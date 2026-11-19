"""
Offline tests for PHX booking links in quote emails. Jobber and the booking
site are faked; nothing is sent anywhere.

    venv\\Scripts\\python.exe -m unittest discover tests -v
"""
import base64
import email
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import booking  # noqa: E402

ENV = {"BOOKING_INVITE_SECRET": "s3cret", "JOBBER_CLIENT_ID": "cid", "JOBBER_CLIENT_SECRET": "csec",
       "JOBBER_REFRESH_TOKEN": "rt", "BOOKING_MARKETS": "PHX", "BOOKING_WAIT_MINUTES": "10"}
LINK = "https://cleanaffinitybooking.com/?invite=abc.def"


def gid(n):
    return base64.b64encode(f"gid://Jobber/Client/{n}".encode()).decode()


class FakeServices:
    """Jobber (token + GraphQL) and the booking site's invite endpoint."""

    def __init__(self):
        self.clients = []         # Jobber client nodes
        self.calls = []
        self.jobber_down = False
        self.invite_down = False

    def add_client(self, number, *emails, created="2026-11-19T10:00:00Z"):
        self.clients.append({"id": gid(number), "createdAt": created,
                             "emails": [{"address": e} for e in emails]})

    def __call__(self, url, timeout=None, headers=None, data=None, json=None):
        self.calls.append((url, headers, data, json))
        resp = mock.Mock(status_code=200)
        if url == booking.TOKEN_URL:
            assert data["grant_type"] == "refresh_token" and data["refresh_token"] == "rt"
            resp.json.return_value = {"access_token": "at", "refresh_token": "rt"}
        elif url == booking.GRAPHQL_URL:
            assert headers["Authorization"] == "Bearer at"
            if self.jobber_down:
                resp.status_code, resp.text = 503, "unavailable"
            term = json["variables"]["t"].lower()
            hits = [c for c in self.clients
                    if any(term.split("@")[0] in e["address"].lower() for e in c["emails"])]
            resp.json.return_value = {"data": {"clients": {"nodes": hits}}}
        elif url == booking.INVITE_URL:
            assert headers["Authorization"] == "Bearer s3cret"
            if self.invite_down:
                resp.status_code, resp.text = 500, "boom"
            resp.json.return_value = {"bookingUrl": f"{LINK}&c={json['clientId']}", "expiresInDays": 7}
        else:
            raise AssertionError(url)
        return resp

    def invites(self):
        return [c[3] for c in self.calls if c[0] == booking.INVITE_URL]


class Base(unittest.TestCase):
    def setUp(self):
        booking.reset()
        booking._token.update(value=None, expires=0)
        self.svc = FakeServices()
        self.now = 1_800_000_000.0
        self.patches = [mock.patch.dict(os.environ, ENV),
                        mock.patch.object(booking.requests, "post", self.svc)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        booking.reset()

    def prepare(self, email="ann@example.com", market="PHX", minutes_old=1):
        return booking.prepare(email, market, received=self.now - minutes_old * 60, now=self.now)


class Prepare(Base):
    def test_found_client_gets_a_link_for_its_id_and_email(self):
        self.svc.add_client(154959839, "Ann@Example.com")
        self.assertEqual(self.prepare(), "ready")
        self.assertEqual(self.svc.invites(), [{"clientId": "154959839", "email": "ann@example.com"}])
        self.assertEqual(booking.link_for("ANN@example.com"), LINK + "&c=154959839")
        self.assertEqual(booking.placeholder("ann@example.com"), booking.MARKER)

    def test_other_markets_never_look_anything_up(self):
        for market in ("PDX", "DFW"):
            self.assertEqual(self.prepare(market=market), "none")
        self.assertEqual(self.svc.calls, [])
        self.assertEqual(booking.placeholder("ann@example.com"), "")

    def test_no_client_yet_waits_then_sends_without(self):
        self.assertEqual(self.prepare(minutes_old=2), "wait")
        self.assertEqual(self.prepare(minutes_old=9), "wait")
        self.assertEqual(self.prepare(minutes_old=11), "none")
        self.assertEqual(self.svc.invites(), [])
        self.assertEqual(booking.placeholder("ann@example.com"), "")

    def test_client_appearing_during_the_wait_gets_the_link(self):
        self.assertEqual(self.prepare(minutes_old=1), "wait")
        self.svc.add_client(42, "ann@example.com")
        self.assertEqual(self.prepare(minutes_old=2), "ready")

    def test_only_an_exact_email_match_counts(self):
        self.svc.add_client(1, "ann@example.org")      # fuzzy search hit, different address
        self.assertEqual(self.prepare(minutes_old=30), "none")
        self.assertEqual(self.svc.invites(), [])

    def test_newest_client_wins_when_there_are_several(self):
        self.svc.add_client(1, "ann@example.com", created="2025-01-01T00:00:00Z")
        self.svc.add_client(2, "ann@example.com", created="2026-11-19T00:00:00Z")
        self.prepare()
        self.assertEqual(self.svc.invites()[0]["clientId"], "2")

    def test_jobber_down_waits_then_sends_without(self):
        self.svc.add_client(1, "ann@example.com")
        self.svc.jobber_down = True
        self.assertEqual(self.prepare(minutes_old=1), "wait")
        self.assertEqual(self.prepare(minutes_old=15), "none")

    def test_booking_site_down_waits_then_sends_without(self):
        self.svc.add_client(1, "ann@example.com")
        self.svc.invite_down = True
        self.assertEqual(self.prepare(minutes_old=1), "wait")
        self.assertEqual(self.prepare(minutes_old=15), "none")

    def test_old_lead_from_the_daytime_backlog_is_looked_up_once(self):
        self.svc.add_client(1, "ann@example.com")
        self.assertEqual(self.prepare(minutes_old=8 * 60), "ready")

    def test_not_configured_sends_without_and_calls_nothing(self):
        with mock.patch.dict(os.environ, {"JOBBER_REFRESH_TOKEN": ""}):
            self.assertEqual(self.prepare(), "none")
        self.assertEqual(self.svc.calls, [])

    def test_one_decision_per_lead_per_run(self):
        self.svc.add_client(1, "ann@example.com")
        self.prepare()
        self.prepare()
        self.assertEqual(len(self.svc.invites()), 1)

    def test_token_is_reused_within_the_hour(self):
        self.svc.add_client(1, "a@example.com")
        self.svc.add_client(2, "b@example.com")
        self.prepare("a@example.com")
        self.prepare("b@example.com")
        self.assertEqual(sum(1 for c in self.svc.calls if c[0] == booking.TOKEN_URL), 1)


class Rendering(Base):
    def test_button_replaces_its_own_line_and_plain_text_gets_the_link(self):
        import add_to_spreadsheet as ats
        self.svc.add_client(1, "ann@example.com")
        self.prepare()
        text = f"Hi Ann!\nPick a time:\n{booking.MARKER}\nThanks"
        out = booking.render_html(ats.convert_text_to_html(text), "ann@example.com")
        self.assertIn(f'href="{LINK}&amp;c=1"', out)
        self.assertIn("Book your cleaning</a>", out)
        self.assertNotIn(booking.MARKER, out)
        self.assertNotIn("<p><table", out)
        self.assertEqual(booking.render_text(text, "ann@example.com"),
                         f"Hi Ann!\nPick a time:\nBook your cleaning: {LINK}&c=1\nThanks")

    def test_no_link_leaves_no_trace(self):
        text = f"Hi\n{booking.MARKER}\nBye"
        self.assertNotIn(booking.MARKER, booking.render_html(text, "x@example.com"))
        self.assertEqual(booking.render_text(text, "x@example.com"), "Hi\n\nBye")


class Scripts(Base):
    """{booking_link} in the scripts sheet."""

    def setUp(self):
        super().setUp()
        import add_to_spreadsheet as ats
        self.ats = ats
        pricing = {"initial": 250, "ot": 300, "move": 400, "weekly": 120, "biweekly": 140, "monthly": 170}
        self.calc = lambda market, email: ats.autocalc(1500, 3, 2, 3, "Ann", "Lee", "Joel", "Phoenix",
                                                       market, pricing, email=email)
        self.script = mock.patch.object(ats, "get_email_script",
                                        lambda k, m, t: "Hi {name}, ${initial}.\n{booking_link}\nThanks")
        self.title = mock.patch.object(ats, "get_title", lambda k, m, t: "Quote {sqft}")
        self.script.start()
        self.title.start()

    def tearDown(self):
        self.script.stop()
        self.title.stop()
        super().tearDown()

    def test_placeholder_never_breaks_an_email(self):
        for market in ("PDX", "DFW", "PHX"):  # no link: blank, no KeyError
            _, body, _, _ = self.calc(market, "ann@example.com")
            self.assertEqual(body, "Hi Ann, $250.\n\nThanks")

    def test_phx_lead_with_a_link_gets_the_marker(self):
        self.svc.add_client(1, "ann@example.com")
        self.prepare()
        _, body, _, _ = self.calc("PHX", "ann@example.com")
        self.assertEqual(body, f"Hi Ann, $250.\n{booking.MARKER}\nThanks")

    def test_booking_link_in_a_text_script_holds_the_text(self):
        with mock.patch.object(self.ats, "get_text_script", lambda k, m, t: "Book: {booking_link}"):
            _, _, fill, meta = self.calc("PHX", "ann@example.com")
            text, problem = self.ats.build_text("PHX", meta["send_type"], fill)
        self.assertIsNone(text)
        self.assertIn("unknown placeholder {booking_link}", problem)

    def test_sent_email_carries_the_button(self):
        self.svc.add_client(1, "ann@example.com")
        self.prepare()
        service = mock.MagicMock()
        self.ats.create_draft(service, "Clean Affinity", "me@example.com", "Quote",
                              f"Hi Ann\n{booking.MARKER}\nThanks", "ann@example.com", "PHX")
        raw = service.users().drafts().create.call_args.kwargs["body"]["message"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw))
        parts = {p.get_content_type(): p.get_payload(decode=True).decode() for p in msg.walk()
                 if not p.is_multipart()}
        self.assertIn(f'href="{LINK}&amp;c=1"', parts["text/html"])
        self.assertIn(f"Book your cleaning: {LINK}&c=1", parts["text/plain"])
        self.assertNotIn(booking.MARKER, parts["text/html"] + parts["text/plain"])


class EmailRun(Base):
    """A PHX lead waiting for its Jobber client stays queued; nothing is emailed yet."""

    def run_with(self, minutes_old):
        import autoemailing as ae
        msgs = [{"id": "m0", "body": "x", "received": time.time() - minutes_old * 60}]
        lead = ("Lee, Ann", "weekly", "ann@example.com", "1500", "3", "2",
                ("1", "Phoenix"), "4805551234", "", "")
        seen = {}
        with mock.patch.object(ae, "authenticate_gmail", return_value=mock.MagicMock()), \
                mock.patch.object(ae, "build", return_value=mock.MagicMock()), \
                mock.patch.object(ae, "get_label_ids_by_name",
                                  return_value={"Automations": "L1", "DFW": "L2", "PHX": "L3"}), \
                mock.patch.object(ae, "fetch_emails", return_value=([], [], msgs)), \
                mock.patch.object(ae, "get_cleaned_body", side_effect=lambda b: b), \
                mock.patch.object(ae, "parse_email_details", return_value=lead), \
                mock.patch.object(ae, "add_to_spreadsheet", return_value=[]) as sheet, \
                mock.patch.object(ae, "relabel_messages",
                                  side_effect=lambda svc, ids, label: seen.setdefault(label, []).extend(ids)), \
                mock.patch.object(ae.ghl_sync, "sync_quotes"):
            ae.run_automation()
        return seen, sheet.call_args[0][0]

    def test_waiting_lead_keeps_its_queue_label(self):
        seen, sheet_leads = self.run_with(minutes_old=2)
        self.assertEqual(sheet_leads, [])
        self.assertEqual(seen.get("AutomatedEmailSent", []), [])

    def test_after_the_wait_it_is_emailed_anyway(self):
        seen, sheet_leads = self.run_with(minutes_old=12)
        self.assertEqual(len(sheet_leads), 1)
        self.assertEqual(seen["AutomatedEmailSent"], ["m0"])

    def test_with_a_link_it_goes_straight_out(self):
        self.svc.add_client(1, "ann@example.com")
        seen, sheet_leads = self.run_with(minutes_old=1)
        self.assertEqual(seen["AutomatedEmailSent"], ["m0"])
        self.assertEqual(booking.link_for("ann@example.com"), LINK + "&c=1")


if __name__ == "__main__":
    unittest.main()

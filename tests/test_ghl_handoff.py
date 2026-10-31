"""
Offline tests for the quote -> GHL text handoff.

No network: the GHL API and the scripts/estimator sheets are faked.
Run from the repo root:  python -m unittest discover tests -v
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import add_to_spreadsheet as ats  # noqa: E402
import ghl_sync  # noqa: E402

SCRIPT_TYPES = ["ONETIME", "MOVE", "WEEKLY", "BIWEEKLY", "MONTHLY"]

PRICING = {
    "initial": Decimal("250.4"), "ot": Decimal("310.5"), "move": Decimal("420"),
    "weekly": Decimal("120"), "biweekly": Decimal("140.5"), "monthly": Decimal("175"),
}

EMAIL_TEMPLATE = ("Hi {name}! Normally ${initial_full}, 50% off just ${initial}. "
                  "Service ${recurring}. {date_month} {username}")
TITLE_TEMPLATE = "{name_section}Cleans {sqft} sqft, {beds} Bed, {baths} Bath"
TEXT_TEMPLATE = ("Hi {name}, {username} here. Your {sqft} sqft, {beds} beds / {baths} bath home: "
                 "first clean ${initial} with 50% off, then ${recurring}.")
TEXT_TEMPLATE_ONETIME = "Hi {name}, your {sqft} sqft clean would be ${initial}."

EMAIL = "ann@example.com"
PHONE = "+15035551234"


def old_autocalc(sqft, beds, baths, type_clean_numerical, name_first, name_last, username, city, market, pricing):
    """autocalc() exactly as it was before this change, for comparison."""
    type_converter = ['', 'initial', 'ot', 'move', 'weekly', 'biweekly', 'monthly']
    type_clean = type_converter[type_clean_numerical + 2]
    initial = pricing['initial']
    ongoing = pricing[type_clean]
    elite = initial if type_clean not in ("ot", "move") else pricing[type_clean]
    name_section = f"{name_last}, {name_first} - " if name_first.strip() else ""
    send = "onetime" if type_clean == "ot" else type_clean
    body = ats.get_email_script("quote_text", market, send).format(
        name=name_first, last=name_last, first=name_first, date_month=ats.month,
        initial=round(elite), initial_full=round(elite * 2), recurring=round(ongoing),
        username=username)
    title = ats.get_title("quote_text", market, send).format(
        name_section=name_section, sqft=sqft, beds=ats.clean_number(beds), baths=ats.clean_number(baths))
    return title, body


class FakeGHL:
    """In-memory stand-in for several sub-accounts, keyed by location ID."""

    def __init__(self):
        self.contacts = {}  # location_id -> {contact_id: contact}
        self.calls = []
        self.sms = []        # (location_id, contact_id, message, body)
        self.send_error = None  # exception to raise on the next send

    def add_contact(self, location_id, contact_id="c1", email=EMAIL, phone=PHONE,
                    tags=("auto text",), dnd=False, updated="2026-10-28"):
        self.contacts.setdefault(location_id, {})[contact_id] = {
            "id": contact_id, "email": email, "phone": phone, "tags": list(tags),
            "dnd": dnd, "dateUpdated": updated, "fields": {}}
        return self.contacts[location_id][contact_id]

    def contact(self, location_id, contact_id="c1"):
        return self.contacts[location_id][contact_id]

    def field(self, location_id, key, contact_id="c1"):
        return self.contact(location_id, contact_id)["fields"].get(f"{location_id}_{key}")

    def view(self, c):
        out = {k: v for k, v in c.items() if k != "fields"}
        out["customFields"] = [{"id": k, "value": v} for k, v in c["fields"].items()]
        return out

    def __call__(self, client, method, path, headers=None, **kw):
        loc = client.location_id
        self.calls.append((loc, client.session.headers["Authorization"], method, path))
        book = self.contacts.setdefault(loc, {})
        if path == "/conversations/messages":
            assert headers == {"Version": "2021-04-15"}
            if self.send_error:
                err, self.send_error = self.send_error, None
                raise err
            body = kw["json"]
            assert body["type"] == "SMS"
            self.sms.append((loc, body["contactId"], body["message"], body))
            return {"messageId": f"m{len(self.sms)}", "conversationId": "conv"}
        if path.endswith("/customFields"):
            return {"customFields": [{"id": f"{loc}_{k}", "fieldKey": f"contact.{k}"}
                                     for k in ghl_sync.QUOTE_FIELDS]}
        if path == "/contacts/search":
            f = kw["json"]["filters"][0]
            hits = [self.view(c) for c in book.values()
                    if (c.get(f["field"]) or "").lower() == str(f["value"]).lower()]
            return {"contacts": hits, "total": len(hits)}
        cid = path.split("/")[2]
        c = book[cid]
        if method == "GET":
            return {"contact": self.view(c)}
        if method == "PUT":
            body = kw["json"]
            assert not {"dnd", "dndSettings", "tags", "locationId"} & set(body), body
            for f in body.get("customFields", []):
                c["fields"][f["id"]] = f["field_value"]
            if "phone" in body:
                c["phone"] = body["phone"]
            return {"contact": self.view(c)}
        if path.endswith("/tags") and method == "POST":
            tags = [t.lower() for t in kw["json"]["tags"]]
            assert "auto text" not in tags, "the consent tag must never be written"
            c["tags"] = sorted(set(c["tags"]) | set(tags))
            return {}
        raise AssertionError(f"unexpected call {method} {path}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.texting = {}  # (market, type) -> override texting cell

        def text_script(key, market, type_):
            return self.texting.get((market, type_.upper()),
                                    TEXT_TEMPLATE_ONETIME if type_.upper() in ("ONETIME", "MOVE") else TEXT_TEMPLATE)

        self.ghl = FakeGHL()
        self.patches = [
            mock.patch.object(ghl_sync, "LEDGER_PATH", os.path.join(self.tmp, "ledger.sqlite3")),
            mock.patch.object(ats, "get_email_script", lambda k, m, t: EMAIL_TEMPLATE),
            mock.patch.object(ats, "get_title", lambda k, m, t: TITLE_TEMPLATE),
            mock.patch.object(ats, "get_text_script", text_script),
            mock.patch.dict(os.environ, {
                "GHL_SYNC": "live",
                "GHL_PDX_LOCATION_ID": "loc_pdx", "GHL_PDX_TOKEN": "tok_pdx",
                "GHL_DFW_LOCATION_ID": "loc_dfw", "GHL_DFW_TOKEN": "tok_dfw",
                "GHL_PHX_LOCATION_ID": "loc_phx", "GHL_PHX_TOKEN": "tok_phx",
            }),
            mock.patch.object(ghl_sync.GHLClient, "_call",
                              lambda client, m, p, headers=None, **kw: self.ghl(client, m, p, headers, **kw)),
        ]
        # Texting hours are open unless a test says otherwise, so results
        # don't depend on what time the suite is run.
        self.hours_open = True
        self.patches.append(mock.patch.object(ghl_sync, "texting_open", lambda market, now=None, since=None: self.hours_open))
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def quote(self, market="PDX", service="BIWEEKLY", pricing=PRICING,
              phone="503-555-1234", service_known=True, email=EMAIL):
        idx = SCRIPT_TYPES.index(service)
        sub, body, fill, meta = ats.autocalc(1500, 3.0, 2.0, idx, "Ann", "Lee", "Joel", "Portland", market, pricing)
        problems = [] if service_known else ["unknown service type 'deep'"]
        text, problem = ats.build_text(market, meta["send_type"], fill)
        if problem:
            problems.append(problem)
        return body, ghl_sync.build_quote(market, "Ann", "Lee", email, phone,
                                          fill, meta, text, problems, "")

    def status(self, quote):
        conn = sqlite3.connect(ghl_sync.LEDGER_PATH)
        try:
            return conn.execute("SELECT status, detail FROM ghl_quotes WHERE quote_id=?",
                                (quote["quote_id"],)).fetchone()
        finally:
            conn.close()

    def age(self, quote, minutes):
        """Pretend the quote was first seen `minutes` ago."""
        conn = sqlite3.connect(ghl_sync.LEDGER_PATH)
        then = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        conn.execute("UPDATE ghl_quotes SET first_seen=? WHERE quote_id=?", (then, quote["quote_id"]))
        conn.commit()
        conn.close()

    def tag_calls(self):
        return [c for c in self.ghl.calls if c[3].endswith("/tags")]

    def sent(self, location_id="loc_pdx"):
        return [s[2] for s in self.ghl.sms if s[0] == location_id]


class EmailUnchanged(Base):
    def test_email_title_and_body_identical_to_before(self):
        for idx, service in enumerate(SCRIPT_TYPES):
            with self.subTest(service=service):
                new = ats.autocalc(1500, 3.0, 2.5, idx, "Ann", "Lee", "Joel", "Portland", "PDX", PRICING)[:2]
                old = old_autocalc(1500, 3.0, 2.5, idx, "Ann", "Lee", "Joel", "Portland", "PDX", PRICING)
                self.assertEqual(new, old)


class SharedPrices(Base):
    def test_text_and_fields_use_the_emailed_prices(self):
        body, q = self.quote(service="BIWEEKLY")
        # Rounded as the email rounds: 250.4 -> 250, x2 -> 501, 140.5 -> 140 (half-even)
        self.assertIn("just $250", body)
        self.assertIn("Normally $501", body)
        self.assertIn("Service $140", body)
        self.assertIn("first clean $250", q["fields"]["quote_sms_text"])
        self.assertIn("then $140", q["fields"]["quote_sms_text"])
        self.assertEqual((q["fields"]["quote_initial"], q["fields"]["quote_initial_full"],
                          q["fields"]["quote_recurring"]), ("250", "501", "140"))

    def test_one_time_and_move_carry_no_recurring_price(self):
        for service, price in (("ONETIME", "310"), ("MOVE", "420")):
            with self.subTest(service=service):
                _, q = self.quote(service=service)
                self.assertEqual(q["fields"]["quote_initial"], price)
                self.assertEqual(q["fields"]["quote_recurring"], "")
                self.assertEqual(q["problems"], [])


class ServiceNames(unittest.TestCase):
    def test_biweekly_is_not_matched_as_weekly(self):
        self.assertEqual(ats.normalize_service_type("biweekly deep"), "BIWEEKLY")
        self.assertEqual(ats.normalize_service_type("Bi-Weekly"), "BIWEEKLY")
        self.assertEqual(ats.normalize_service_type("weekly"), "WEEKLY")
        self.assertEqual(ats.normalize_service_type("weekly deep"), "WEEKLY")
        self.assertEqual(ats.normalize_service_type("monthly"), "MONTHLY")
        self.assertEqual(ats.normalize_service_type("move out"), "MOVE")

    def test_unknown_service_is_reported_not_guessed(self):
        self.assertIsNone(ats.normalize_service_type("deep"))


class BlockedTexts(Base):
    def assert_held_without_ghl(self, q, reason_part):
        ghl_sync.sync_quotes([q])
        status, detail = self.status(q)
        self.assertEqual(status, "held")
        self.assertIn(reason_part, detail)
        self.assertEqual(self.ghl.calls, [])

    def test_empty_texting_cell(self):
        self.texting[("PDX", "BIWEEKLY")] = "   "
        self.assert_held_without_ghl(self.quote()[1], "texting cell is empty")

    def test_unknown_placeholder(self):
        self.texting[("PDX", "BIWEEKLY")] = "Hi {name}, see {calendar_link}"
        self.assert_held_without_ghl(self.quote()[1], "unknown placeholder {calendar_link}")

    def test_unknown_service(self):
        self.assert_held_without_ghl(self.quote(service_known=False)[1], "unknown service type")

    def test_zero_required_price(self):
        self.assert_held_without_ghl(self.quote(pricing=dict(PRICING, initial=Decimal(0)))[1],
                                     "first-clean price")

    def test_zero_service_price(self):
        self.assert_held_without_ghl(self.quote(pricing=dict(PRICING, biweekly=Decimal(0)))[1],
                                     "biweekly price")

    def test_zero_unused_price_is_fine(self):
        _, q = self.quote(service="MOVE", pricing=dict(PRICING, weekly=Decimal(0), initial=Decimal(0)))
        self.assertEqual(q["problems"], [])

    def test_no_phone(self):
        self.assert_held_without_ghl(self.quote(phone="")[1], "no valid phone")


class Consent(Base):
    def test_auto_text_tag_saves_quote_then_sends_the_same_message(self):
        self.ghl.add_contact("loc_pdx", tags=["auto text", "web form"])
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q), ("sent", "message m1"))
        self.assertEqual(self.sent(), [q["fields"]["quote_sms_text"]])
        self.assertEqual(self.ghl.field("loc_pdx", "quote_sms_text"), q["fields"]["quote_sms_text"])
        self.assertEqual(self.ghl.field("loc_pdx", "quote_id"), q["quote_id"])
        self.assertEqual(set(self.ghl.contact("loc_pdx")["tags"]), {"auto text", "web form", "quote-texted"})
        # Order: save quote -> read back -> mark quote_id -> send -> tag
        steps = [c[2] + " " + c[3] for c in self.ghl.calls]
        send = steps.index("POST /conversations/messages")
        puts = [i for i, s in enumerate(steps) if s.startswith("PUT")]
        self.assertEqual(len(puts), 2)
        self.assertLess(puts[1], send)
        self.assertGreater(steps.index("POST /contacts/c1/tags"), send)

    def test_no_auto_text_tag_waits_then_holds(self):
        self.ghl.add_contact("loc_pdx", tags=["web form"])
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q)[0], "waiting")
        self.assertEqual(self.tag_calls(), [])
        # The quote is still saved on the contact
        self.assertEqual(self.ghl.field("loc_pdx", "quote_initial"), "250")
        self.age(q, ghl_sync.CONSENT_WAIT_MINUTES + 1)
        ghl_sync.sync_quotes([])
        self.assertEqual(self.status(q), ("held", "no 'auto text' tag on the contact"))
        self.assertEqual(self.ghl.sms, [])

    def test_tag_arriving_late_still_sends(self):
        c = self.ghl.add_contact("loc_pdx", tags=[])
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q)[0], "waiting")
        c["tags"].append("auto text")  # GHL's workflow catches up
        ghl_sync.sync_quotes([])
        self.assertEqual(self.status(q)[0], "sent")
        self.assertEqual(len(self.ghl.sms), 1)

    def test_dnd_blocks_even_with_auto_text(self):
        self.ghl.add_contact("loc_pdx", dnd=True)
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q), ("held", "contact has SMS DND/STOP active"))
        self.assertEqual(self.ghl.sms, [])


class Matching(Base):
    def test_no_contact_waits_then_holds_and_never_creates_one(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q), ("waiting", "no matching contact in GHL"))
        self.age(q, ghl_sync.CONSENT_WAIT_MINUTES + 1)
        ghl_sync.sync_quotes([])
        self.assertEqual(self.status(q)[0], "held")
        self.assertEqual(self.ghl.contacts.get("loc_pdx"), {})

    def test_matches_by_email_and_fills_missing_phone(self):
        self.ghl.add_contact("loc_pdx", phone=None)  # like the web-form contacts: email only
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.ghl.contact("loc_pdx")["phone"], PHONE)
        self.assertEqual(self.status(q)[0], "sent")

    def test_never_replaces_an_existing_phone(self):
        self.ghl.add_contact("loc_pdx", phone="+19715550000")
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.ghl.contact("loc_pdx")["phone"], "+19715550000")

    def test_matches_by_phone_when_email_differs(self):
        self.ghl.add_contact("loc_pdx", email="other@example.com")
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q)[0], "sent")

    def test_prefers_the_duplicate_with_consent(self):
        self.ghl.add_contact("loc_pdx", "old", tags=[], updated="2026-10-29")
        self.ghl.add_contact("loc_pdx", "new", tags=["auto text"], updated="2026-10-01")
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual([s[1] for s in self.ghl.sms], ["new"])
        self.assertEqual(self.ghl.contact("loc_pdx", "old")["fields"], {})


class Routing(Base):
    def test_each_market_goes_to_its_own_sub_account(self):
        for m in ("PDX", "DFW", "PHX"):
            self.ghl.add_contact(f"loc_{m.lower()}")
        quotes = {m: self.quote(market=m)[1] for m in ("PDX", "DFW", "PHX")}
        ghl_sync.sync_quotes(list(quotes.values()))
        for market, q in quotes.items():
            loc, tok = f"loc_{market.lower()}", f"Bearer tok_{market.lower()}"
            with self.subTest(market=market):
                self.assertEqual(self.ghl.field(loc, "quote_id"), q["quote_id"])
                self.assertEqual(self.sent(loc), [q["fields"]["quote_sms_text"]])
                self.assertTrue(all(c[1] == tok for c in self.ghl.calls if c[0] == loc))

    def test_from_number_is_used_when_configured(self):
        self.ghl.add_contact("loc_pdx")
        with mock.patch.dict(os.environ, {"GHL_PDX_FROM_NUMBER": "+15035550100"}):
            ghl_sync.sync_quotes([self.quote()[1]])
        self.assertEqual(self.ghl.sms[0][3]["fromNumber"], "+15035550100")

    def test_default_number_when_not_configured(self):
        self.ghl.add_contact("loc_pdx")
        ghl_sync.sync_quotes([self.quote()[1]])
        self.assertNotIn("fromNumber", self.ghl.sms[0][3])


class Retries(Base):
    def setUp(self):
        super().setUp()
        self.ghl.add_contact("loc_pdx")

    def test_same_quote_again_sends_nothing(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        before = len(self.ghl.calls)
        ghl_sync.sync_quotes([q])
        ghl_sync.sync_quotes([q])
        self.assertEqual(len(self.ghl.calls), before)
        self.assertEqual(len(self.ghl.sms), 1)

    def test_lost_ledger_after_send_does_not_resend(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        os.remove(ghl_sync.LEDGER_PATH)
        ghl_sync.sync_quotes([q])
        self.assertEqual(len(self.ghl.sms), 1)
        self.assertEqual(self.status(q), ("sent", "recovered"))

    def test_crash_mid_send_is_never_resent(self):
        _, q = self.quote()
        # The run died after marking the attempt, before recording the result.
        with mock.patch.object(ghl_sync.GHLClient, "send_sms", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q)[0], "sending")
        ghl_sync.sync_quotes([q])
        ghl_sync.sync_quotes([])
        self.assertEqual(self.ghl.sms, [])
        self.assertEqual(self.status(q)[0], "sending")
        # Even with the ledger gone, the contact's quote_id stops a resend.
        os.remove(ghl_sync.LEDGER_PATH)
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.ghl.sms, [])
        self.assertEqual(self.status(q)[0], "held")

    def test_send_timeout_is_held_not_retried(self):
        import requests
        self.ghl.send_error = requests.Timeout("read timed out")
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        status, detail = self.status(q)
        self.assertEqual(status, "held")
        self.assertIn("send outcome unknown", detail)
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.ghl.sms, [])

    def test_rejected_send_is_rolled_back_and_retried(self):
        self.ghl.send_error = RuntimeError("GHL POST /conversations/messages -> 400")
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q)[0], "failed")
        self.assertEqual(self.ghl.field("loc_pdx", "quote_id"), "")
        ghl_sync.sync_quotes([])
        self.assertEqual(self.status(q)[0], "sent")
        self.assertEqual(len(self.ghl.sms), 1)

    def test_new_quote_for_same_contact_is_not_texted_again_within_a_day(self):
        _, q1 = self.quote()
        ghl_sync.sync_quotes([q1])
        _, q2 = self.quote(pricing=dict(PRICING, biweekly=Decimal(160)))
        self.assertNotEqual(q1["quote_id"], q2["quote_id"])
        ghl_sync.sync_quotes([q2])
        self.assertEqual(self.status(q2), ("held", "this lead was already texted a quote in the last 24h"))
        self.assertEqual(len(self.ghl.sms), 1)

    def test_new_quote_after_a_day_is_sent(self):
        _, q1 = self.quote()
        ghl_sync.sync_quotes([q1])
        conn = sqlite3.connect(ghl_sync.LEDGER_PATH)
        conn.execute("UPDATE ghl_quotes SET updated_at=?",
                     ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),))
        conn.commit(); conn.close()
        _, q2 = self.quote(pricing=dict(PRICING, biweekly=Decimal(160)))
        ghl_sync.sync_quotes([q2])
        self.assertEqual(self.status(q2)[0], "sent")
        self.assertIn("$160", self.ghl.sms[1][2])

    def test_ghl_outage_is_retried_and_never_raises(self):
        _, q = self.quote()
        with mock.patch.object(ghl_sync.GHLClient, "_call", side_effect=RuntimeError("503")):
            ghl_sync.sync_quotes([q])  # must not raise
        self.assertEqual(self.status(q)[0], "failed")
        ghl_sync.sync_quotes([])  # next run picks it up from the ledger
        self.assertEqual(self.status(q)[0], "sent")


class OneTextPerLead(Base):
    """Duplicate leads: text only the highest frequency, like the email does."""

    def setUp(self):
        super().setUp()
        self.ghl.add_contact("loc_pdx")

    def test_overnight_weekly_and_biweekly_send_only_weekly(self):
        # The Bradford case: both forms queued overnight, released together at 8am.
        for order in (("BIWEEKLY", "WEEKLY"), ("WEEKLY", "BIWEEKLY")):
            with self.subTest(order=order):
                self.ghl = FakeGHL()
                self.ghl.add_contact("loc_pdx")
                if os.path.exists(ghl_sync.LEDGER_PATH):
                    os.remove(ghl_sync.LEDGER_PATH)
                self.hours_open = False
                quotes = {s: self.quote(service=s)[1] for s in order}
                for s in order:
                    ghl_sync.sync_quotes([quotes[s]])  # separate runs, evening
                self.assertEqual(self.ghl.sms, [])
                self.hours_open = True
                ghl_sync.sync_quotes([])  # 8am
                self.assertEqual(len(self.ghl.sms), 1)
                self.assertEqual(self.status(quotes["WEEKLY"])[0], "sent")
                self.assertEqual(self.status(quotes["BIWEEKLY"]),
                                 ("held", "superseded by this lead's weekly quote"))

    def test_same_run_picks_highest_frequency(self):
        quotes = [self.quote(service=s)[1] for s in ("ONETIME", "MONTHLY", "MOVE", "BIWEEKLY")]
        ghl_sync.sync_quotes(quotes)
        self.assertEqual(len(self.ghl.sms), 1)
        self.assertEqual(self.status(quotes[3])[0], "sent")

    def test_same_phone_different_email_is_the_same_lead(self):
        _, q1 = self.quote(service="WEEKLY")
        _, q2 = self.quote(service="MONTHLY", email="other@example.com")
        ghl_sync.sync_quotes([q2, q1])
        self.assertEqual(len(self.ghl.sms), 1)
        self.assertEqual(self.status(q1)[0], "sent")

    def test_different_people_both_get_their_text(self):
        self.ghl.add_contact("loc_pdx", "c2", email="bob@example.com", phone="+15035559999")
        _, q1 = self.quote()
        _, q2 = self.quote(email="bob@example.com", phone="503-555-9999")
        ghl_sync.sync_quotes([q1, q2])
        self.assertEqual(len(self.ghl.sms), 2)

    def test_same_person_in_another_market_is_separate(self):
        self.ghl.add_contact("loc_dfw")
        ghl_sync.sync_quotes([self.quote()[1], self.quote(market="DFW")[1]])
        self.assertEqual(len(self.ghl.sms), 2)


class Modes(Base):
    def test_off_sends_nothing(self):
        with mock.patch.dict(os.environ, {"GHL_SYNC": "off"}):
            ghl_sync.sync_quotes([self.quote()[1]])
        self.assertEqual(self.ghl.calls, [])

    def test_fields_mode_saves_but_never_marks_ready(self):
        self.ghl.add_contact("loc_pdx")
        _, q = self.quote()
        with mock.patch.dict(os.environ, {"GHL_SYNC": "fields"}):
            ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q), ("staged", "saved; GHL_SYNC=fields; would send"))
        self.assertEqual(self.ghl.field("loc_pdx", "quote_sms_text"), q["fields"]["quote_sms_text"])
        self.assertEqual(self.ghl.sms, [])
        self.assertEqual(self.tag_calls(), [])

    def test_fields_mode_reports_missing_consent(self):
        self.ghl.add_contact("loc_pdx", tags=[])
        _, q = self.quote()
        with mock.patch.dict(os.environ, {"GHL_SYNC": "fields"}):
            ghl_sync.sync_quotes([q])
        self.assertEqual(self.status(q)[1], "saved; GHL_SYNC=fields; would hold: no 'auto text' tag")


class TextingHours(unittest.TestCase):
    """The real clock logic, with explicit instants (no patching)."""
    PDX, DFW = "America/Los_Angeles", "America/Chicago"
    # Wed 28 Oct 2026 is a weekday; Sat 31 Oct is a weekend day.
    WED, FRI, SAT, SUN = 28, 30, 31, 1

    def at(self, day, hhmm, tz=PDX):
        h, m = map(int, hhmm.split(":"))
        month = 11 if day < 10 else 10
        return datetime(2026, month, day, h, m, tzinfo=ZoneInfo(tz))

    def new_quote_open(self, day, hhmm, market="PDX", tz=PDX):
        return ghl_sync.texting_open(market, self.at(day, hhmm, tz))

    def test_weekday_new_quotes_text_only_6pm_to_730pm(self):
        for hhmm, expected in [("07:59", False), ("08:00", False), ("12:00", False),
                               ("17:59", False), ("18:00", True), ("19:29", True),
                               ("19:30", False), ("23:00", False)]:
            self.assertEqual(self.new_quote_open(self.WED, hhmm), expected, hhmm)

    def test_weekend_new_quotes_text_8am_to_730pm(self):
        for day in (self.SAT, self.SUN):
            for hhmm, expected in [("07:59", False), ("08:00", True), ("12:00", True),
                                   ("19:29", True), ("19:30", False)]:
                self.assertEqual(self.new_quote_open(day, hhmm), expected, (day, hhmm))

    def test_evening_quote_goes_out_at_8am_next_morning_even_on_a_weekday(self):
        since = self.at(self.WED, "20:15")
        opening = ghl_sync.next_opening("PDX", since, since=since)
        self.assertEqual((opening.day, opening.hour, opening.minute), (29, 8, 0))  # Thursday
        self.assertFalse(ghl_sync.texting_open("PDX", self.at(29, "07:59"), since=since))
        self.assertTrue(ghl_sync.texting_open("PDX", self.at(29, "08:00"), since=since))
        self.assertTrue(ghl_sync.texting_open("PDX", self.at(29, "08:05"), since=since))

    def test_after_midnight_quote_goes_out_at_8am_same_day(self):
        since = self.at(29, "01:30")
        self.assertFalse(ghl_sync.texting_open("PDX", self.at(29, "07:00"), since=since))
        self.assertTrue(ghl_sync.texting_open("PDX", self.at(29, "08:00"), since=since))

    def test_friday_night_quote_goes_out_saturday_8am(self):
        since = self.at(self.FRI, "21:00")
        opening = ghl_sync.next_opening("PDX", since, since=since)
        self.assertEqual((opening.day, opening.hour), (self.SAT, 8))

    def test_weekday_daytime_quote_waits_for_6pm(self):
        since = self.at(self.WED, "10:00")
        self.assertFalse(ghl_sync.texting_open("PDX", self.at(self.WED, "17:59"), since=since))
        self.assertTrue(ghl_sync.texting_open("PDX", self.at(self.WED, "18:00"), since=since))

    def test_queued_quote_never_texts_after_730pm(self):
        since = self.at(self.WED, "20:00")
        self.assertFalse(ghl_sync.texting_open("PDX", self.at(29, "19:45"), since=since))
        opening = ghl_sync.next_opening("PDX", self.at(29, "19:45"), since=since)
        self.assertEqual((opening.day, opening.hour), (30, 8))

    def test_each_market_uses_its_own_time_zone(self):
        instant = self.at(self.SAT, "18:45")  # 20:45 Dallas, 18:45 Phoenix (no DST)
        self.assertTrue(ghl_sync.texting_open("PDX", instant))
        self.assertFalse(ghl_sync.texting_open("DFW", instant))
        self.assertTrue(ghl_sync.texting_open("PHX", instant))

    def test_hours_are_configurable(self):
        with mock.patch.dict(os.environ, {"GHL_PDX_TEXT_HOURS": "09:00-19:00",
                                          "GHL_PDX_WEEKDAY_TEXT_START": "17:00"}):
            self.assertFalse(self.new_quote_open(self.SAT, "08:30"))
            self.assertFalse(self.new_quote_open(self.SAT, "19:15"))
            self.assertTrue(self.new_quote_open(self.WED, "17:30"))
            self.assertTrue(self.new_quote_open(self.SAT, "08:30", market="DFW"))  # others unchanged
            self.assertFalse(self.new_quote_open(self.WED, "17:30", market="DFW"))


class QuietHours(Base):
    def setUp(self):
        super().setUp()
        self.ghl.add_contact("loc_pdx")
        self.hours_open = False

    def test_after_hours_quote_is_saved_and_scheduled_not_sent(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        status, detail = self.status(q)
        self.assertEqual(status, "scheduled")
        self.assertIn("outside texting hours; sends after", detail)
        self.assertEqual(self.ghl.sms, [])
        self.assertEqual(self.ghl.field("loc_pdx", "quote_sms_text"), q["fields"]["quote_sms_text"])
        self.assertIsNone(self.ghl.field("loc_pdx", "quote_id"))

    def test_waits_quietly_overnight_then_sends_in_the_morning(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        calls = len(self.ghl.calls)
        ghl_sync.sync_quotes([])
        ghl_sync.sync_quotes([q])  # even if the same lead comes round again
        self.assertEqual(len(self.ghl.calls), calls)  # no GHL traffic all night
        self.hours_open = True
        ghl_sync.sync_quotes([])
        self.assertEqual(self.status(q)[0], "sent")
        self.assertEqual(len(self.ghl.sms), 1)

    def test_consent_and_dnd_are_rechecked_in_the_morning(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.ghl.contact("loc_pdx")["dnd"] = True  # they replied STOP overnight
        self.hours_open = True
        ghl_sync.sync_quotes([])
        self.assertEqual(self.status(q), ("held", "contact has SMS DND/STOP active"))
        self.assertEqual(self.ghl.sms, [])

    def test_auto_text_tag_is_required_again_in_the_morning(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.ghl.contact("loc_pdx")["tags"] = []  # tag removed overnight
        self.hours_open = True
        ghl_sync.sync_quotes([])
        self.assertNotIn(self.status(q)[0], ("sent", "sending"))
        self.assertEqual(self.ghl.sms, [])

    def test_morning_script_sends_the_queue_without_emailing(self):
        import runpy
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.hours_open = True
        marked = []
        with mock.patch.object(ats, "batch_get_quotes", side_effect=AssertionError("no quoting")),                 mock.patch.object(ats, "mark_lead_texted", marked.append):
            runpy.run_path(os.path.join(os.path.dirname(__file__), "..", "send_queued_texts.py"),
                           run_name="__main__")
        self.assertEqual(self.status(q)[0], "sent")
        self.assertEqual(len(self.ghl.sms), 1)
        self.assertEqual([m["quote_id"] for m in marked], [q["quote_id"]])

    def test_too_old_is_held_even_once_hours_reopen(self):
        # e.g. the server was stopped for a day and comes back mid-morning
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.age(q, (ghl_sync.SCHEDULE_MAX_HOURS + 1) * 60)
        self.hours_open = True
        ghl_sync.sync_quotes([])
        status, detail = self.status(q)
        self.assertEqual(status, "held")
        self.assertIn("too late to text", detail)
        self.assertEqual(self.ghl.sms, [])

    def test_normal_overnight_delay_is_not_too_old(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q])
        self.age(q, 13 * 60)  # 7:30pm -> 8:30am
        self.hours_open = True
        ghl_sync.sync_quotes([])
        self.assertEqual(self.status(q)[0], "sent")

    def test_fields_mode_reports_when_it_would_send(self):
        _, q = self.quote()
        with mock.patch.dict(os.environ, {"GHL_SYNC": "fields"}):
            ghl_sync.sync_quotes([q])
        self.assertIn("would send after", self.status(q)[1])


class LeadSheetMarking(Base):
    """'emailed' becomes 'emailed/texted' on the lead sheet only once a text has gone out."""

    def setUp(self):
        super().setUp()
        self.ghl.add_contact("loc_pdx")
        self.marked = []

    def sync(self, *quotes):
        ghl_sync.sync_quotes(list(quotes), on_sent=self.marked.append)

    def test_marked_once_when_sent(self):
        _, q = self.quote()
        self.sync(q)
        self.sync(q)
        self.sync()
        self.assertEqual([m["quote_id"] for m in self.marked], [q["quote_id"]])

    def test_not_marked_while_scheduled_then_marked_when_sent(self):
        _, q = self.quote()
        self.hours_open = False
        self.sync(q)
        self.assertEqual(self.marked, [])
        self.hours_open = True
        self.sync()
        self.assertEqual(len(self.marked), 1)

    def test_not_marked_without_consent_or_in_fields_mode(self):
        self.ghl.contact("loc_pdx")["tags"] = []
        self.sync(self.quote()[1])
        self.ghl.contact("loc_pdx")["tags"] = ["auto text"]
        with mock.patch.dict(os.environ, {"GHL_SYNC": "fields"}):
            self.sync(self.quote(pricing=dict(PRICING, biweekly=Decimal(170)))[1])
        self.assertEqual(self.marked, [])

    def test_marking_failure_does_not_affect_the_send(self):
        _, q = self.quote()
        ghl_sync.sync_quotes([q], on_sent=mock.Mock(side_effect=RuntimeError("sheets down")))
        self.assertEqual(self.status(q)[0], "sent")
        self.sync()  # not retried, not resent
        self.assertEqual(len(self.ghl.sms), 1)

    def test_updates_newest_emailed_row_for_that_email(self):
        emails = ["email", "ann@example.com", "bob@example.com", "ANN@example.com ", "cy@example.com"]
        statuses = ["status", "emailed", "emailed", "emailed", "emailed"]
        sheet = mock.Mock()
        sheet.col_values.side_effect = lambda col: {14: emails, 5: statuses}[col]
        with mock.patch("gspread.authorize") as auth,                 mock.patch("google.oauth2.service_account.Credentials.from_service_account_file"):
            auth.return_value.open_by_key.return_value.worksheet.return_value = sheet
            self.assertTrue(ats.mark_lead_texted({"market": "pdx", "email": "Ann@Example.com"}))
            auth.return_value.open_by_key.return_value.worksheet.assert_called_with("PDX")
            sheet.update_cell.assert_called_once_with(4, 5, "emailed/texted")

            statuses[3] = "emailed/texted"; statuses[1] = "called"
            sheet.update_cell.reset_mock()
            self.assertFalse(ats.mark_lead_texted({"market": "PDX", "email": "ann@example.com"}))
            sheet.update_cell.assert_not_called()


class TrackingCodes(unittest.TestCase):
    OLD_FORM = """Jones, Joel wants monthly cleaning!
Phone: 3609038004
email: test@test.com
Address: 97034
SQFT: 2000
Bed 2
Bath 3
UTM CODES ( COPY INTO A1 SHEET):
CAMPAIGN : 119396
SOURCE : google
"""
    # As read from the real Phoenix test lead (plain-text part).
    NEW_FORM = """Test, Test wants biWeekly cleaning!
Phone: 3609038004
email: drinkh20bois@gmail.com
Address: 85205
SQFT: 2300
Bed 2
Bath 2
CLIENT NOTES:

UTM CAMPAIGN: gmb

UTM SOURCE: google

UTM MEDIUM: organic

UTM CONTENT:

UTM TERM:

GCLID: Cj0KCQjwjL3HBhCgARIsAPUg7a7t
"""

    def parse(self, body, market):
        import autoemailing as ae
        with mock.patch.object(ae, "get_zone", return_value=("1", "Somewhere")):
            return ae.parse_email_details(ae.get_cleaned_body(body), market)

    def test_old_form_still_reads_campaign_and_source(self):
        parsed = self.parse(self.OLD_FORM, "PDX")
        self.assertEqual(parsed[8:10], ("119396", "google"))

    def test_new_utm_form_reads_campaign_and_source(self):
        parsed = self.parse(self.NEW_FORM, "PHX")
        self.assertEqual(parsed[8:10], ("gmb", "google"))

    def test_empty_utm_lines_do_not_bleed_into_the_next_line(self):
        body = self.NEW_FORM.replace("UTM CAMPAIGN: gmb", "UTM CAMPAIGN:")
        parsed = self.parse(body, "PHX")
        self.assertIsNone(parsed[8])


class EmailPathIsolated(Base):
    def lead(self, service="biweekly", market="PDX"):
        return ("Lee, Ann", service, EMAIL, "1500", "3", "2", ("1", "Portland"),
                "503-555-1234", "camp", "src", market)

    def run_revise(self, leads):
        fake_quotes = lambda market, qs: [{"output": PRICING} for _ in qs]
        with mock.patch.object(ats, "batch_get_quotes", fake_quotes):
            return ats.revise_list(leads, "DFW", 0, {}, {})

    def test_every_lead_still_gets_its_email(self):
        _, drafts, _ = self.run_revise([self.lead(), self.lead("deep"), self.lead(market="DFW")])
        self.assertEqual(len(drafts), 3)
        self.assertTrue(all(len(d) == 5 and d[1] for d in drafts))
        # revise_list groups by market, so drafts are not in input order.
        problems = [p for d in drafts for p in d[4]["problems"]]
        self.assertEqual(problems, ["unknown service type 'deep'"])

    def test_text_failure_does_not_drop_the_email(self):
        with mock.patch.object(ghl_sync, "build_quote", side_effect=RuntimeError("boom")):
            _, drafts, _ = self.run_revise([self.lead()])
        self.assertEqual(len(drafts), 1)
        self.assertTrue(drafts[0][1])
        self.assertIsNone(drafts[0][4])


if __name__ == "__main__":
    unittest.main()

"""
Offline tests for surviving Google's Sheets quota and alerting when runs fail.
No Gmail, Sheets or GHL traffic; nothing is emailed or texted.

    venv\\Scripts\\python.exe -m unittest discover tests -v
"""
import os
import sys
import tempfile
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gspread  # noqa: E402
from gspread.exceptions import APIError  # noqa: E402

import health_alert  # noqa: E402
import quoting  # noqa: E402

ALERT_ENV = {"ALERT_PHONE": "503-555-0142", "ALERT_MARKET": "PDX",
             "ALERT_AFTER_FAILURES": "5", "ALERT_REMIND_HOURS": "6",
             "GHL_PDX_LOCATION_ID": "loc_pdx", "GHL_PDX_TOKEN": "tok"}


class Alerts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sent = []
        self.now = datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc)  # Sun 6:00 PM Pacific
        self.patches = [
            mock.patch.object(health_alert, "STATE_PATH", os.path.join(self.tmp, "health.json")),
            mock.patch.dict(os.environ, ALERT_ENV),
            mock.patch.object(health_alert, "_now", lambda: self.now),
            mock.patch.object(health_alert.ghl_sync.GHLClient, "find_contact",
                              lambda c, email, phone: "joel" if phone == "+15035550142" else None),
            mock.patch.object(health_alert.ghl_sync.GHLClient, "send_sms",
                              lambda c, cid, msg: self.sent.append((c.market, cid, msg))),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fail(self, n=1, error=None):
        for _ in range(n):
            health_alert.record_failure(error or RuntimeError("APIError: [429]: Quota exceeded"))
            self.now += timedelta(minutes=1)

    def test_one_alert_after_five_failures_in_a_row(self):
        self.fail(4)
        self.assertEqual(self.sent, [])
        self.fail(1)
        self.assertEqual(len(self.sent), 1)
        market, contact, msg = self.sent[0]
        self.assertEqual((market, contact), ("PDX", "joel"))
        self.assertIn("Quote engine DOWN since Sun 6:00 PM", msg)
        self.assertIn("5 runs failed in a row", msg)
        self.assertIn("Quota exceeded", msg)
        self.fail(30)
        self.assertEqual(len(self.sent), 1)  # no text every minute

    def test_reminder_while_still_down(self):
        self.fail(5)
        self.now += timedelta(hours=6)
        self.fail(1)
        self.assertEqual(len(self.sent), 2)

    def test_recovery_text_then_reset(self):
        self.fail(5)
        health_alert.record_success()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("running again", self.sent[1][2])
        self.fail(4)  # a fresh count: not yet 5
        self.assertEqual(len(self.sent), 2)

    def test_short_blip_sends_nothing(self):
        self.fail(3)
        health_alert.record_success()
        health_alert.record_success()
        self.assertEqual(self.sent, [])
        self.fail(4)
        self.assertEqual(self.sent, [])

    def test_alert_problems_never_raise(self):
        with mock.patch.object(health_alert.ghl_sync.GHLClient, "send_sms",
                               side_effect=RuntimeError("GHL down")):
            self.fail(6)  # must not raise
        self.assertEqual(self.sent, [])
        self.fail(1)  # tries again on the next failure since none got through
        self.assertEqual(len(self.sent), 1)

    def test_no_phone_configured_means_no_alert(self):
        with mock.patch.dict(os.environ, {"ALERT_PHONE": ""}):
            self.fail(10)
        self.assertEqual(self.sent, [])

    def test_unknown_contact_is_not_created(self):
        with mock.patch.dict(os.environ, {"ALERT_PHONE": "503-555-0000"}):
            self.fail(5)
        self.assertEqual(self.sent, [])


class RunHook(unittest.TestCase):
    """autoemailing's __main__ block reports each run to health_alert."""

    def run_main(self, preload=None, run=None):
        import runpy
        calls = []
        import autoemailing
        with mock.patch.object(autoemailing, "preload_all", preload or (lambda: None)), \
                mock.patch("health_alert.record_failure", lambda e: calls.append(("fail", e))), \
                mock.patch("health_alert.record_success", lambda: calls.append(("ok",))):
            with mock.patch.object(autoemailing, "run_automation", run or (lambda: None)):
                path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "autoemailing.py")
                src = open(path, encoding="utf-8").read()
                main = src[src.index('if __name__ == "__main__":'):]
                g = dict(vars(autoemailing))
                g["__name__"] = "__main__"
                try:
                    exec(compile(main, path, "exec"), g)
                except Exception as e:
                    calls.append(("raised", e))
        return calls

    def test_success_is_recorded(self):
        self.assertEqual(self.run_main(), [("ok",)])

    def test_crash_is_recorded_and_still_raised(self):
        boom = RuntimeError("429")
        calls = self.run_main(run=mock.Mock(side_effect=boom))
        self.assertEqual(calls, [("fail", boom), ("raised", boom)])


class LeadCap(unittest.TestCase):
    """A backlog is worked through MAX_LEADS_PER_RUN at a time; the rest stay queued."""

    def test_backlog_is_split_across_runs(self):
        import autoemailing as ae
        msgs = [{"id": f"m{i}", "body": f"lead {i}"} for i in range(30)]
        seen = {}

        def parse(body, market):
            i = int(body.split()[1])
            return (f"Lee, Ann{i}", "weekly", f"a{i}@example.com", "1500", "3", "2",
                    ("1", "Portland"), "5035551234", "", "")

        def relabel(service, ids, label):
            seen.setdefault(label, []).extend(ids)

        with mock.patch.object(ae, "authenticate_gmail", return_value=object()), \
                mock.patch.object(ae, "build"), \
                mock.patch.object(ae, "get_label_ids_by_name",
                                  return_value={"Automations": "L1", "DFW": "L2", "PHX": "L3"}), \
                mock.patch.object(ae, "fetch_emails", return_value=(msgs, [], [])), \
                mock.patch.object(ae, "get_cleaned_body", side_effect=lambda b: b), \
                mock.patch.object(ae, "parse_email_details", side_effect=parse), \
                mock.patch.object(ae, "add_to_spreadsheet", return_value=[]) as sheet, \
                mock.patch.object(ae, "relabel_messages", side_effect=relabel), \
                mock.patch.object(ae.ghl_sync, "sync_quotes"), \
                mock.patch.object(ae, "MAX_LEADS_PER_RUN", 20):
            ae.run_automation()

        self.assertEqual(len(sheet.call_args[0][0]), 20)
        self.assertEqual(seen["AutomatedEmailSent"], [f"m{i}" for i in range(20)])
        # m20..m29 were not relabelled, so they keep Automations for the next run

    def test_failures_to_start_are_raised_for_the_alert(self):
        import autoemailing as ae
        with mock.patch.object(ae, "authenticate_gmail", return_value=None):
            with self.assertRaises(RuntimeError):
                ae.run_automation()


class SheetsQuota(unittest.TestCase):
    def test_estimator_client_waits_and_retries_on_429(self):
        with mock.patch("gspread.authorize") as auth, \
                mock.patch("oauth2client.service_account.ServiceAccountCredentials.from_json_keyfile_name"):
            sheet = auth.return_value.open_by_key.return_value.worksheet.return_value
            sheet.batch_get.return_value = [[["1"]]] * 6
            quoting._batch_get_quotes("pdx", [{"sqft": 1500, "beds": 3, "baths": 2}])
        self.assertIs(auth.call_args.kwargs["http_client"], gspread.http_client.BackOffHTTPClient)

    def test_failed_estimator_write_stops_instead_of_reading_old_prices(self):
        resp = mock.Mock(status_code=429)
        resp.json.return_value = {"error": {"code": 429, "message": "Quota exceeded", "status": "x"}}
        sheet = mock.Mock()
        sheet.update.side_effect = APIError(resp)
        with mock.patch.object(quoting.time, "sleep"):
            with self.assertRaises(APIError):
                quoting.safe_update(sheet, "E3:E5", [[1], [2], [3]])
        self.assertEqual(sheet.update.call_count, 5)


if __name__ == "__main__":
    unittest.main()

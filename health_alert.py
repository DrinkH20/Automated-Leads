"""
Text an alert when the quote engine keeps failing, and again when it recovers.

autoemailing.py calls record_failure() when a run crashes and record_success()
when one completes. After ALERT_AFTER_FAILURES crashed runs in a row (one run a
minute, so ~5 minutes down) one text goes to ALERT_PHONE; while it stays down,
a reminder every ALERT_REMIND_HOURS. When a run succeeds again, one "running
again" text. Nothing here may raise: an alert problem is only logged.

The text goes out through the ALERT_MARKET GHL sub-account (default PDX) to the
existing contact with that phone number; no contact is ever created. This is an
internal message, so no 'auto text' tag is needed.

.env:  ALERT_PHONE=+1...   (required; no alerts without it)
       ALERT_MARKET=PDX  ALERT_AFTER_FAILURES=5  ALERT_REMIND_HOURS=6
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import ghl_sync

BASE_DIR = os.getenv("APP_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE_DIR, "health_state.json")
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _settings():
    return {
        "phone": ghl_sync.normalize_phone(os.getenv("ALERT_PHONE", "")),
        "market": os.getenv("ALERT_MARKET", "PDX").strip().upper(),
        "after": int(os.getenv("ALERT_AFTER_FAILURES", "5")),
        "remind": timedelta(hours=float(os.getenv("ALERT_REMIND_HOURS", "6"))),
    }


def _now():
    return datetime.now(timezone.utc)


def _load():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


def _local(iso):
    return datetime.fromisoformat(iso).astimezone(LOCAL_TZ).strftime("%a %I:%M %p").replace(" 0", " ")


def _send(message):
    """Text the alert phone. Returns True if GHL accepted it."""
    cfg = _settings()
    if not cfg["phone"]:
        logging.error("ALERT not sent (ALERT_PHONE not set): %s", message)
        return False
    try:
        client = ghl_sync.GHLClient(cfg["market"])
        contact_id = client.find_contact(None, cfg["phone"])
        if not contact_id:
            logging.error("ALERT not sent: no %s GHL contact with phone %s: %s",
                          cfg["market"], cfg["phone"], message)
            return False
        client.send_sms(contact_id, message)
        logging.warning("ALERT sent: %s", message)
        return True
    except Exception as e:
        logging.error("ALERT not sent (%s): %s", e, message)
        return False


def record_failure(error):
    try:
        cfg = _settings()
        state = _load()
        now = _now()
        state["failures"] = state.get("failures", 0) + 1
        state.setdefault("down_since", now.isoformat())
        state["last_error"] = f"{type(error).__name__}: {error}"[:120]

        alerted = state.get("alerted_at")
        due = state["failures"] >= cfg["after"] and (
            not alerted or now - datetime.fromisoformat(alerted) >= cfg["remind"])
        if due:
            message = (f"Quote engine DOWN since {_local(state['down_since'])}: "
                       f"{state['failures']} runs failed in a row. "
                       f"Last error: {state['last_error'][:80]}. Check automation.log.")
            if _send(message):
                state["alerted_at"] = now.isoformat()
        _save(state)
    except Exception as e:
        logging.error("health_alert.record_failure failed: %s", e)


def record_success():
    try:
        state = _load()
        if not state:
            return
        if state.get("alerted_at"):
            _send(f"Quote engine is running again (was down since "
                  f"{_local(state['down_since'])}, {state['failures']} failed runs).")
        _save({})
    except Exception as e:
        logging.error("health_alert.record_success failed: %s", e)

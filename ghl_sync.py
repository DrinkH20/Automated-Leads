"""
Hand each finished quote to the lead's regional GoHighLevel sub-account.

Python builds the complete text message (from the scripts sheet's texting
column, with the same prices as the email), saves it with the quote on the
lead's existing GHL contact, and sends it through that sub-account's
Conversations API, so it goes out from the branch's number and replies land in
the branch's conversations. No GHL workflow is involved.

Consent is the CONSENT_TAG ("auto text") on the contact. GHL adds it when the
lead ticked the marketing/SMS checkbox; no tag means no auto text, and the
lead is handled as normal. Python only ever reads that tag -- it never adds or
removes it, and never writes dnd/dndSettings.

Per quote:
  1. Anything that should block the text (no phone, missing/zero required
     price, unknown service, missing or unfillable texting wording) stops it
     here: 'held', logged for review. The email is unaffected.
  2. Find the lead's existing contact in the market's sub-account, by email
     then phone. Contacts are never created here. If the contact, or its
     consent tag, isn't there yet (GHL may still be processing the same form
     submission), the quote is 'waiting' and is retried on later runs for
     CONSENT_WAIT_MINUTES before it is held.
  3. Write the quote fields and finished message onto that contact (and the
     lead's phone, only if the contact has none). Read it back; every field
     must match.
  4. Re-read consent and DND/STOP from the contact as it is now, immediately
     before sending. Outside the market's texting hours (local time) the quote
     is 'scheduled' instead and sent on the first run after they reopen --
     with consent and DND checked again then. A quote not sendable within
     SCHEDULE_MAX_HOURS is held rather than texted late.
  5. Mark the attempt (ledger 'sending', contact quote_id), send the text,
     then tag the contact QUOTE_TEXTED_TAG and record 'sent'.

Never texting twice wins over never missing a text: if a run dies, or the
send times out, after step 5 began, the quote is NOT resent. It stays
'sending' / is held as "send outcome unknown" for someone to check the
contact's conversation. A send GHL clearly rejected is rolled back and retried.

GHL_SYNC in .env controls how far this goes:
  off     (default) nothing is sent to GHL
  fields  save quote + message on the contact, never send
          (safe for checking contacts in GHL before any text can go out)
  live    save, then send the text

Per market:  GHL_<MKT>_LOCATION_ID, GHL_<MKT>_TOKEN   (MKT = PDX, DFW, PHX)
Optional:    GHL_<MKT>_FROM_NUMBER (+1...) to pick the sending number;
             otherwise the sub-account's default number is used.
             Texting hours, in the market's own time zone:
             GHL_TEXT_HOURS / GHL_<MKT>_TEXT_HOURS, default 08:00-19:30: the
               weekend window, and the latest any text goes out.
             GHL_WEEKDAY_TEXT_START / GHL_<MKT>_WEEKDAY_TEXT_START, default
               18:00: Mon-Fri, new quotes text from then until 19:30.
             Quotes from after 19:30 (or before 08:00) go out at 08:00 the
             next morning, any day -- cron must run then (send_queued_texts.py).
Token scopes: contacts read/write, custom fields read, conversations/message.write
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import requests

API_BASE = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"
MESSAGES_API_VERSION = "2021-04-15"
TIMEOUT = 20

QUOTE_TEXTED_TAG = "quote-texted"
CONSENT_TAG = os.getenv("GHL_CONSENT_TAG", "auto text").strip().lower()
MAX_ATTEMPTS = 5
CONSENT_WAIT_MINUTES = int(os.getenv("GHL_CONSENT_WAIT_MINUTES", "30"))
SCHEDULE_MAX_HOURS = int(os.getenv("GHL_SCHEDULE_MAX_HOURS", "24"))

MARKET_TZ = {
    "PDX": "America/Los_Angeles",
    "DFW": "America/Chicago",
    "PHX": "America/Phoenix",  # no daylight saving
}
DEFAULT_TEXT_HOURS = "08:00-19:30"   # every day; also when overnight quotes go out
DEFAULT_WEEKDAY_START = "18:00"      # Mon-Fri, new quotes text from here until the end above

BASE_DIR = os.getenv("APP_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
LEDGER_PATH = os.path.join(BASE_DIR, "ghl_ledger.sqlite3")

# Contact custom fields, by key, that must exist in EVERY sub-account. IDs
# differ per sub-account, so they are looked up by key at runtime.
QUOTE_FIELDS = (
    "quote_id",
    "quote_market",
    "quote_service_type",
    "quote_initial",        # first clean, as emailed
    "quote_initial_full",   # "regular" first-clean price shown in the email
    "quote_recurring",      # blank for one-time and move-out
    "quote_sms_text",       # the finished message the workflow sends
    "quote_created_at",
)
# quote_id is written last, separately; everything else must read back exactly.
VERIFIED_FIELDS = tuple(k for k in QUOTE_FIELDS if k != "quote_id")


def mode():
    value = os.getenv("GHL_SYNC", "off").strip().lower()
    return value if value in ("off", "fields", "live") else "off"


# ---------------------------------------------------------------------------
# Texting hours
# ---------------------------------------------------------------------------

def _text_hours(market):
    spec = (os.getenv(f"GHL_{market}_TEXT_HOURS") or os.getenv("GHL_TEXT_HOURS")
            or DEFAULT_TEXT_HOURS)
    start, end = (time.fromisoformat(part.strip()) for part in spec.split("-"))
    return start, end


def _weekday_start(market):
    spec = (os.getenv(f"GHL_{market}_WEEKDAY_TEXT_START") or os.getenv("GHL_WEEKDAY_TEXT_START")
            or DEFAULT_WEEKDAY_START)
    return time.fromisoformat(spec.strip())


def _local_now(market, now=None):
    tz = ZoneInfo(os.getenv(f"GHL_{market}_TZ") or MARKET_TZ[market])
    return (now or datetime.now(timezone.utc)).astimezone(tz)


def _at(local, t):
    return local.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def send_after(market, since):
    """
    The earliest local time a quote first seen at `since` may be texted.

    Weekends: straight away between 08:00 and 19:30. Weekdays: straight away
    between 18:00 and 19:30 (staff handle daytime leads). Anything after 19:30,
    or before 08:00, waits for 08:00 the next morning, weekday or not.
    """
    start, end = _text_hours(market)
    local = _local_now(market, since)
    weekend = local.weekday() >= 5
    if local.time() < start:
        return _at(local, start)                            # overnight -> this morning
    if local.time() >= end:
        return _at(local + timedelta(days=1), start)        # evening -> next morning
    if not weekend and local.time() < _weekday_start(market):
        return _at(local, _weekday_start(market))           # weekday daytime -> this evening
    return local


def next_opening(market, now=None, since=None):
    """When a quote first seen at `since` (default: now) may next be texted, local time."""
    start, end = _text_hours(market)
    local = _local_now(market, now)
    opening = max(send_after(market, since or now), local)
    if opening.time() >= end:
        return _at(opening + timedelta(days=1), start)
    if opening.time() < start:
        return _at(opening, start)
    return opening


def texting_open(market, now=None, since=None):
    """True if a quote first seen at `since` (default: now) may be texted now."""
    return next_opening(market, now, since) <= _local_now(market, now)


# ---------------------------------------------------------------------------
# Building the handoff
# ---------------------------------------------------------------------------

def normalize_phone(raw):
    """Return E.164 (+1XXXXXXXXXX) for a US number, or None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", re.split(r"x", str(raw), flags=re.IGNORECASE)[0])
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def _positive(value):
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def build_quote(market, first_name, last_name, email, phone, fill, meta,
                sms_text, problems, source=""):
    """
    Assemble the handoff for one lead.

    `fill` is the exact dict the email template was filled from, so the text
    fields carry the emailed numbers. `meta` says which prices the selected
    service actually uses. `problems` holds reasons found while building the
    text (unknown service, missing wording, ...); any problem holds the text.
    """
    problems = list(problems)
    recurring_service = meta["type_clean"] not in ("ot", "move")

    # Only the prices this service quotes must be positive. An unused cell
    # being 0 (e.g. weekly on a move-out) is not a reason to block.
    if not _positive(meta["elite"]):
        problems.append(f"first-clean price is {meta['elite']!r}")
    if recurring_service and not _positive(meta["ongoing"]):
        problems.append(f"{meta['type_clean']} price is {meta['ongoing']!r}")

    phone_e164 = normalize_phone(phone)
    if not phone_e164:
        problems.append(f"no valid phone number ({phone!r})")

    fields = {
        "quote_market": market.upper(),
        "quote_service_type": meta["send_type"],
        "quote_initial": str(fill["initial"]),
        "quote_initial_full": str(fill["initial_full"]),
        "quote_recurring": str(fill["recurring"]) if recurring_service else "",
        "quote_sms_text": sms_text or "",
        "quote_created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # Same lead + same quote + same message = same quote_id, so a retry is
    # recognised. Any change (new price, edited wording) is a new quote.
    fingerprint = json.dumps([
        market.upper(), (email or "").lower(), phone_e164,
        {k: v for k, v in fields.items() if k != "quote_created_at"},
    ], sort_keys=True)
    quote_id = hashlib.sha256(fingerprint.encode()).hexdigest()[:20]

    return {
        "quote_id": quote_id,
        "market": market.upper(),
        "first_name": first_name or "",
        "last_name": last_name or "",
        "email": email or "",
        "phone": phone_e164,
        "source": source or "Quote Engine",
        "fields": fields,
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# Ledger: idempotency, retries, and the review list for held quotes
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _ledger():
    conn = sqlite3.connect(LEDGER_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ghl_quotes (
            quote_id   TEXT PRIMARY KEY,
            market     TEXT NOT NULL,
            email      TEXT,
            payload    TEXT NOT NULL,
            status     TEXT NOT NULL,   -- pending | waiting | scheduled | failed | held | staged | sending | sent
            detail     TEXT,
            attempts   INTEGER NOT NULL DEFAULT 0,
            contact_id TEXT,
            first_seen TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    return conn


def _record(conn, quote, status, detail="", contact_id=None, failed=False):
    now = _now().isoformat()
    bump = 1 if failed else 0
    conn.execute("""
        INSERT INTO ghl_quotes (quote_id, market, email, payload, status, detail,
                                attempts, contact_id, first_seen, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(quote_id) DO UPDATE SET
            status = excluded.status,
            detail = excluded.detail,
            attempts = ghl_quotes.attempts + ?,
            contact_id = COALESCE(excluded.contact_id, ghl_quotes.contact_id),
            updated_at = excluded.updated_at
    """, (quote["quote_id"], quote["market"], quote["email"], json.dumps(quote),
          status, detail, bump, contact_id, now, now, bump))
    conn.commit()


def _first_seen(conn, quote):
    row = conn.execute("SELECT first_seen FROM ghl_quotes WHERE quote_id=?",
                       (quote["quote_id"],)).fetchone()
    return datetime.fromisoformat(row[0]) if row else _now()


# Final states: a retry of the same quote_id does nothing. 'sending' is final
# on purpose -- a run that died mid-send must not text again.
FINAL = ("held", "staged", "sending", "sent")


class SendOutcomeUnknown(Exception):
    """The send request got no answer; the text may or may not have gone out."""


# ---------------------------------------------------------------------------
# GHL API
# ---------------------------------------------------------------------------

class GHLClient:
    def __init__(self, market):
        self.market = market.upper()
        self.location_id = os.getenv(f"GHL_{self.market}_LOCATION_ID")
        self.from_number = os.getenv(f"GHL_{self.market}_FROM_NUMBER") or None
        token = os.getenv(f"GHL_{self.market}_TOKEN")
        if not self.location_id or not token:
            raise RuntimeError(f"GHL_{self.market}_LOCATION_ID / GHL_{self.market}_TOKEN not set")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Version": API_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self._field_ids = None

    def _call(self, method, path, headers=None, **kwargs):
        resp = self.session.request(method, API_BASE + path, timeout=TIMEOUT,
                                    headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"GHL {method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def field_ids(self):
        if self._field_ids is None:
            data = self._call("GET", f"/locations/{self.location_id}/customFields",
                              params={"model": "contact"})
            ids = {(f.get("fieldKey") or "").replace("contact.", ""): f["id"]
                   for f in data.get("customFields", [])}
            missing = [k for k in QUOTE_FIELDS if k not in ids]
            if missing:
                raise RuntimeError(f"{self.market} sub-account is missing custom fields: {missing}")
            self._field_ids = ids
        return self._field_ids

    def _search(self, field, value):
        body = {"locationId": self.location_id, "pageLimit": 10,
                "filters": [{"field": field, "operator": "eq", "value": value}]}
        return self._call("POST", "/contacts/search", json=body).get("contacts", [])

    def find_contact(self, email, phone):
        """
        The lead's existing contact: by email, else by phone. If there are
        several, prefer one carrying the consent tag, then the most recently
        updated. Returns a contact id or None.
        """
        for field, value in (("email", (email or "").lower()), ("phone", phone)):
            if not value:
                continue
            found = self._search(field, value)
            if found:
                found.sort(key=lambda c: (CONSENT_TAG in _tags(c), c.get("dateUpdated") or ""),
                           reverse=True)
                return found[0]["id"]
        return None

    def get_contact(self, contact_id):
        return self._call("GET", f"/contacts/{contact_id}")["contact"]

    def update_contact(self, contact_id, body):
        self._call("PUT", f"/contacts/{contact_id}", json=body)

    def set_field(self, contact_id, key, value):
        self.update_contact(contact_id, {"customFields": [{"id": self.field_ids()[key], "field_value": value}]})

    def add_tags(self, contact_id, tags):
        self._call("POST", f"/contacts/{contact_id}/tags", json={"tags": tags})

    def send_sms(self, contact_id, message):
        """
        Send one SMS from this sub-account. Returns the GHL message id.
        Raises RuntimeError if GHL rejected it (nothing was sent), or
        SendOutcomeUnknown if no answer came back (it may have been sent).
        """
        body = {"type": "SMS", "contactId": contact_id, "message": message}
        if self.from_number:
            body["fromNumber"] = self.from_number
        try:
            res = self._call("POST", "/conversations/messages", json=body,
                             headers={"Version": MESSAGES_API_VERSION})
        except requests.RequestException as e:
            raise SendOutcomeUnknown(str(e)) from e
        return res.get("messageId") or ""


def _tags(contact):
    return [str(t).strip().lower() for t in contact.get("tags", []) or []]


def _saved_values(client, contact):
    by_id = {f.get("id"): f.get("value") for f in contact.get("customFields", [])}
    return {key: by_id.get(fid) for key, fid in client.field_ids().items()}


def _same(saved, sent):
    norm = lambda v: str(v if v is not None else "").replace("\r\n", "\n").strip()
    return norm(saved) == norm(sent)


def _sms_blocked(contact):
    if contact.get("dnd"):
        return True
    sms = (contact.get("dndSettings") or {}).get("SMS") or {}
    return sms.get("status") == "active"


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------

def _wait_or_hold(conn, quote, reason, contact_id=None):
    """Not there yet: retry on later runs, until the wait runs out."""
    waited = _now() - _first_seen(conn, quote)
    if waited < timedelta(minutes=CONSENT_WAIT_MINUTES):
        _record(conn, quote, "waiting", reason, contact_id)
        return "waiting"
    _record(conn, quote, "held", reason, contact_id)
    logging.info("Text not sent to %s (%s): %s", quote["email"], quote["market"], reason)
    return "held"


def _hand_off(conn, quote, run_mode):
    if quote["problems"]:
        reason = "; ".join(quote["problems"])
        _record(conn, quote, "held", reason)
        logging.warning("TEXT HELD FOR REVIEW: %s (%s): %s",
                        quote["email"], quote["market"], reason)
        return "held"

    client = GHLClient(quote["market"])
    contact_id = client.find_contact(quote["email"], quote["phone"])
    if not contact_id:
        return _wait_or_hold(conn, quote, "no matching contact in GHL")

    contact = client.get_contact(contact_id)
    saved = _saved_values(client, contact)

    # This exact quote was already being sent to this contact (the local
    # ledger was lost or reset). Never send it again.
    if saved.get("quote_id") == quote["quote_id"]:
        if QUOTE_TEXTED_TAG in _tags(contact):
            _record(conn, quote, "sent", "recovered", contact_id)
            return "recovered"
        _record(conn, quote, "held", "send outcome unknown; check the contact's conversation", contact_id)
        return "held"

    ids = client.field_ids()
    body = {"customFields": [{"id": ids[k], "field_value": quote["fields"][k]} for k in VERIFIED_FIELDS]}
    if not contact.get("phone"):
        body["phone"] = quote["phone"]  # fill a missing number; never replace one
    client.update_contact(contact_id, body)

    contact = client.get_contact(contact_id)  # current state: fields, consent, DND
    saved = _saved_values(client, contact)
    mismatched = [k for k in VERIFIED_FIELDS if not _same(saved.get(k), quote["fields"][k])]
    if mismatched:
        raise RuntimeError(f"fields did not save correctly: {mismatched}")

    consented = CONSENT_TAG in _tags(contact)
    blocked = _sms_blocked(contact)
    since = _first_seen(conn, quote)

    if run_mode == "fields":
        would = ("would hold: SMS DND/STOP" if blocked else
                 f"would hold: no '{CONSENT_TAG}' tag" if not consented else
                 "would send" if texting_open(quote["market"], since=since) else
                 f"would send after {next_opening(quote['market'], since=since):%a %H:%M %Z}")
        _record(conn, quote, "staged", f"saved; GHL_SYNC=fields; {would}", contact_id)
        return "staged"

    if blocked:
        _record(conn, quote, "held", "contact has SMS DND/STOP active", contact_id)
        logging.info("Text not sent to %s (%s): DND/STOP", quote["email"], quote["market"])
        return "held"
    if not consented:
        return _wait_or_hold(conn, quote, f"no '{CONSENT_TAG}' tag on the contact", contact_id)

    # However it got delayed (overnight, an outage, a stopped server), a quote
    # this old is not texted.
    if _now() - since > timedelta(hours=SCHEDULE_MAX_HOURS):
        _record(conn, quote, "held", f"not sent within {SCHEDULE_MAX_HOURS}h; too late to text", contact_id)
        return "held"

    if not texting_open(quote["market"], since=since):
        opening = next_opening(quote["market"], since=since)
        _record(conn, quote, "scheduled", f"outside texting hours; sends after {opening:%a %H:%M %Z}", contact_id)
        return "scheduled"

    # Mark the attempt in both places before sending, so neither a lost
    # ledger nor a crash can lead to a second text.
    _record(conn, quote, "sending", "", contact_id)
    client.set_field(contact_id, "quote_id", quote["quote_id"])
    try:
        message_id = client.send_sms(contact_id, quote["fields"]["quote_sms_text"])
    except SendOutcomeUnknown as e:
        _record(conn, quote, "held", f"send outcome unknown ({e}); check the contact's conversation", contact_id)
        logging.error("TEXT MAY OR MAY NOT HAVE SENT to %s (%s): %s", quote["email"], quote["market"], e)
        return "held"
    except Exception:
        # GHL answered with an error: nothing went out. Undo the marker so the
        # retry is not mistaken for an earlier send.
        try:
            client.set_field(contact_id, "quote_id", "")
        except Exception as e:
            logging.error("Could not clear quote_id on %s after a failed send: %s", contact_id, e)
        raise

    _record(conn, quote, "sent", f"message {message_id}", contact_id)
    try:
        client.add_tags(contact_id, [QUOTE_TEXTED_TAG])
    except Exception as e:
        logging.error("Text sent to %s but tagging failed: %s", quote["email"], e)
    return "sent"


def sync_quotes(quotes, on_sent=None):
    """
    Hand new quotes, plus earlier waiting/failed ones, to GHL.

    Never raises: nothing here may affect the email run. Failures are retried
    up to MAX_ATTEMPTS; quotes waiting on the contact or its consent tag are
    retried for CONSENT_WAIT_MINUTES.

    on_sent(quote) is called once for each text sent in this run (e.g. to mark
    the lead sheet); its errors are logged and ignored.
    """
    run_mode = mode()
    if run_mode == "off":
        return
    try:
        conn = _ledger()
    except Exception as e:
        logging.error("GHL ledger unavailable, skipping GHL handoff: %s", e)
        return
    try:
        queue = {q["quote_id"]: q for q in quotes if q}
        for payload, status, first_seen in conn.execute(
                "SELECT payload, status, first_seen FROM ghl_quotes "
                "WHERE status IN ('pending','waiting','scheduled','failed') AND attempts < ?",
                (MAX_ATTEMPTS,)).fetchall():
            q = json.loads(payload)
            # Scheduled quotes sit untouched until they are due, instead of
            # re-checking GHL every minute all night.
            if status == "scheduled" and not texting_open(
                    q["market"], since=datetime.fromisoformat(first_seen)):
                queue.pop(q["quote_id"], None)
                continue
            queue.setdefault(q["quote_id"], q)

        for quote in queue.values():
            row = conn.execute("SELECT status FROM ghl_quotes WHERE quote_id=?",
                               (quote["quote_id"],)).fetchone()
            if row and row[0] in FINAL:
                continue
            try:
                if not row:
                    _record(conn, quote, "pending")
                status = _hand_off(conn, quote, run_mode)
                logging.info("GHL %s quote %s for %s: %s",
                             quote["market"], quote["quote_id"], quote["email"], status)
                if status == "sent" and on_sent:
                    try:
                        on_sent(quote)
                    except Exception as e:
                        logging.error("Text sent to %s, but after-send step failed: %s",
                                      quote["email"], e)
            except Exception as e:
                _record(conn, quote, "failed", str(e)[:500], failed=True)
                logging.error("GHL handoff failed for %s (%s): %s",
                              quote["email"], quote["market"], e)
    finally:
        conn.close()

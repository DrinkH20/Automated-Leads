"""
Personal "Book your cleaning" links in quote emails (PHX only for now).

For each lead in a BOOKING_MARKETS market, before its quote email goes out:
  1. Find the lead's Jobber client by email (Jobber's GraphQL API, read-only).
     Jobber creates the client automatically when the lead comes in, but not
     instantly, so for up to BOOKING_WAIT_MINUTES after the lead email arrived
     the lead is held back ("wait") and retried on the next runs.
  2. Ask the booking site for that client's personal link (POST
     /api/card/invite with the client ID and email; links last 7 days).
  3. The scripts sheet's {booking_link} placeholder becomes a "Click Here to Book"
     link to it.

If there's still no link after the wait (no Jobber client, Jobber or the
booking site down, not configured), the email goes out without the link:
{booking_link} is then blank. A lead never loses its quote email over this.
Every other market's {booking_link} is always blank.

.env:  BOOKING_INVITE_SECRET   (the booking site's CARD_INVITE_SECRET)
       JOBBER_CLIENT_ID, JOBBER_CLIENT_SECRET, JOBBER_REFRESH_TOKEN
              (from the Jobber Developer Center app; see jobber_auth.py)
Optional: BOOKING_MARKETS=PHX  BOOKING_WAIT_MINUTES=10
          BOOKING_INVITE_URL  JOBBER_API_VERSION
"""

import base64
import html
import logging
import os
import time

import requests

INVITE_URL = os.getenv("BOOKING_INVITE_URL", "https://cleanaffinitybooking.com/api/card/invite")
TOKEN_URL = "https://api.getjobber.com/api/oauth/token"
GRAPHQL_URL = "https://api.getjobber.com/api/graphql"
TIMEOUT = 20

# What {booking_link} becomes in the text of the email; create_draft swaps it
# for a "Click Here to Book" link (HTML) or the bare link (plain-text part).
MARKER = "@@BOOKING_BUTTON@@"
LINK_TEXT = "Click Here to Book"
LINK_COLOR = "#0077d9"

_links = {}       # email -> booking URL, for leads in this run that got one
_decided = {}     # email -> "ready" | "none", so duplicates in a run agree
_token = {"value": None, "expires": 0}


def markets():
    return {m.strip().upper() for m in os.getenv("BOOKING_MARKETS", "PHX").split(",") if m.strip()}


def wait_minutes():
    return float(os.getenv("BOOKING_WAIT_MINUTES", "10"))


def reset():
    """Forget this run's links (each cron run is a fresh process; tests aren't)."""
    _links.clear()
    _decided.clear()


def _key(email):
    return (email or "").strip().lower()


# ---------------------------------------------------------------------------
# Jobber and the booking site
# ---------------------------------------------------------------------------

def _access_token():
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    resp = requests.post(TOKEN_URL, timeout=TIMEOUT, data={
        "client_id": os.environ["JOBBER_CLIENT_ID"],
        "client_secret": os.environ["JOBBER_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["JOBBER_REFRESH_TOKEN"],
    })
    if resp.status_code >= 400:
        raise RuntimeError(f"Jobber token refresh -> {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("refresh_token") and data["refresh_token"] != os.environ["JOBBER_REFRESH_TOKEN"]:
        logging.error("Jobber returned a NEW refresh token: turn off refresh token rotation "
                      "in the Jobber app, or this connection will stop working")
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + 50 * 60  # Jobber access tokens last 60 minutes
    return _token["value"]


def find_client_id(email):
    """The numeric Jobber client ID with this email (newest if several), or None."""
    resp = requests.post(GRAPHQL_URL, timeout=TIMEOUT, headers={
        "Authorization": f"Bearer {_access_token()}",
        "X-JOBBER-GRAPHQL-VERSION": os.getenv("JOBBER_API_VERSION", "2025-04-16"),
    }, json={
        "query": "query($t: String!) { clients(searchTerm: $t, first: 10) "
                 "{ nodes { id createdAt emails { address } } } }",
        "variables": {"t": email},
    })
    if resp.status_code >= 400:
        raise RuntimeError(f"Jobber client search -> {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"Jobber client search: {str(body['errors'])[:200]}")
    nodes = ((body.get("data") or {}).get("clients") or {}).get("nodes") or []
    # The search is fuzzy: keep only clients that really have this address.
    matches = [n for n in nodes if any(_key(e.get("address")) == _key(email)
                                       for e in n.get("emails") or [])]
    if not matches:
        return None
    newest = max(matches, key=lambda n: n.get("createdAt") or "")
    # Jobber IDs are base64 of "gid://Jobber/Client/<number>"
    return base64.b64decode(newest["id"]).decode().rsplit("/", 1)[-1]


def invite_url(client_id, email):
    resp = requests.post(INVITE_URL, timeout=TIMEOUT, headers={
        "Authorization": f"Bearer {os.environ['BOOKING_INVITE_SECRET']}",
        "Content-Type": "application/json",
    }, json={"clientId": str(client_id), "email": email})
    if resp.status_code >= 400:
        raise RuntimeError(f"booking invite -> {resp.status_code}: {resp.text[:200]}")
    url = (resp.json() or {}).get("bookingUrl") or ""
    if not url.startswith("https://"):
        raise RuntimeError(f"booking invite returned no usable link: {url[:80]!r}")
    return url


# ---------------------------------------------------------------------------
# Used by the email run
# ---------------------------------------------------------------------------

def prepare(email, market, received=None, now=None):
    """
    Get the booking link for one lead before its email is written. Returns
      "ready" -- got a link; {booking_link} becomes the button
      "wait"  -- not yet: leave the lead queued and try again next run
      "none"  -- send the email without a button
    Never raises.
    """
    if market.upper() not in markets():
        return "none"
    key = _key(email)
    if not key:
        return "none"
    if key in _decided:
        return _decided[key]

    now = time.time() if now is None else now
    age_minutes = (now - received) / 60 if received else float("inf")
    can_wait = age_minutes < wait_minutes()

    missing = [k for k in ("BOOKING_INVITE_SECRET", "JOBBER_CLIENT_ID",
                           "JOBBER_CLIENT_SECRET", "JOBBER_REFRESH_TOKEN") if not os.getenv(k)]
    if missing:
        logging.error("No booking link for %s: %s not set in .env", email, ", ".join(missing))
        _decided[key] = "none"
        return "none"

    try:
        client_id = find_client_id(email)
        if client_id is None:
            reason = "no Jobber client with this email yet"
        else:
            _links[key] = invite_url(client_id, email)
            _decided[key] = "ready"
            logging.info("Booking link ready for %s (Jobber client %s)", email, client_id)
            return "ready"
    except Exception as e:
        reason = str(e)

    if can_wait:
        logging.info("Holding %s's quote email for a booking link (%s); will retry", email, reason)
        return "wait"
    logging.warning("Quote email to %s goes out WITHOUT a booking link: %s", email, reason)
    _decided[key] = "none"
    return "none"


def placeholder(email):
    """What {booking_link} is filled with for this lead: the marker, or blank."""
    return MARKER if _key(email) in _links else ""


def link_for(email):
    return _links.get(_key(email))


def link_html(url):
    """The booking link as ordinary left-aligned link text in the email."""
    url = html.escape(url, quote=True)
    return (f'<a href="{url}" target="_blank" style="color:{LINK_COLOR};'
            f'font-weight:bold;text-decoration:underline;">{LINK_TEXT}</a>')


def render_html(message_html, email):
    """Swap the marker in the email's HTML for the link (or drop its line)."""
    if MARKER not in message_html:
        return message_html
    url = link_for(email)
    if not url:
        message_html = message_html.replace(f"<p>{MARKER}</p>", "")
        return message_html.replace(MARKER, "")
    return message_html.replace(MARKER, link_html(url))


def render_text(message_text, email):
    """Swap the marker in the plain-text part for the bare link (or drop it)."""
    if MARKER not in message_text:
        return message_text
    url = link_for(email)
    return message_text.replace(MARKER, f"{LINK_TEXT}: {url}" if url else "")

"""
Send quote texts that were queued for later (after 19:30, overnight, or
weekday daytime), without touching Gmail or sending any email.

autoemailing.py already does this on every run; this exists so the 08:00
morning batch goes out even while the email cron is not running. Safe to run
alongside it: anything already sent, or being sent, is never sent again.

    cron:  */5 8-19 * * *  flock -n /tmp/quote_engine.lock <venv>/bin/python send_queued_texts.py
"""
from dotenv import load_dotenv

load_dotenv()

import logging  # noqa: E402

import ghl_sync  # noqa: E402
from add_to_spreadsheet import mark_lead_texted  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ghl_sync.sync_quotes([], on_sent=mark_lead_texted)

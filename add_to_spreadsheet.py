import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from datetime import date
import base64
from email.mime.text import MIMEText
import logging
import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
# Install google-api-python-client
from googleapiclient.discovery import build
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
import html
import re
from server_price_connect import update_servers
import unicodedata
from quoting import batch_get_quotes

# ot, initial, move, monthly, biweekly, weekly = 0,0,0,0,0,0


SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.compose']

BASE_DIR = os.getenv("APP_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials", "google_secrets.json")
TOKEN_FILE = 'token.pickle'


logging.basicConfig(level=logging.DEBUG)

def safe_state_place(sp):
    """Return (zone, city) from state_place, safely."""
    zone, city = "", ""
    if isinstance(sp, (list, tuple)):
        if len(sp) >= 1 and sp[0]:
            zone = sp[0]
        if len(sp) >= 2 and sp[1]:
            city = sp[1]
    return zone, city

def parse_lead_line(text):
    """
    Extract name and service_type from text like:
      'Z., Edna wants monthly cleaning!'  -> ('Z., Edna', 'monthly')
      'Curtin, Sara wants oneTime cleaning!' -> ('Curtin, Sara', 'oneTime')
    Works across lines; ignores case.
    """
    if not text:
        return None, None

    s = unicodedata.normalize("NFKC", str(text)).replace("\xa0", " ")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    m = re.search(
        r"""(?P<name>.+?)\s+wants\s+(?P<stype>[A-Za-z\-\s]+?)\s+cleaning\b!?""",
        s,
        flags=re.IGNORECASE
    )
    if not m:
        return None, None
    name = m.group("name").strip()
    stype = m.group("stype").strip()
    return name, stype

def normalize_service_type(raw):
    s = (raw or "").strip().upper()
    s = re.sub(r"[\s\-]", "", s)
    aliases = {
        "ONETIME":"ONETIME", "ONCE":"ONETIME", "ONEOFF":"ONETIME",
        "MOVE":"MOVE","MOVEIN":"MOVE","MOVEOUT":"MOVE",
        "WEEKLY":"WEEKLY",
        "BIWEEKLY":"BIWEEKLY","EOW":"BIWEEKLY","EVERYOTHERWEEK":"BIWEEKLY","EVERY2WEEKS":"BIWEEKLY",
        "MONTHLY":"MONTHLY","EVERY4WEEKS":"MONTHLY","4WEEK":"MONTHLY",
    }
    return aliases.get(s)

def split_name(name):
    if not name:
        return "", ""
    s = unicodedata.normalize("NFKC", str(name)).replace("\xa0", " ")
    s = s.replace("，", ",").replace("‚", ",").replace("ˏ", ",")
    s = re.sub(r"\s+", " ", s).strip()
    if "," in s:
        last, first = s.split(",", 1)
        return last.strip(), first.strip()
    parts = s.split(" ")
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[1:]).strip(), parts[0].strip()

def normalize_service_type(raw):
    s = (raw or "").strip().upper()
    # remove spaces and dashes for easier matching
    s_compact = re.sub(r'[\s\-]', '', s)

    # canonical options
    valid = {"ONETIME", "MOVE", "WEEKLY", "BIWEEKLY", "MONTHLY"}

    # direct match
    if s in valid:
        return s
    if s_compact in valid:
        return s_compact

    # common aliases
    aliases = {
        "ONCE": "ONETIME",
        "ONEOFF": "ONETIME",
        "ONECLEAN": "ONETIME",
        "MOVEIN": "MOVE",
        "MOVEOUT": "MOVE",
        "EOW": "BIWEEKLY",
        "EVERYOTHERWEEK": "BIWEEKLY",
        "EVERY2WEEKS": "BIWEEKLY",
        "4WEEK": "MONTHLY",
        "EVERY4WEEKS": "MONTHLY",
    }
    if s_compact in aliases:
        return aliases[s_compact]

    # heuristic: if token contains a canonical word, pick it
    for key in ["ONETIME", "MOVE", "WEEKLY", "BIWEEKLY", "MONTHLY"]:
        if key in s_compact:
            return key

    return None  # unknown

def revise_list(data, mark, dfw_count, pdx_pricing, dfw_pricing):

    revised_data, draft_list = [], []
    markets_for_rows = []  # ✅ add this
    today_date = datetime.now().strftime('%#m/%#d')
    scripts_choose = ["ONETIME", "MOVE", "WEEKLY", "BIWEEKLY", "MONTHLY"]

    count = 0
    quotes_to_run_pdx = []
    quotes_to_run_dfw = []
    quotes_to_run_phx = []
    for item in data:
        # Unpack what you *know*; guard lengths
        market = item[9] if len(item) > 9 else "PDX"
        name         = item[0] if len(item) > 0 else None
        service_type = item[1] if len(item) > 1 else None
        email        = item[2] if len(item) > 2 else None
        sqft         = item[3] if len(item) > 3 else None
        bed          = item[4] if len(item) > 4 else None
        bath         = item[5] if len(item) > 5 else None
        state_place  = item[6] if len(item) > 6 else None
        phone        = item[7] if len(item) > 7 else None
        utm_value    = item[8] if len(item) > 8 and item[8] is not None else ""

        # --- NEW: if name or service_type missing, scan all string fields in *this* item only
        if not name or not service_type:
            for field in item:
                if isinstance(field, str) and ("wants" in field or "WANTS" in field):
                    n2, s2 = parse_lead_line(field)
                    if n2 and not name:
                        name = n2
                    if s2 and not service_type:
                        service_type = s2
                    if name and service_type:
                        break

        # Derive zone/city safely
        zone = state_place[0] if isinstance(state_place, (list, tuple)) and len(state_place) > 0 and state_place[0] else ""
        city = state_place[1] if isinstance(state_place, (list, tuple)) and len(state_place) > 1 and state_place[1] else ""

        # Normalize strings
        name = name or ""
        email = email or ""
        phone = phone or ""
        service_type = service_type or ""

        # Name & service parsing
        last_name, first_name = split_name(name)
        stype_norm = normalize_service_type(service_type)
        if not stype_norm:
            # If we STILL can't normalize, default to ONETIME (or log & skip)
            stype_norm = "ONETIME"
        try:
            stype_idx = scripts_choose.index(stype_norm)
        except ValueError:
            stype_idx = 0

        markets_for_rows.append(market)  # ✅ add this
        # Add to sheet data
        revised_data.append((
            today_date, utm_value, "Auto", "", "emailed",
            "", "", "", "", "",
            name, service_type, zone, email, phone, "",
            utm_value, city
        ))

        # Compose draft using market split
        # if (len(data) - count) > dfw_count:
        #     quotes_to_run_dfw.append(((sqft, bed, bath), stype_idx, first_name, last_name,
        #                               "Joel", city, "PDX"))
        #     count += 1
        #     # sub, body_text = autocalc(sqft, bed, bath, stype_idx, first_name, last_name,
        #     #                           "Joel", city, "PDX", factor_dfw, pdx_pricing)
        # else:
        #     quotes_to_run_pdx.append(((sqft, bed, bath), stype_idx, first_name, last_name,
        #                          "Joel", city, "DFW"))
        quote_tuple = (
            (sqft, bed, bath),
            stype_idx,
            first_name,
            last_name,
            "Joel",
            city,
            market,
            email  # ← carry email with quote
        )

        if market == "PDX":
            quotes_to_run_pdx.append(quote_tuple)
        elif market == "DFW":
            quotes_to_run_dfw.append(quote_tuple)
        elif market == "PHX":
            quotes_to_run_phx.append(quote_tuple)

            count += 1

    quotes_to_run = [
        batch
        for batch in (quotes_to_run_dfw, quotes_to_run_pdx, quotes_to_run_phx)
        if batch and len(batch) > 0
    ]

    all_results_quotes = []
    # print("quotes_to_run", quotes_to_run)
    for market_batch in quotes_to_run:

        # Market is consistent inside each sublist, so grab it from the first record
        # print("Market batch val", market_batch)
        market = market_batch[0][6].lower()

        formatted_quotes = []

        for quote in market_batch:
            sqft, beds, baths = quote[0]

            formatted_quotes.append({
                "sqft": int(float(sqft)),
                "beds": int(float(beds)),
                "baths": float(baths)
            })

        # Run one call per market
        results = batch_get_quotes(market, formatted_quotes)

        all_results_quotes.append({
            "market": market,
            "input": formatted_quotes,
            "results": results
        })

    final_outputs = []

    # count = 0
    for market_index, market_batch in enumerate(quotes_to_run):

        market_results = all_results_quotes[market_index]

        market = market_results["market"].upper()  # "DFW" or "PDX"

        quotes = market_batch
        results = market_results["results"]

        # Safety check — this prevents silent misalignment
        if len(quotes) != len(results):
            raise ValueError(f"Mismatch in {market}: {len(quotes)} quotes vs {len(results)} results")

        # Walk quote-by-quote
        for quote, result in zip(quotes, results):
            # Unpack original quote
            (sqft, bed, bath) = quote[0]
            stype_idx = quote[1]
            first_name = quote[2]
            last_name = quote[3]
            username = quote[4]
            city = quote[5]
            market = quote[6]
            email = quote[7]  # ← now safe

            # email = revised_data[count]
            # email = email[13]
            # count += 1

            # Pricing output for this quote
            pricing = result["output"]  # list of Decimals

            # Call autocalc ONE quote at a time
            sub, body_text = autocalc(
                int(float(sqft)),
                int(float(bed)),
                float(bath),
                stype_idx,
                first_name,
                last_name,
                username,
                city,
                market,
                pricing  # ← if your autocalc needs the pricing array
            )
            # draft_list.append((sub, body_text, email))
            draft_list.append((sub, body_text, email, market))

            final_outputs.append({
                "name": f"{first_name} {last_name}",
                "city": city,
                "market": market,
                "sub": sub,
                "body": body_text,
                "pricing": pricing
            })

    #
    # for quot in quotes_to_run:
    #     sqft, beds, baths = quot[0]
    #
    #     sub, body_text = autocalc(sqft, bed, bath, quot[1], quot[2], quot[3],
    #                               quot[4], quot[5], quot[7], )


        # sub, body_text = autocalc(sqft, bed, bath, stype_idx, first_name, last_name,
        #                           "Joel", city, "DFW", factor_dfw, dfw_pricing)

    # draft_list.append((sub, body_text, email))
    # count += 1

    # Send drafts
    # total = len(draft_list)
    # for i, (sub, body_text, email) in enumerate(draft_list):
    #     label_market = "DFW" if i >= total - dfw_count else "PDX"
    #     create_draft_route(sub, body_text, email, label_market)
    #
    # return revised_data
    # Don't send drafts here. Just return them.
    return revised_data, draft_list, markets_for_rows


def create_label_if_not_exists(service, user_id, label_name, markt=None):
    """Creates a new label if it doesn't exist."""
    try:
        # List existing labels
        label_list = service.users().labels().list(userId=user_id).execute()
        labels = label_list.get('labels', [])

        # Check if the label already exists
        for label in labels:
            if label['name'] == label_name:
                return label['id']

        # If the label does not exist, create it
        label_body = {
            'name': label_name,
            'labelListVisibility': 'labelShow',
            'messageListVisibility': 'show'
        }
        label = service.users().labels().create(userId=user_id, body=label_body).execute()
        return label['id']
    except Exception as e:
        logging.error(f"An error occurred while creating or fetching the label: {e}")
        return None


def apply_label_to_message(service, user_id, message_id, label_id):
    """Applies the specified label to the message."""
    try:
        message_labels = {
            'addLabelIds': [label_id],
            'removeLabelIds': []
        }
        service.users().messages().modify(userId=user_id, id=message_id, body=message_labels).execute()
        logging.debug(f"Label applied to message ID: {message_id}")
    except Exception as e:
        logging.error(f"An error occurred while applying the label to the message: {e}")


def convert_text_to_html(message_text):
    # Escape special HTML characters to prevent misinterpretation
    escaped_message_text = html.escape(message_text)

    # Replace multiple spaces with non-breaking spaces to preserve formatting
    escaped_message_text = re.sub(r' {2,}', lambda match: '&nbsp;' * len(match.group(0)), escaped_message_text)

    # Handle bullet points (•) and preserve space after them
    escaped_message_text = escaped_message_text.replace("• ", "•&nbsp;")

    # Convert line breaks to <br> and wrap paragraphs in <p> tags for HTML formatting
    message_lines = escaped_message_text.splitlines()  # Split message into lines based on line breaks
    html_message = "<p>" + "</p><p>".join(message_lines) + "</p>"  # Wrap each line in <p> tags
    return html_message


def create_draft(service, sender_name, sender, subject, message_text, receiver, area, label_name='Leads In Process'):
    try:
        message = MIMEMultipart('alternative')
        formatted_sender = formataddr((sender_name, sender))

        if area.upper() == "PDX":
            footer_html = """
            <table width="206" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;color:rgb(20,49,65);font-family:proxima-nova,sans-serif;font-size:16px"><tbody><tr><td style="margin:auto;padding:0px 0px 1px"><a href="https://cleanaffinity.com/" style="background-color:transparent;color:rgb(35,82,124);outline:0px;display:inline-block" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://cleanaffinity.com/&amp;source=gmail&amp;ust=1753387360204000&amp;usg=AOvVaw1_qGxFX9vNvZj88nCJmRhf"><img width="200" src="https://ci3.googleusercontent.com/meips/ADKq_NaHCjqRyVIbvhTlEb3vGPvT6jjSyDbNyBJE7ZhgTdaYGWQ2Ux1vTrGvxNSFWCoI_7YLbi2lyvNToByk2wku5X4Ty3j2kGBnqDThP-lz5meLf3ComXVwEg=s0-d-e1-ft#https://s1g.s3.amazonaws.com/325e6b8720f2f9a00d074326edf01a9f.png" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></a></td></tr><tr><td height="4" style="padding:0px;border-top:3px solid rgb(0,0,0)"></td></tr><tr><td style="padding:0px;vertical-align:middle;color:rgb(0,0,0);font-size:12px;font-family:helvetica,arial"><span style="font-weight:700"><span style="font-size:15px">Office Team</span></span><br><br><table cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent;margin:0px 1px 1px 0px"><tbody><tr><td style="padding:0px 1px 0px 0px"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_Nbu8BcqvPO0NsMt0thKm1fy5BM-bke3tekFIPLPj8-lOIllqWmOXD_sNYvqyTuFPb8NZLkVMMT1KtHKvYpfxBq-1Rs_P3kVVbF3j3_umEaigthjxIeBBg=s0-d-e1-ft#https://s1g.s3.amazonaws.com/3e17acc3e1f17ca0eb066f92112030d4.png" alt="email" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></td><td style="padding:0px"><span style="font-size-adjust:none;font-stretch:normal;line-height:normal"><a href="mailto:hello@cleanaffinity.com" style="background-color:transparent;color:rgb(0,0,0)" target="_blank">hello@cleanaffinity.com</a></span></td></tr></tbody></table><table cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent;margin:0px 1px 1px 0px"><tbody><tr><td style="padding:0px 1px 0px 0px"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_NbOvxEt5lgrvY7In4555tR498ZHVnamfeiNDuz0ihljVAOsV1JEkU7A8huN48KtfFD-RaiqMdvdbpefi2ElxhXdGOXBcb5OIoj2c5IudggNYU8JcBIWxA=s0-d-e1-ft#https://s1g.s3.amazonaws.com/6d17a9904ea926bfe5700c3e877f70c0.png" alt="mobile" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></td><td style="padding:0px"><span style="font-size-adjust:none;font-stretch:normal;line-height:normal"><a href="tel:503-933-1917" target="_blank">503-933-1917</a></span></td></tr></tbody></table><table cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent"><tbody><tr><td style="padding:0px 5px 0px 0px"><a href="https://facebook.com/cleanaffinity/" style="background-color:transparent;color:rgb(51,122,183);display:inline-block" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://facebook.com/cleanaffinity/&amp;source=gmail&amp;ust=1753387360204000&amp;usg=AOvVaw1PokiaSIca2gSp9_r74Pu2"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_NarBJHUDBNpZSF5x9fwZRDVzxrCJQ0OjwhhH5kt5Prfkk-Ae1pCwBmyRD2fyPtAklyAZDBnTH8kUNq8b1zU9cy_YXAjjV7JVzc_0XoliAgiyxNqz8x5gw=s0-d-e1-ft#https://s1g.s3.amazonaws.com/2c5fe92c2cad30bc7beafa503141662b.png" alt="Facebook" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></a></td><td style="padding:0px 5px 0px 0px"><a href="https://instagram.com/cleanaffinity/" style="background-color:transparent;color:rgb(51,122,183);display:inline-block" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://instagram.com/cleanaffinity/&amp;source=gmail&amp;ust=1753387360204000&amp;usg=AOvVaw16I4Z5Yx74Y6W15ySxm9yJ"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_NZxAdIU3eRhJqF8PfQpL0gZAj4ovvZCNNIY4aDVSWm4yfk_nW9A5s6Dt3oi9y4mthvIgZViU5HaXEcUUK6Vx8sClYSC_nYEEwuRmnXan-ZJzjuWbkKNkw=s0-d-e1-ft#https://s1g.s3.amazonaws.com/85231364dae3871f3e2465f0e3e47239.png" alt="Instagram" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></a></td></tr></tbody></table><a href="https://cleanaffinity.com/" style="background-color:transparent;color:rgb(0,0,0)" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://cleanaffinity.com/&amp;source=gmail&amp;ust=1753387360204000&amp;usg=AOvVaw1_qGxFX9vNvZj88nCJmRhf">cleanaffinity.com/</a><br></td></tr></tbody></table>
            """
        elif area.upper() == "DFW":
            footer_html = """
            <table width="206" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;color:rgb(20,49,65);font-family:proxima-nova,sans-serif;font-size:16px"><tbody><tr><td style="margin:auto;padding:0px 0px 1px"><a href="https://cleanaffinity.com/" style="background-color:transparent;color:rgb(35,82,124);outline:0px;display:inline-block" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://cleanaffinity.com/&amp;source=gmail&amp;ust=1753390838452000&amp;usg=AOvVaw1Jdh4ThRFl97qfd7jNlOSq"><img width="200" src="https://ci3.googleusercontent.com/meips/ADKq_NaHCjqRyVIbvhTlEb3vGPvT6jjSyDbNyBJE7ZhgTdaYGWQ2Ux1vTrGvxNSFWCoI_7YLbi2lyvNToByk2wku5X4Ty3j2kGBnqDThP-lz5meLf3ComXVwEg=s0-d-e1-ft#https://s1g.s3.amazonaws.com/325e6b8720f2f9a00d074326edf01a9f.png" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></a></td></tr><tr><td height="4" style="padding:0px;border-top:3px solid rgb(0,0,0)"></td></tr><tr><td style="padding:0px;vertical-align:middle;color:rgb(0,0,0);font-size:12px;font-family:helvetica,arial"><span style="font-weight:700"><span style="font-size:15px">Office Team</span></span><br><br><table cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent;margin:0px 1px 1px 0px"><tbody><tr><td style="padding:0px 1px 0px 0px"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_Nbu8BcqvPO0NsMt0thKm1fy5BM-bke3tekFIPLPj8-lOIllqWmOXD_sNYvqyTuFPb8NZLkVMMT1KtHKvYpfxBq-1Rs_P3kVVbF3j3_umEaigthjxIeBBg=s0-d-e1-ft#https://s1g.s3.amazonaws.com/3e17acc3e1f17ca0eb066f92112030d4.png" alt="email" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></td><td style="padding:0px"><span style="font-size-adjust:none;font-stretch:normal;line-height:normal"><a href="mailto:hellodfw@cleanaffinity.com" style="background-color:transparent;color:rgb(0,0,0)" target="_blank">hellodfw@cleanaffinity.com</a></span></td></tr></tbody></table><table cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent;margin:0px 1px 1px 0px"><tbody><tr><td style="padding:0px 1px 0px 0px"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_NbOvxEt5lgrvY7In4555tR498ZHVnamfeiNDuz0ihljVAOsV1JEkU7A8huN48KtfFD-RaiqMdvdbpefi2ElxhXdGOXBcb5OIoj2c5IudggNYU8JcBIWxA=s0-d-e1-ft#https://s1g.s3.amazonaws.com/6d17a9904ea926bfe5700c3e877f70c0.png" alt="mobile" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></td><td style="padding:0px"><span style="font-size-adjust:none;font-stretch:normal;line-height:normal"><a href="tel:972-318-4678" target="_blank">972-318-4678</a></span></td></tr></tbody></table><table cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent"><tbody><tr><td style="padding:0px 5px 0px 0px"><a href="https://facebook.com/cleanaffinity/" style="background-color:transparent;color:rgb(51,122,183);display:inline-block" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://facebook.com/cleanaffinity/&amp;source=gmail&amp;ust=1753390838453000&amp;usg=AOvVaw3nrk9R9LBXsHPIEY36yHhu"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_NarBJHUDBNpZSF5x9fwZRDVzxrCJQ0OjwhhH5kt5Prfkk-Ae1pCwBmyRD2fyPtAklyAZDBnTH8kUNq8b1zU9cy_YXAjjV7JVzc_0XoliAgiyxNqz8x5gw=s0-d-e1-ft#https://s1g.s3.amazonaws.com/2c5fe92c2cad30bc7beafa503141662b.png" alt="Facebook" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></a></td><td style="padding:0px 5px 0px 0px"><a href="https://instagram.com/cleanaffinity/" style="background-color:transparent;color:rgb(51,122,183);display:inline-block" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://instagram.com/cleanaffinity/&amp;source=gmail&amp;ust=1753390838453000&amp;usg=AOvVaw0S9ak4Y_nKy5X1r4alhRtS"><img width="33" height="33" src="https://ci3.googleusercontent.com/meips/ADKq_NZxAdIU3eRhJqF8PfQpL0gZAj4ovvZCNNIY4aDVSWm4yfk_nW9A5s6Dt3oi9y4mthvIgZViU5HaXEcUUK6Vx8sClYSC_nYEEwuRmnXan-ZJzjuWbkKNkw=s0-d-e1-ft#https://s1g.s3.amazonaws.com/85231364dae3871f3e2465f0e3e47239.png" alt="Instagram" style="border:none;vertical-align:baseline" class="CToWUd" data-bit="iit"></a></td></tr></tbody></table><a href="https://cleanaffinity.com/home-cleaning-services-dallas/" style="background-color:transparent;color:rgb(0,0,0)" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://cleanaffinity.com/home-cleaning-services-dallas/&amp;source=gmail&amp;ust=1753390838453000&amp;usg=AOvVaw2n1bKaSwZdhhL_nJ_5XRq2">cleanaffinity.com/</a><br></td></tr></tbody></table>
            """
        elif area.upper() == "PHX":
            footer_html = """
            <table width="206" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;color:rgb(20,49,65);font-family:proxima-nova,sans-serif;font-size:16px"><tbody><tr><td style="margin:auto;padding:0px 0px 1px"><a href="https://cleanaffinity.com/" style="background-color:transparent;color:rgb(35,82,124);outline:0px;display:inline-block" target="_blank"><img width="200" src="https://s1g.s3.amazonaws.com/325e6b8720f2f9a00d074326edf01a9f.png" style="border:none;vertical-align:baseline"></a></td></tr><tr><td height="4" style="padding:0px;border-top:3px solid rgb(0,0,0)"></td></tr><tr><td style="padding:0px;vertical-align:middle;color:rgb(0,0,0);font-size:12px;font-family:helvetica,arial"><span style="font-weight:700"><span style="font-size:15px">Office Team</span></span><br><br><table cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent;margin:0px 1px 1px 0px"><tbody><tr><td style="padding:0px 1px 0px 0px"><img width="33" height="33" src="https://s1g.s3.amazonaws.com/3e17acc3e1f17ca0eb066f92112030d4.png" alt="email" style="border:none;vertical-align:baseline"></td><td style="padding:0px"><span style="font-size-adjust:none;font-stretch:normal;line-height:normal"><a href="mailto:hellophx@cleanaffinity.com" style="background-color:transparent;color:rgb(0,0,0)" target="_blank">hellophx@cleanaffinity.com</a></span></td></tr></tbody></table><table cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent;margin:0px 1px 1px 0px"><tbody><tr><td style="padding:0px 1px 0px 0px"><img width="33" height="33" src="https://s1g.s3.amazonaws.com/6d17a9904ea926bfe5700c3e877f70c0.png" alt="mobile" style="border:none;vertical-align:baseline"></td><td style="padding:0px"><span style="font-size-adjust:none;font-stretch:normal;line-height:normal"><a href="tel:480-428-8450" target="_blank">480-428-8450</a></span></td></tr></tbody></table><table cellpadding="0" border="0" style="border-collapse:collapse;border-spacing:0px;background-color:transparent"><tbody><tr><td style="padding:0px 5px 0px 0px"><a href="https://facebook.com/cleanaffinity/" style="background-color:transparent;color:rgb(51,122,183);display:inline-block" target="_blank"><img width="33" height="33" src="https://s1g.s3.amazonaws.com/2c5fe92c2cad30bc7beafa503141662b.png" alt="Facebook" style="border:none;vertical-align:baseline"></a></td><td style="padding:0px 5px 0px 0px"><a href="https://instagram.com/cleanaffinity/" style="background-color:transparent;color:rgb(51,122,183);display:inline-block" target="_blank"><img width="33" height="33" src="https://s1g.s3.amazonaws.com/85231364dae3871f3e2465f0e3e47239.png" alt="Instagram" style="border:none;vertical-align:baseline"></a></td></tr></tbody></table><a href="https://cleanaffinity.com/home-cleaning-services-dallas/" style="background-color:transparent;color:rgb(0,0,0)" target="_blank">cleanaffinity.com/</a><br></td></tr></tbody></table>
            """

        html_message = convert_text_to_html(message_text) + footer_html
        plain_text = message_text + "\n\nBest regards,\nClean Affinity\n503-933-1917\nwww.cleanaffinity.com"

        message.attach(MIMEText(plain_text, 'plain'))
        message.attach(MIMEText(html_message, 'html'))

        message['to'] = receiver
        # if area.upper() == "PDX":
        #     message['from'] = formataddr(("Clean Affinity", "hello@cleanaffinity.com"))
        # else:
        #     message['from'] = formataddr(("Clean Affinity", "hellodfw@cleanaffinity.com"))
        message['subject'] = subject

        if area.upper() == "PDX":
            sender_email = formataddr(("Clean Affinity", "hello@cleanaffinity.com"))
        elif area.upper() == "DFW":
            sender_email = formataddr(("Clean Affinity", "hellodfw@cleanaffinity.com"))
        elif area.upper() == "PHX":
            sender_email = formataddr(("Clean Affinity", "hellophx@cleanaffinity.com"))

        message['from'] = sender_email

        message['subject'] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        # draft_body = {'message': {'raw': raw}}
        # draft = service.users().drafts().create(userId='me', body=draft_body).execute()
        # logging.debug(f"Draft created with ID: {draft['id']}")
        #
        # message_id = draft['message']['id']
        # send_body = {'raw': raw}
        # sent_message = service.users().messages().send(userId='me', body=send_body).execute()
        # logging.debug(f"Email sent with ID: {sent_message['id']}")
        draft_body = {'message': {'raw': raw}}
        draft = service.users().drafts().create(userId='me', body=draft_body).execute()
        logging.info("Draft created")
        return draft

        message_id = sent_message['id']

        # Ensure both labels exist
        label_ids = []
        in_process_id = create_label_if_not_exists(service, 'me', label_name, area)
        if in_process_id:
            label_ids.append(in_process_id)

        if area.upper() == "DFW":
            dfw_id = create_label_if_not_exists(service, 'me', "DFW", area)
            if dfw_id:
                label_ids.append(dfw_id)

        if area.upper() == "PHX":
            phx_id = create_label_if_not_exists(service, 'me', "PHX", area)
            if phx_id:
                label_ids.append(phx_id)

        # Apply labels
        if label_ids:
            apply_label_to_message(service, 'me', message_id, label_ids[0])
            for label_id in label_ids[1:]:
                apply_label_to_message(service, 'me', message_id, label_id)

        return sent_message

    except Exception as e:
        logging.error(f"An error occurred while creating a draft: {e}")
        return None


def authenticate_gmail():
    try:
        creds = None
        logging.debug("Starting authentication process.")

        # Check if token.pickle exists
        if os.path.exists(TOKEN_FILE):
            logging.debug("Found existing token file. Loading credentials.")
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)

        # If no valid credentials, perform OAuth flow
        if not creds or not creds.valid:
            logging.debug("No valid credentials found or credentials are invalid/expired.")
            if creds and creds.expired and creds.refresh_token:
                logging.debug("Credentials are expired, attempting to refresh.")
                creds.refresh(Request())
            else:
                logging.debug("Running OAuth flow to obtain new credentials.")
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)

            # Save the credentials for future use
            with open(TOKEN_FILE, 'wb') as token:
                logging.debug("Saving new credentials to token file.")
                pickle.dump(creds, token)

        logging.debug("Authentication process completed.")
        return creds
    except Exception as e:
        logging.error(f"An error occurred during authentication: {e}")
        return None


def create_draft_route(subject, message_text, gmail, market):
    creds = authenticate_gmail()
    if not creds:
        return "Failed to authenticate with Gmail."

    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)

    # Create the draft
    user_info = service.users().getProfile(userId='me').execute()
    sender_email = user_info['emailAddress']
    draft = create_draft(service, "Clean Affinity", sender_email, subject, message_text, gmail, market)


def add_to_spreadsheet(raw_data, mrkt, dfw_amount, pdx_prices, dfw_prices):
    from google.oauth2.service_account import Credentials
    import gspread
    from datetime import date

    # Path to your credentials.json file
    BASE_DIR = os.getenv("APP_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
    creds_file = os.path.join(BASE_DIR, "credentials", "google_secrets.json")

    creds = Credentials.from_service_account_file(
        creds_file,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/gmail.modify"
        ]
    )

    client = gspread.authorize(creds)

    spreadsheet_id = '1mZ0TseN9pucJEDvQXAzCtKUUgSWT8802SMEo-BfL3KU'
    sheet_name = 'Sheet1'

    # data = revise_list(raw_data, mrkt, dfw_amount, pdx_prices, dfw_prices)
    # data, draft_list = revise_list(raw_data, mrkt, dfw_amount, pdx_prices, dfw_prices)
    data, draft_list, markets_for_rows = revise_list(raw_data, mrkt, dfw_amount, pdx_prices, dfw_prices)

    try:
        # Group rows by market tab name (PDX / DFW / PHX)
        rows_by_market = {"PDX": [], "DFW": [], "PHX": []}

        for row, mkt in zip(data, markets_for_rows):
            mkt = (mkt or "PDX").upper()
            if mkt not in rows_by_market:
                mkt = "PDX"
            if len(row) == 18:
                rows_by_market[mkt].append(row)

        gsheet = client.open_by_key(spreadsheet_id)

        for mkt, rows_to_insert in rows_by_market.items():
            if not rows_to_insert:
                continue

            try:
                sheet = gsheet.worksheet(mkt)  # ✅ tab name matches market
            except Exception as e:
                print(f"ERROR: Could not find worksheet tab '{mkt}'. Create a tab named '{mkt}' in the sheet.")
                raise

            # Next available row ONCE per tab
            existing_rows = sheet.col_values(1)
            start_row = len(existing_rows) + 1
            end_row = start_row + len(rows_to_insert) - 1

            update_range = f"A{start_row}:R{end_row}"
            print(f"[{mkt}] Inserting {len(rows_to_insert)} rows at once (Rows {start_row}–{end_row})")

            sheet.update(update_range, rows_to_insert, value_input_option="RAW")

        print("✅ Data appended successfully by market.")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"Spreadsheet with ID '{spreadsheet_id}' not found.")
    except Exception as e:
        print(f"An error occurred: {e}")
    return draft_list
    #     sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
    #     print(f"Successfully accessed the spreadsheet '{sheet_name}'.")
    #
    #     # 🔥 Filter valid rows first
    #     rows_to_insert = [item for item in data if len(item) == 18]
    #
    #     if not rows_to_insert:
    #         print("No valid rows to insert.")
    #         return
    #
    #     # 🔥 Find next available row ONCE (1 read call)
    #     existing_rows = sheet.col_values(1)
    #     start_row = len(existing_rows) + 1
    #     end_row = start_row + len(rows_to_insert) - 1
    #
    #     update_range = f"A{start_row}:R{end_row}"
    #
    #     print(f"Inserting {len(rows_to_insert)} rows at once "
    #           f"(Rows {start_row}–{end_row})")
    #
    #     # 🔥 ONE WRITE CALL
    #     sheet.update(update_range, rows_to_insert, value_input_option="RAW")
    #
    #     print("Data appended successfully.")
    #
    # except gspread.exceptions.SpreadsheetNotFound:
    #     print(f"Spreadsheet with ID '{spreadsheet_id}' not found.")
    # except Exception as e:
    #     print(f"An error occurred: {e}")
    # return draft_list



today = date.today()
months_list = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
month = months_list[today.month-1]


# def update_prices(mark, ot, initial, move, monthly, biweekly, weekly):
#     factors, texas_factors = update_servers(mark)
#     set_ot, set_initial, set_move, set_monthly, set_biweekly, set_weekly = map(float, factors)
#     # print(texas_factors)
#     if (ot, initial, move, monthly, biweekly, weekly) == (set_ot, set_initial, set_move, set_monthly, set_biweekly,
#                                                           set_weekly):
#         print("No change needed")
#     else:
#         ot, initial, move, monthly, biweekly, weekly = set_ot, set_initial, set_move, set_monthly, set_biweekly, set_weekly
#         print("Prices successfully updated!")
#     return texas_factors, ot, initial, move, monthly, biweekly, weekly


def autocalc(sqft, beds, baths, type_clean_numerical, name_first, name_last, username, city, market, pricing):
    # For some reason the type clean is off by +1 on each quote so biweekly = weekly pricing etc.
    type_converter = ['', 'initial', 'ot', 'move', 'weekly', 'biweekly', 'monthly']
    type_clean = type_converter[type_clean_numerical+2]
    type_clean_price = type_converter[type_clean_numerical + 2]
    initial = pricing['initial']
    ongoing = pricing[type_clean_price]

    if type_clean not in ("ot", "move"):
        elite = initial

    else:
        elite = pricing[type_clean_price]

    title = get_title(sqft, beds, baths, type_clean_numerical, name_last, name_first)
    if market == "DFW":
        main_info = get_quote_dfw(month, round(elite), round(ongoing), type_clean_numerical, name_first, username, city)
    elif market == "PHX":
        main_info = get_quote_phx(month, round(elite), round(ongoing), type_clean_numerical, name_first, username, city)
    else:
        main_info = get_quote(month, round(elite), round(ongoing), type_clean_numerical, name_first, username, city)

    return title, main_info


# This is all the different scripts
def get_title(sqft, beds, baths, part_list, last, first):
    sqft = int(sqft)
    sqft = round(sqft/10)*10
    beds = int(beds)

    if baths == int(baths):
        baths = int(baths)

    if beds <= 1 >= baths:
        scripts = [f"{last}, {first} - One Time Clean {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"{last}, {first} - Move Clean {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"{last}, {first} - Weekly Cleans {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"{last}, {first} - Biweekly Cleans {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"{last}, {first} - Monthly Cleans {sqft} sqft, {beds} Bed, {baths} Bath"]
    elif beds > 1 < baths:
        scripts = [f"{last}, {first} - One Time Clean {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"{last}, {first} - Move Clean {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"{last}, {first} - Weekly Cleans {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"{last}, {first} - Biweekly Cleans {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"{last}, {first} - Monthly Cleans {sqft} sqft, {beds} Beds, {baths} Baths"]
    elif beds > 1 >= baths:
        scripts = [f"{last}, {first} - One Time Clean {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"{last}, {first} - Move Clean {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"{last}, {first} - Weekly Cleans {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"{last}, {first} - Biweekly Cleans {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"{last}, {first} - Monthly Cleans {sqft} sqft, {beds} Beds, {baths} Bath"]
    else:
        scripts = [f"{last}, {first} - One Time Clean {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"{last}, {first} - Move Clean {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"{last}, {first} - Weekly Cleans {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"{last}, {first} - Biweekly Cleans {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"{last}, {first} - Monthly Cleans {sqft} sqft, {beds} Bed, {baths} Baths"]

    return scripts[part_list]


def get_quote(date_month, initial, recuring, part_list, name="there", username="", city=""):
    scripts = [f"""Hi {name},

We’re excited to help make your home feel fresh and spotless!

Based on the info you provided and our {date_month} special, your one-time clean will be ${initial} (Includes washing all interior window panes within arms reach!)
•	        Would you like any extras like fridge, oven, window blind or track cleaning?
•	        Are there any other cleaning needs/notes you would like for me to add to our list?
Please let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly, but we still have a few spots open in {date_month}!

We look forward to cleaning for you!
{username}""", f"""Hi {name},

We’re excited to help make your home feel fresh and spotless!

Based on the info you provided and our {date_month} special, your moving clean will be ${initial} (Includes washing all interior window panes within arms reach!)
•	        Would you like any extras like fridge, oven, window blind or track cleaning?
•	        Are there any other cleaning needs/notes you would like for me to add to our list?
Please let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly, but we still have a few spots open in {date_month}!

We look forward to cleaning for you!
{username}""", f"""Hi {name}!

We’re excited to help make your home feel fresh and spotless!

Normally, your initial reset clean would be ${initial*2},
but with our {date_month} special, it’s 50% off — just ${initial}. Your weekly service is ${recuring}, with the whole home cleaned every visit.

Let me know if you’d like to get on the schedule and if you have any preferred days or times. Our calendar fills up quickly (especially for the longer initial clean), but we still have a few {date_month} spots available. What works best for you?

We look forward to cleaning for you!
{username}
""", f"""Hi {name}!

We’re excited to help make your home feel fresh and spotless!

Normally, your initial reset clean would be ${initial*2},
but with our {date_month} special, it’s 50% off — just ${initial}. Your biweekly service is ${recuring}, with the whole home cleaned every visit.

Let me know if you’d like to get on the schedule and if you have any preferred days or times. Our calendar fills up quickly (especially for the longer initial clean), but we still have a few {date_month} spots available. What works best for you?

We look forward to cleaning for you!
{username}
""", f"""Hi {name}!

We’re excited to help make your home feel fresh and spotless!

Normally, your initial reset clean would be ${initial*2},
but with our {date_month} special, it’s 50% off — just ${initial}. Your monthly service is ${recuring}, with the whole home cleaned every visit.

Let me know if you’d like to get on the schedule and if you have any preferred days or times. Our calendar fills up quickly (especially for the longer initial clean), but we still have a few {date_month} spots available. What works best for you?

We look forward to cleaning for you!
{username}
""", f"""Hi {name},

Thank you for reaching out about cleans! We'd love to help!

It looks like the address you provided is in Salem which is outside of our service area. Do you have an address that is closer to the Portland Metro area? Let me know and we'd love to help you with your cleaning needs!

Best,

{username}"""]
    return scripts[part_list]


def get_quote_dfw(date_month, initial, recuring, part_list, name="there", username="", city=""):
    scripts = [f"""Hi {name},
    
We’re excited to help make your home feel fresh and spotless!

Based on the info you provided and our {date_month} special, your one-time clean will be ${initial} before sales tax (Includes washing all interior window panes within arms reach!)

•         Would you like any extras like fridge, oven, window blind or track cleaning?

•         Are there any other cleaning needs/notes you would like for me to add to our list?

Every technician on our team is background-checked, highly trained, and IICRC-certified, with great communication skills — so you can count on professionalism and care with every visit.

Let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}! What works best?

We look forward to cleaning for you!
{username}""", f"""Hi {name},
    
We’re excited to help make your home feel fresh and spotless!
Based on the info you provided and our {date_month} special, your moving clean will be ${initial} before sales tax (Includes washing all interior window panes within arms reach!)

•         Would you like any extras like fridge, oven, window blind or track cleaning?

•         Are there any other cleaning needs/notes you would like for me to add to our list?

Every technician on our team is background-checked, highly trained, and IICRC-certified, with great communication skills — so you can count on professionalism and care with every visit.

Let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}! What works best?

We look forward to cleaning for you!
{username}""", f"""Hi {name},

We’d love to help get your home fresh and spotless!

With the special we are running for {date_month}, your first clean is ${recuring} before sales tax — the same rate as your weekly visits moving forward, with baseboards and interior windows included!

All of our technicians are background-checked, highly trained, and IICRC-certified.

{date_month} availability is limited — would you like me to hold an opening for you?

Best,
{username}  
""", f"""Hi {name},

We’d love to help get your home fresh and spotless!

With the special we are running for {date_month}, your first clean is ${recuring} before sales tax — the same rate as your biweekly visits moving forward, with baseboards and interior windows included!

All of our technicians are background-checked, highly trained, and IICRC-certified.

{date_month} availability is limited — would you like me to hold an opening for you?

Best,
{username} 
""", f"""Hi {name},

We’d love to help get your home fresh and spotless!

With the special we are running for {date_month}, your first clean is ${recuring} before sales tax — the same rate as your monthly visits moving forward, with baseboards and interior windows included!

All of our technicians are background-checked, highly trained, and IICRC-certified.

{date_month} availability is limited — would you like me to hold an opening for you?

Best,
{username}  
""", f"""Hi {name},

Thank you for reaching out about cleans! We'd love to help!

It looks like the address you provided is in Salem which is outside of our service area. Do you have an address that is closer to the Portland Metro area? Let me know and we'd love to help you with your cleaning needs!

Best,

{username}"""]
    return scripts[part_list]


def get_quote_phx(date_month, initial, recuring, part_list, name="there", username="", city=""):
    scripts = [f"""Hi {name},

We’re excited to help make your home feel fresh and spotless!

Based on the info you provided and our {date_month} special, your one-time clean will be ${initial} (Includes washing all interior window panes within arms reach!)

•         Would you like any extras like fridge, oven, window blind or track cleaning?

•         Are there any other cleaning needs/notes you would like for me to add to our list?

Every technician on our team is background-checked, highly trained, and IICRC-certified, with great communication skills — so you can count on professionalism and care with every visit.

Let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}! What works best?

We look forward to cleaning for you!
{username}""", f"""Hi {name},

We’re excited to help make your home feel fresh and spotless!
Based on the info you provided and our {date_month} special, your moving clean will be ${initial} (Includes washing all interior window panes within arms reach!)

•         Would you like any extras like fridge, oven, window blind or track cleaning?

•         Are there any other cleaning needs/notes you would like for me to add to our list?

Every technician on our team is background-checked, highly trained, and IICRC-certified, with great communication skills — so you can count on professionalism and care with every visit.

Let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}! What works best?

We look forward to cleaning for you!
{username}""", f"""Hi {name},

We’d love to help get your home fresh and spotless!

With the special we are running for {date_month}, your first clean is ${recuring} — the same rate as your weekly visits moving forward, with baseboards and interior windows included!

All of our technicians are background-checked, highly trained, and IICRC-certified.

{date_month} availability is limited — would you like me to hold an opening for you?

Best,
{username} 
""", f"""Hi {name},

We’d love to help get your home fresh and spotless!

With the special we are running for {date_month}, your first clean is ${recuring} — the same rate as your biweekly visits moving forward, with baseboards and interior windows included!

All of our technicians are background-checked, highly trained, and IICRC-certified.

{date_month} availability is limited — would you like me to hold an opening for you?

Best,
{username} 
""", f"""Hi {name},

We’d love to help get your home fresh and spotless!

With the special we are running for {date_month}, your first clean is ${recuring} — the same rate as your monthly visits moving forward, with baseboards and interior windows included!

All of our technicians are background-checked, highly trained, and IICRC-certified.

{date_month} availability is limited — would you like me to hold an opening for you?

Best,
{username} 
""", f"""Hi {name},

Thank you for reaching out about cleans! We'd love to help!

It looks like the address you provided is in Salem which is outside of our service area. Do you have an address that is closer to the Phoenix area? Let me know and we'd love to help you with your cleaning needs!

Best,

{username}"""]
    return scripts[part_list]


def get_title_manual(sqft, beds, baths, part_list):
    sqft = int(sqft)
    sqft = round(sqft / 10) * 10
    beds = int(beds)
    try:
        baths = int(baths)
    except ValueError:
        baths = float(baths)

    if beds <= 1 >= baths:
        scripts = [f"One Time Clean {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"Move Clean {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"Weekly Cleans {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"Biweekly Cleans {sqft} sqft, {beds} Bed, {baths} Bath",
                   f"Monthly Cleans {sqft} sqft, {beds} Bed, {baths} Bath"]
    elif beds > 1 < baths:
        scripts = [f"One Time Clean {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"Move Clean {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"Weekly Cleans {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"Biweekly Cleans {sqft} sqft, {beds} Beds, {baths} Baths",
                   f"Monthly Cleans {sqft} sqft, {beds} Beds, {baths} Baths"]
    elif beds > 1 >= baths:
        scripts = [f"One Time Clean {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"Move Clean {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"Weekly Cleans {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"Biweekly Cleans {sqft} sqft, {beds} Beds, {baths} Bath",
                   f"Monthly Cleans {sqft} sqft, {beds} Beds, {baths} Bath"]
    else:
        scripts = [f"One Time Clean {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"Move Clean {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"Weekly Cleans {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"Biweekly Cleans {sqft} sqft, {beds} Bed, {baths} Baths",
                   f"Monthly Cleans {sqft} sqft, {beds} Bed, {baths} Baths"]

    return scripts[part_list]


def get_quote_text(date_month, initial, recuring, part_list, name="there", username="", sqft=0, beds=0, baths=0):
    scripts = [f"""H {name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your one-time clean will be ${initial} with our {date_month} special. 

Is this something I can get on the schedule for you?
""", f"""Hi {name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your moving clean will be ${initial} with our {date_month} special. 

Is this something I can get on the schedule for you?
""", f"""Hi {name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your initial clean will be ${initial} and the following weekly cleans will be ${recuring} with our {date_month} special. 

Is this something I can get on the schedule for you?
""", f"""Hi {name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your initial clean will be ${initial} and the following biweekly cleans will be ${recuring} with our {date_month} special. 

Is this something I can get on the schedule for you?
""", f"""Hi {name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your initial clean will be ${initial} and the following monthly cleans will be ${recuring} with our {date_month} special. 

Is this something I can get on the schedule for you?
"""]
    return scripts[part_list]


def get_quote_text_dfw(date_month, initial, recuring, part_list, name="there", username="", sqft=0, beds=0, baths=0):
    scripts = [f"""Hi {name}! {username} with Clean Affinity here

Thanks for reaching out! For your {sqft} sqft home ({beds} beds, {baths} baths), your Elite one-time clean is ${initial} before sales tax with our {date_month} special — a full reset with interior windows and baseboards included so it feels fresh again.

Most clients book this when they want things spotless without giving up their weekend.

We also offer extras like fridge, oven, blinds, or track cleaning — would a morning or afternoon spot work better for you?
""", f"""Hi {name}! {username} with Clean Affinity here

Thanks for reaching out! For your {sqft} sqft home ({beds} beds, {baths} baths), your moving clean is ${initial} before sales tax with our {date_month} special — a full reset that includes interior windows and all reachable cabinet interiors so it feels brand new again.

Most clients book this when they want things spotless without giving up their weekend.

We also offer extras like fridge, oven, blinds, or track cleaning — would a morning or afternoon spot work better for you?
""", f"""Hi {name}, this is {username} with Clean Affinity!

For your {sqft} sq ft, {beds} bed / {baths} bath home:

Your first clean is ${recuring} before sales tax with our {date_month} special — the same rate as your weekly cleans moving forward. (Baseboards and interior windows are included)

All our technicians are background-checked, highly trained, and IICRC-certified.

We only have a few {date_month} openings left — would you like me to hold one for you?
""", f"""Hi {name}, this is {username} with Clean Affinity!

For your {sqft} sq ft, {beds} bed / {baths} bath home:

Your first clean is ${recuring} before sales tax with our {date_month} special — the same rate as your biweekly cleans moving forward. (Baseboards and interior windows are included)

All our technicians are background-checked, highly trained, and IICRC-certified.

We only have a few {date_month} openings left — would you like me to hold one for you?
""", f"""Hi {name}, this is {username} with Clean Affinity!

For your {sqft} sq ft, {beds} bed / {baths} bath home:

Your first clean is ${recuring} before sales tax with our {date_month} special — the same rate as your monthly cleans moving forward. (Baseboards and interior windows are included)

All our technicians are background-checked, highly trained, and IICRC-certified.

We only have a few {date_month} openings left — would you like me to hold one for you? 
""", f"""# Hi {name},

Thank you for reaching out about cleans! We'd love to help!

It looks like the address you provided is in Salem which is outside of our service area. Do you have an address that is closer to the Portland Metro area? Let me know and we'd love to help you with your cleaning needs!

Best,

{username}"""]
    return scripts[part_list]


def get_quote_text_phx(date_month, initial, recuring, part_list, name="there", username="", sqft=0, beds=0, baths=0):
    scripts = [f"""Hi {name}! {username} with Clean Affinity here

Thanks for reaching out! For your {sqft} sqft home ({beds} beds, {baths} baths), your Elite one-time clean is ${initial} with our {date_month} special — a full reset with interior windows and baseboards included so it feels fresh again.

Most clients book this when they want things spotless without giving up their weekend.

We also offer extras like fridge, oven, blinds, or track cleaning — would a morning or afternoon spot work better for you?
""", f"""Hi {name}! {username} with Clean Affinity here

Thanks for reaching out! For your {sqft} sqft home ({beds} beds, {baths} baths), your moving clean is ${initial} with our {date_month} special — a full reset that includes interior windows and all reachable cabinet interiors so it feels brand new again.

Most clients book this when they want things spotless without giving up their weekend.

We also offer extras like fridge, oven, blinds, or track cleaning — would a morning or afternoon spot work better for you?
""", f"""Hi {name}, this is {username} with Clean Affinity!

For your {sqft} sq ft, {beds} bed / {baths} bath home:

Your first clean is ${recuring} with our {date_month} special — the same rate as your weekly cleans moving forward. (Baseboards and interior windows are included)

All our technicians are background-checked, highly trained, and IICRC-certified.

We only have a few {date_month} openings left — would you like me to hold one for you?
""", f"""Hi {name}, this is {username} with Clean Affinity!

For your {sqft} sq ft, {beds} bed / {baths} bath home:

Your first clean is ${recuring} with our {date_month} special — the same rate as your biweekly cleans moving forward. (Baseboards and interior windows are included)

All our technicians are background-checked, highly trained, and IICRC-certified.

We only have a few {date_month} openings left — would you like me to hold one for you?
""", f"""Hi {name}, this is {username} with Clean Affinity!

For your {sqft} sq ft, {beds} bed / {baths} bath home:

Your first clean is ${recuring} with our {date_month} special — the same rate as your monthly cleans moving forward. (Baseboards and interior windows are included)

All our technicians are background-checked, highly trained, and IICRC-certified.

We only have a few {date_month} openings left — would you like me to hold one for you?
""", f"""# Hi {name},

Thank you for reaching out about cleans! We'd love to help!

It looks like the address you provided is in Salem which is outside of our service area. Do you have an address that is closer to the Phoenix Metro area? Let me know and we'd love to help you with your cleaning needs!

Best,

{username}"""]
    return scripts[part_list]


def failed(date_month, username=""):
    scripts = f"""Hi there!

We’re excited to help make your home feel fresh and spotless!

Could you provide the number of bedrooms and bathrooms along with the square footage of the house so I can put a quote together for you?

Please let me know if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}!

We look forward to cleaning for you!

{username}
"""
    return scripts

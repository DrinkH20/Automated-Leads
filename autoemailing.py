# from add_to_spreadsheet import update_prices
# from flask import Flask, render_template_string, request, redirect, url_for
from jinja2 import Template
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle
import logging
import base64
from email.mime.text import MIMEText
import re
from mapcodes import get_zone
from add_to_spreadsheet import add_to_spreadsheet, create_draft

# To Auto run - crontab -e - remove the hash infront of * * * * * cd /opt/quote_engine && /opt/quote_engine/venv/bin/python autoemailing.py >> /opt/quote_engine/automation.log 2>&1

# To updated - ssh root@134.209.50.116 - cd /opt/quote_engine_repo - pwd (should say /opt/quote_engine_repo) - git status - git log --oneline --graph --decorate --all -5 - git pull origin main - chmod +x deploy.sh - ./deploy.sh - tail -n 20 /opt/quote_engine_current/automation.log
# Manually test when done - cd /opt/quote_engine_current - pwd (should say /opt/quote_engine_current) - /opt/quote_engine_current/venv/bin/python autoemailing.py

# quote_engine_repo      ← git lives here
# quote_engine_releases  ← built versions
# quote_engine_current   ← live symlink


# app = Flask(__name__)

# Enable logging to capture any issues
SEND_EMAILS = True  # ← set to True when ready to send

logging.basicConfig(level=logging.DEBUG)

BASE_DIR = os.getenv("APP_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials", "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "credentials", "token.pickle")


# Define the Gmail API scope
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.compose', 'https://www.googleapis.com/auth/gmail.modify']

# if os.path.exists("token.pickle"):
#     os.remove("token.pickle")
#     print("token.pickle has been deleted")
# else:
#     print("token.pickle does not exist")

quotes_to_run = []

# download_all_sheets()

def clear_label_from_all_messages(service, label_id):
    """
    Remove a label from ALL messages that currently have it.
    """
    page_token = None

    while True:
        results = service.users().messages().list(
            userId='me',
            labelIds=[label_id],
            pageToken=page_token
        ).execute()

        messages = results.get('messages', [])

        for msg in messages:
            try:
                service.users().messages().modify(
                    userId='me',
                    id=msg['id'],
                    body={"removeLabelIds": [label_id]}
                ).execute()
            except Exception as e:
                logging.error(f"Failed to clear label on {msg['id']}: {e}")

        page_token = results.get('nextPageToken')
        if not page_token:
            break

def authenticate_gmail():
    try:
        creds = None

        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=8080)

            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)

        return creds

    except Exception as e:
        logging.error(f"Authentication error: {e}")
        return None


def get_label_ids_by_name(service, label_names):
    """
    Returns a dict mapping label name → label ID
    """
    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])

    label_map = {}
    for label in labels:
        if label['name'] in label_names:
            label_map[label['name']] = label['id']
    return label_map

# def fetch_emails(service, label_id='INBOX', dfw_label_id=None):
def fetch_emails(service, label_id, dfw_label_id=None, phx_label_id=None):

    pdx_emails = []
    dfw_emails = []
    phx_emails = []

    try:
        emails = []
        dfw_emails = []
        page_token = None

        while True:
            results = service.users().messages().list(
                userId='me',
                labelIds=[label_id],
                pageToken=page_token
            ).execute()

            messages = results.get('messages', [])
            page_token = results.get('nextPageToken')

            for message in messages:
                msg = service.users().messages().get(userId='me', id=message['id']).execute()
                label_ids = msg.get('labelIds', [])

                # Match using label ID, not name
                if phx_label_id and phx_label_id in label_ids:
                    logging.debug(f"Skipping DFW-labeled email: {message['id']}")
                    headers = msg['payload'].get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "(No Subject)")
                    body = get_email_body(msg['payload'])
                    phx_emails.append({
                        'subject': subject,
                        'body': body,
                        'id': message['id']
                    })

                    continue

                if dfw_label_id and dfw_label_id in label_ids:
                    logging.debug(f"Skipping DFW-labeled email: {message['id']}")
                    headers = msg['payload'].get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "(No Subject)")
                    body = get_email_body(msg['payload'])
                    dfw_emails.append({
                        'subject': subject,
                        'body': body,
                        'id': message['id']
                    })

                    continue

                headers = msg['payload']['headers']
                subject = next(header['value'] for header in headers if header['name'] == 'Subject')
                body = get_email_body(msg['payload'])
                pdx_emails.append({
                    'subject': subject,
                    'body': body,
                    'id': message['id']
                })

            if not page_token:
                break

        # return emails, dfw_emails
        return pdx_emails, dfw_emails, phx_emails

    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return [], []


def get_email_body(payload):
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                return decode_base64(part['body']['data'])
            elif part['mimeType'] == 'text/html':
                return decode_base64(part['body']['data'])  # If you prefer HTML format
    elif 'body' in payload:
        return decode_base64(payload['body'].get('data', ''))
    return ""


def decode_base64(data):
    decoded_bytes = base64.urlsafe_b64decode(data.encode('UTF-8'))
    return decoded_bytes.decode('UTF-8')


def run_automation():
    creds = authenticate_gmail()
    if not creds:
        logging.error("Failed to authenticate with Gmail.")
        return

    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
    logging.debug("Gmail service created successfully.")

    # ---- Get Label IDs ----
    # label_ids = get_label_ids_by_name(service, ['LeadsNotYetContacted', 'DFW'])
    # lead_label_id = label_ids.get('LeadsNotYetContacted')
    # dfw_label_id = label_ids.get('DFW')
    # label_ids = get_label_ids_by_name(service, ['LeadsNotYetContacted', 'DFW', 'PHX'])
    label_ids = get_label_ids_by_name(
        service,
        ['Automations', 'DFW', 'PHX', 'Automated Email Sent']
    )
    lead_label_id = label_ids.get('Automations')
    sent_label_id = label_ids.get('Automated Email Sent')
    dfw_label_id = label_ids.get('DFW')
    phx_label_id = label_ids.get('PHX')

    if not lead_label_id:
        logging.error("Automations label not found.")
        return

    # ---- Fetch Emails ----
    # emails, dfw_emails = fetch_emails(
    #     service,
    #     label_id=lead_label_id,
    #     dfw_label_id=dfw_label_id
    # )
    pdx_emails, dfw_emails, phx_emails = fetch_emails(
        service,
        label_id=lead_label_id,
        dfw_label_id=dfw_label_id,
        phx_label_id=phx_label_id
    )

    all_leads = []
    processed_message_ids = []
    seen_leads = {}  # email -> lead tuple

    chart_of_profitable = ['weekly', 'biweekly', 'monthly', 'move', 'onetime']

    def process_email_list(email_list, market):
        nonlocal all_leads, processed_message_ids, seen_leads

        for msg in email_list:
            if 'body' not in msg:
                continue

            try:
                lead = parse_email_details(
                    get_cleaned_body(msg['body']),
                    market
                )

                if not lead:
                    continue


                name, service_type, email, sqft, bed, bath, zone, phone, utm = lead
                lead = (name, service_type, email, sqft, bed, bath, zone, phone, utm, market)

                # ---- Validation ----
                # if not zone:
                #     continue
                #
                # try:
                #     in_zone = int(zone[0])
                #     beds = int(bed)
                # except (ValueError, TypeError):
                #     continue
                if market != "PHX":
                    if not zone or not isinstance(zone, (list, tuple)) or not zone[0]:
                        continue

                # if in_zone <= 0 or beds <= 0:
                #     continue

                # ---- Duplicate Handling ----
                if email in seen_leads:
                    existing = seen_leads[email]
                    if chart_of_profitable.index(service_type) < chart_of_profitable.index(existing[1]):
                        all_leads.remove(existing)
                        all_leads.append(lead)
                        seen_leads[email] = lead
                        processed_message_ids.append(msg['id'])
                        logging.debug("Replaced duplicate with more profitable lead.")
                else:
                    all_leads.append(lead)
                    seen_leads[email] = lead
                    processed_message_ids.append(msg['id'])

            except Exception as e:
                logging.error(f"Error processing lead: {e}")

    # ---- Process PDX then DFW ----
    process_email_list(pdx_emails, "PDX")
    process_email_list(dfw_emails, "DFW")
    process_email_list(phx_emails, "PHX")

    # process_email_list(emails, "PDX")
    # before_dfw_len = len(all_leads)
    #
    # process_email_list(dfw_emails, "DFW")
    # after_dfw_len = len(all_leads)

    # total_dfw_leads = after_dfw_len - before_dfw_len
    # if total_dfw_leads is None:
    #     total_dfw_leads = 0

    # ---- Pricing Structures ----
    pricing_template = {
        'ot': 0,
        'initial': 0,
        'move': 0,
        'monthly': 0,
        'biweekly': 0,
        'weekly': 0
    }

    pricing_pdx = pricing_template.copy()
    pricing_dfw = pricing_template.copy()

    # ---- Push to Spreadsheet ----
    # draft_list = add_to_spreadsheet(
    #     all_leads,
    #     "DFW",  # preserve your original function signature
    #     total_dfw_leads,
    #     pricing_pdx,
    #     pricing_dfw
    # )
    draft_list = add_to_spreadsheet(
        all_leads,
        "DFW",
        0,  # placeholder — no longer used
        pricing_pdx,
        pricing_dfw
    )

    if not draft_list:
        logging.info("No drafts to create.")
        draft_list = []

    # ---- Create Drafts ----
    # user_info = service.users().getProfile(userId='me').execute()
    # sender_email = user_info['emailAddress']
    #
    # for sub, body_text, receiver_email, lead_market in draft_list:
    #     create_draft(
    #         service=service,
    #         sender_name="Clean Affinity",
    #         sender=sender_email,
    #         subject=sub,
    #         message_text=body_text,
    #         receiver=receiver_email,
    #         area=lead_market,
    #         label_name="Leads In Process"
    #     )
    # ---- Create Drafts ----
    user_info = service.users().getProfile(userId='me').execute()
    sender_email = user_info['emailAddress']

    for sub, body_text, receiver_email, lead_market in draft_list:

        logging.info(f"Creating draft for {receiver_email}")

        draft = create_draft(
            service=service,
            sender_name="Clean Affinity",
            sender=sender_email,
            subject=sub,
            message_text=body_text,
            receiver=receiver_email,
            area=lead_market,
            label_name="Leads In Process"
        )

        if SEND_EMAILS and draft:
            draft_id = draft['id']

            logging.info(f"SENDING draft to {receiver_email}")

            sent = service.users().drafts().send(
                userId='me',
                body={'id': draft_id}
            ).execute()

            sent_message_id = sent['id']

            # label_ids = get_label_ids_by_name(
            #     service,
            #     ["Leads In Process", "AutomatedEmailSent"]
            # )
            #
            # service.users().messages().modify(
            #     userId='me',
            #     id=sent_message_id,
            #     body={
            #         "addLabelIds": list(label_ids.values())
            #     }
            # ).execute()
            labels_to_apply = ["Leads In Process", "AutomatedEmailSent"]

            # Add market label dynamically
            if lead_market == "DFW":
                labels_to_apply.append("DFW")
            elif lead_market == "PHX":
                labels_to_apply.append("PHX")
            # elif lead_market == "PDX":
            #     labels_to_apply.append("PDX")  # optional if you want it

            label_ids = get_label_ids_by_name(service, labels_to_apply)

            service.users().messages().modify(
                userId='me',
                id=sent_message_id,
                body={
                    "addLabelIds": list(label_ids.values())
                }
            ).execute()

    # ---- Remove Label After Processing ----
    if processed_message_ids:

        # Fetch both label IDs once
        label_ids = get_label_ids_by_name(
            service,
            ["Automations", "AutomatedEmailSent"]
        )

        remove_label_id = label_ids.get("Automations")
        add_label_id = label_ids.get("AutomatedEmailSent")

        # Optional: auto-create the label if it doesn't exist
        if not add_label_id:
            add_label_id = service.users().labels().create(
                userId='me',
                body={
                    "name": "AutomatedEmailSent",
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show"
                }
            ).execute()["id"]

        for msg_id in processed_message_ids:
            try:
                service.users().messages().modify(
                    userId='me',
                    id=msg_id,
                    body={
                        "removeLabelIds": [remove_label_id] if remove_label_id else [],
                        "addLabelIds": [add_label_id] if add_label_id else []
                    }
                ).execute()

                logging.debug(f"Updated labels for message {msg_id}")

            except Exception as e:
                logging.error(f"Failed to update labels for {msg_id}: {e}")

    logging.info("Automation run complete.")

    # Sweep Automations queue clean
    if lead_label_id:
        clear_label_from_all_messages(service, lead_label_id)
        logging.info("Cleared Automations label from all emails.")


def parse_email_details(text, mark):
    import re

    # Normalize HTML breaks and spacing
    cleaned = text.replace("&nbsp;", " ")
    cleaned = cleaned.replace("<br>", "\n")

    # ------------------------
    # Name + Service
    # ------------------------
    name_type_match = re.search(
        r'\s*([\w\s]+,\s*[\w\s]+)\s+wants\s+([\w\s]+)\s+cleaning',
        cleaned
    )

    if name_type_match:
        name = name_type_match.group(1).strip()
        service_type = name_type_match.group(2).strip()
    else:
        name = None
        service_type = None

    # ------------------------
    # Phone
    # ------------------------
    phone_match = re.search(r'Phone:\s*([\d\s\-x]+)', cleaned)
    phone = phone_match.group(1).strip() if phone_match else None

    # ------------------------
    # Email
    # ------------------------
    email_match = re.search(r'email:\s*([\w\.-]+@[\w\.-]+)', cleaned, re.IGNORECASE)
    email = email_match.group(1) if email_match else None

    # ------------------------
    # SQFT / Beds / Baths
    # ------------------------
    sqft_match = re.search(r'SQFT:\s*(\d+)', cleaned)
    sqft = sqft_match.group(1) if sqft_match else None

    bed_match = re.search(r'Bed:\s*(\d+)', cleaned)
    bed = bed_match.group(1) if bed_match else None

    bath_match = re.search(r'Bath:\s*([\d\.]+)', cleaned)
    bath = bath_match.group(1) if bath_match else None

    # ------------------------
    # ZIP (always extract separately)
    # ------------------------
    zip_match = re.search(r'\b(\d{5})\b', cleaned)
    zip_code = zip_match.group(1) if zip_match else None

    # ------------------------
    # Address extraction
    # ------------------------
    address = None

    address_block = re.search(r'Address:\s*(.+)', cleaned)
    if address_block:
        possible = address_block.group(1).strip()

        # Remove line breaks
        possible = possible.split("\n")[0].strip()

        if possible.lower() != "undefined":
            address = possible

    # Fallback: if no usable street address, use ZIP
    if not address and zip_code:
        address = zip_code

    # Final safety check
    if not address:
        print("WARNING: No valid address found.")
        return name, service_type, email, sqft, bed, bath, None, phone, None

    # ------------------------
    # UTM Extraction
    # ------------------------
    utm_order = [
        'UTM4contentAdID:',
        'UTMreferrerURL:',
        'UTM1source:',
        'UTM2CampaignID:',
        'UTM3AdSetID:'
    ]

    utm_value = None
    for utm in utm_order:
        match = re.search(rf'{utm}\s*([^\r\n<]+)', cleaned)
        if match:
            value = match.group(1).strip()
            if value:
                utm_value = value
                break


    # Get zone safely
    zone = get_zone(address, mark)
    if not zone or zone[0] in ("NA", "", None):
        logging.debug(f"Skipping lead outside service zone: {name}")
        print(zone)
        return

    return name, service_type, email, sqft, bed, bath, zone, phone, utm_value


def get_cleaned_body(body):
    # Split the body by lines
    lines = body.splitlines()

    # Find the line where the actual content starts (skipping unwanted headers like image links)
    start_index = 0
    for i, line in enumerate(lines):
        if "Forwarded message" in line or "Jia, Bo wants" in line:
            start_index = i + 1
            break

    # Join the lines starting from the content we want
    cleaned_body = "\n".join(lines[start_index:]).strip()
    return cleaned_body


def get_label_id(service, label_name):
    try:
        # Fetch all labels
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])

        # Search for the label with the matching name
        for label in labels:
            if label['name'].lower() == label_name.lower():
                return label['id']
        return None
    except Exception as e:
        logging.error(f"An error occurred while fetching labels: {e}")
        return None


# if __name__ == '__main__':
#     app.run(debug=True, port=5200)


from warmup import preload_all

if __name__ == "__main__":
    preload_all()
    run_automation()

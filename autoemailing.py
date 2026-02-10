# from add_to_spreadsheet import update_prices
from flask import Flask, render_template_string, request, redirect, url_for
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import pickle
import logging
import base64
from email.mime.text import MIMEText
import re
from mapcodes import get_zone
from add_to_spreadsheet import add_to_spreadsheet
from quoting import download_all_sheets

app = Flask(__name__)

# Enable logging to capture any issues
logging.basicConfig(level=logging.DEBUG)

# Path to your client_secrets.json file which is actually checkmail
CREDENTIALS_FILE = r'client_secret_1_833814108979-7l6vv2lc6kjit5c1toqpb0sbdq6mtuca.apps.googleusercontent.com (1).json'
TOKEN_FILE = 'token.pickle'

# Define the Gmail API scope
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.compose', 'https://www.googleapis.com/auth/gmail.modify']

if os.path.exists("token.pickle"):
    os.remove("token.pickle")
    print("token.pickle has been deleted")
else:
    print("token.pickle does not exist")

quotes_to_run = []

download_all_sheets()

def authenticate_gmail():
    # update_prices(market)
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

def fetch_emails(service, label_id='INBOX', dfw_label_id=None):
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
                if dfw_label_id and dfw_label_id in label_ids:
                    logging.debug(f"Skipping DFW-labeled email: {message['id']}")
                    headers = msg['payload'].get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "(No Subject)")
                    body = get_email_body(msg['payload'])
                    dfw_emails.append({'subject': subject, 'body': body})
                    continue

                headers = msg['payload']['headers']
                subject = next(header['value'] for header in headers if header['name'] == 'Subject')
                body = get_email_body(msg['payload'])
                emails.append({'subject': subject, 'body': body})

            if not page_token:
                break

        return emails, dfw_emails

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


@app.route('/')
def index():
    creds = authenticate_gmail()
    if not creds:
        return "Failed to authenticate with Gmail."

    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
    logging.debug("Gmail service created successfully.")

    label_name = 'LeadsNotYetContacted'
    label_id = get_label_id(service, label_name)
    label_names_needed = ['LeadsNotYetContacted', 'DFW']
    label_ids = get_label_ids_by_name(service, label_names_needed)

    lead_label_id = label_ids.get('LeadsNotYetContacted')
    dfw_label_id = label_ids.get('DFW')

    if not label_id:
        return f"Label '{label_name}' not found."

    all_leads = []
    lead_emails_for_doubles = []
    lead_type_for_doubles = []

    # emails, dfw_emails = fetch_emails(service, label_id=label_id)
    emails, dfw_emails = fetch_emails(service, label_id=lead_label_id, dfw_label_id=dfw_label_id)

    chart_of_profitable = ['weekly', 'biweekly', 'monthly', 'move', 'onetime']
    ot = initial = move = monthly = biweekly = weekly = 0
    market = "PDX"

    pricing_pdx = {
        'ot': ot,
        'initial': initial,
        'move': move,
        'monthly': monthly,
        'biweekly': biweekly,
        'weekly': weekly
    }
    # --- Process PDX emails first ---
    emails_markets = []
    for i in emails:
        if 'body' not in i:
            continue
        check_first = parse_email_details(get_cleaned_body(i['body']), market)
        last_lead = check_first
        try:
            state_parts = last_lead[6]
            in_zone = int(state_parts[0])
            if in_zone > 0 and int(last_lead[4]) > 0:
                if last_lead[2] in lead_emails_for_doubles:
                    idx = lead_emails_for_doubles.index(last_lead[2])
                    if chart_of_profitable.index(last_lead[1]) < chart_of_profitable.index(lead_type_for_doubles[idx]):
                        all_leads.pop(idx)
                        lead_emails_for_doubles.pop(idx)
                        lead_type_for_doubles.pop(idx)

                        all_leads.append(check_first)
                        lead_emails_for_doubles.append(last_lead[2])
                        lead_type_for_doubles.append(last_lead[1])
                        print("Removed duplicate lead and replaced with better one.")
                    else:
                        print("Did not add because of better duplicate.")
                else:
                    all_leads.append(check_first)
                    lead_emails_for_doubles.append(last_lead[2])
                    lead_type_for_doubles.append(last_lead[1])
                    # print("doubles", lead_emails_for_doubles) 1/22/2026
                    # print("types", lead_type_for_doubles)
        except (TypeError, ValueError):
            print("Skipped due to invalid zone or lead info.")

    # --- Now process DFW emails separately ---
    market = "DFW"

    pricing_dfw = {
        'ot': ot,
        'initial': initial,
        'move': move,
        'monthly': monthly,
        'biweekly': biweekly,
        'weekly': weekly
    }

    before_dfw_len = len(all_leads)
    for i in dfw_emails:
        if 'body' not in i:
            continue
        check_first = parse_email_details(get_cleaned_body(i['body']), market)
        last_lead = check_first
        try:
            state_parts = last_lead[6]
            in_zone = int(state_parts[0])
            if in_zone > 0 and int(last_lead[4]) > 0:
                if last_lead[2] in lead_emails_for_doubles:
                    idx = lead_emails_for_doubles.index(last_lead[2])
                    if chart_of_profitable.index(last_lead[1]) < chart_of_profitable.index(lead_type_for_doubles[idx]):
                        all_leads.pop(idx)
                        lead_emails_for_doubles.pop(idx)
                        lead_type_for_doubles.pop(idx)

                        all_leads.append(check_first)
                        lead_emails_for_doubles.append(last_lead[2])
                        lead_type_for_doubles.append(last_lead[1])
                        print("Removed duplicate lead and replaced with better one (DFW).")
                    else:
                        print("Did not add (DFW) due to better duplicate.")
                else:
                    all_leads.append(check_first)
                    lead_emails_for_doubles.append(last_lead[2])
                    lead_type_for_doubles.append(last_lead[1])
        except (TypeError, ValueError):
            print("Skipped (DFW) due to invalid zone or lead info.")

    # Final push to spreadsheet
    after_dfw_len = len(all_leads)
    total_dfw_leads = after_dfw_len - before_dfw_len
    add_to_spreadsheet(all_leads, market, total_dfw_leads, pricing_pdx, pricing_dfw)

    html_template = """
        <h1>Latest Emails from {{ label_id }}</h1>
        <ul>
            {% for email in emails %}
                <li>
                    <h3>{{ email.subject }}</h3>
                    <p>{{ email.body }}</p>
                </li>
            {% endfor %}
        </ul>
        """

    return render_template_string(html_template, emails=emails, label_id=label_id)


def parse_email_details(text, mark):
    # Extract name and type of service after the word "wants"

    name_type_match = re.search(
        r'\s*([\w\s]+,\s*[\w\s]+)\s+wants\s+([\w\s]+)\s+cleaning', text)

    if name_type_match:
        name = name_type_match.group(1).strip()
        service_type = name_type_match.group(2).strip()
    else:
        name = service_type = None

    # This part needs work
    phone_match = re.search(r'Phone:\s*([\d\s-]+(?: x \d+)?)', text)
    phone = phone_match.group(1).strip() if phone_match else None

    # Extract the email
    email_match = re.search(r'email:\s*([\w\.-]+@[\w\.-]+)', text)
    email = email_match.group(1) if email_match else None

    # Extract SQFT
    sqft_match = re.search(r'SQFT: &nbsp;\s*(\d+)', text)
    sqft = sqft_match.group(1) if sqft_match else None

    # Extract number of beds
    bed_match = re.search(r'Bed:\s*(\d+)', text)
    bed = bed_match.group(1) if bed_match else None

    # Extract number of baths
    bath_match = re.search(r'Bath:\s*([\d\.]+)', text)
    bath = bath_match.group(1) if bath_match else None

    # Extract the address
    address_match = re.search(r'Address:\s*(.+?)\s*(\d{5})', text)
    if address_match:
        address = f"{address_match.group(1).strip()} {address_match.group(2)}"
    else:
        address = None

    print(name, email, bed, bath, sqft, phone)
    quotes_to_run.append({"sqft": sqft, "beds": bed, "baths": bath})

    # UTM parameters in the specified order
    utm_order = [
        'UTM4contentAdID:',
        'UTMreferrerURL:',
        'UTM1source:',
        'UTM2CampaignID:',
        'UTM3AdSetID:'
    ]

    utm_value = None

    for utm in utm_order:
        # Modify the regex to stop capturing at a line break or <br> (but not include <br> itself)
        match = re.search(rf'{utm}\s*([^\r\n<]+)', text)
        if match:
            # Check if the captured value contains a <br> and strip it off if present
            utm_value = match.group(1).split('<br>')[0].strip()
            if utm_value != "":
                break

    return name, service_type, email, sqft, bed, bath, get_zone(address, mark), phone, utm_value
    # return name, service_type, email, sqft, bed, bath, get_zone(address), utm_value


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


if __name__ == '__main__':
    app.run(debug=True, port=5200)

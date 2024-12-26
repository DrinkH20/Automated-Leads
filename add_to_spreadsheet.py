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
from googleapiclient.discovery import build
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
import html
import re
from server_price_connect import update_servers


SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.compose']

CREDENTIALS_FILE = r'checkemail.json'
TOKEN_FILE = 'token.pickle'

logging.basicConfig(level=logging.DEBUG)


def revise_list(data):

    revised_data = []
    today_date = datetime.now().strftime('%#m/%#d')  # Get today's date in M/D format

    for item in data:
        # Extract each element from the tuple
        state_place = item[6]
        city = state_place[1]
        name, service_type, email, sqft, bed, bath, zone, phone = item[0:8]
        zone = state_place[0]
        print(len(item))
        if len(item) == 9:
            utm_value = item[8]

        # Prepare the revised format in columns
        revised_data.append((
            today_date,
            utm_value if utm_value else "",
            "Auto",
            "",
            "emailed",
            "", "", "",
            name if name else "",
            service_type if service_type else "",
            zone if zone else "",
            email if email else "",
            phone if phone else "",
            "",
            utm_value if utm_value else "",
            city if city else ""
        ))
        scripts_choose = ["ONETIME", "MOVE", "WEEKLY", "BIWEEKLY", "MONTHLY"]
        if ',' in name:
            last_name, first_name = name.split(',', 1)
        print(service_type.upper(), scripts_choose.index(service_type.upper()))
        sub, body_text = autocalc(sqft, bed, bath, scripts_choose.index(service_type.upper()), first_name, last_name, "Joel", city)
        create_draft_route(sub, body_text, email)
        print("create_draft")
    return revised_data


def create_label_if_not_exists(service, user_id, label_name):
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


def create_draft(service, sender_name, sender, subject, message_text, receiver, label_name='Leads In Process'):
    try:
        # Create a multipart message to support both plain text and HTML content
        message = MIMEMultipart('alternative')
        formatted_sender = formataddr((sender_name, sender))

        # Define the footer with your logo and other HTML elements
        footer_html = """
        <div dir="ltr"><img data-aii="CiExZnhMN2ttWDdra2RHdlY5Z1U4ODhUTHdlZEpVSEYwbTU" src="https://ci3.googleusercontent.com/mail-sig/AIorK4wK5N0Ul0HHETT-MTvAGX0Ry6a3go9OyEQWmOp7woQXvjOF0DXhwxdbLs-viIsdHmS9hkuL_CG6fN7M" data-os="https://lh3.googleusercontent.com/d/1fxL7kmX7kkdGvV9gU888TLwedJUHF0m5"><br><table cellpadding="0" cellspacing="0" style="color:rgb(255,255,255);font-size:medium;vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td style="vertical-align:top"><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td style="text-align:center"></td></tr><tr><td height="30"></td></tr><tr><td style="text-align:center"><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial;display:inline-block"><tbody><tr><td><a href="https://www.facebook.com/cleanaffinity/" color="#3fcdd2" style="display:inline-block;padding:0px;background-color:rgb(63,205,210)" target="_blank"><img height="24" src="https://cdn2.hubspot.net/hubfs/53/tools/email-signature-generator/icons/facebook-icon-2x.png" alt="facebook" color="#3fcdd2" style="max-width:135px;display:block"></a></td><td width="5"><div></div></td><td><a href="https://twitter.com/clean_affinity" color="#3fcdd2" style="display:inline-block;padding:0px;background-color:rgb(63,205,210)" target="_blank"><img height="24" src="https://cdn2.hubspot.net/hubfs/53/tools/email-signature-generator/icons/twitter-icon-2x.png" alt="twitter" color="#3fcdd2" style="max-width:135px;display:block"></a></td><td width="5"><div></div></td><td><a href="https://www.linkedin.com/company/cleanaffinity" color="#3fcdd2" style="display:inline-block;padding:0px;background-color:rgb(63,205,210)" target="_blank"><img height="24" src="https://cdn2.hubspot.net/hubfs/53/tools/email-signature-generator/icons/linkedin-icon-2x.png" alt="linkedin" color="#3fcdd2" style="max-width:135px;display:block"></a></td><td width="5"><div></div></td><td><a href="https://instagram.com/cleanaffinity" color="#3fcdd2" style="display:inline-block;padding:0px;background-color:rgb(63,205,210)" target="_blank"><img height="24" src="https://cdn2.hubspot.net/hubfs/53/tools/email-signature-generator/icons/instagram-icon-2x.png" alt="instagram" color="#3fcdd2" style="max-width:135px;display:block"></a></td><td width="5"><div></div></td></tr></tbody></table></td></tr></tbody></table></td><td width="46"><div></div></td><td style="padding:0px;vertical-align:middle"><h3 color="#000000" style="margin:0px;font-size:18px;color:rgb(0,0,0)">Office Team</h3><p color="#000000" style="margin:0px;color:rgb(0,0,0);font-size:14px;line-height:22px">Clean Affinity</p><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial;width:234px"><tbody><tr><td height="30"></td></tr><tr><td height="1" color="#3FCDD2" style="width:234px;border-bottom:1px solid rgb(63,205,210);border-left:none;display:block"></td></tr><tr><td height="30"></td></tr></tbody></table><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr height="25" style="vertical-align:middle"><td width="30" style="vertical-align:middle"><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td style="vertical-align:bottom"><span width="11" color="#3FCDD2" style="display:block;background-color:rgb(63,205,210)"><img width="13" src="https://cdn2.hubspot.net/hubfs/53/tools/email-signature-generator/icons/phone-icon-2x.png" color="#3FCDD2" style="display:block"></span></td></tr></tbody></table></td><td style="padding:0px;color:rgb(0,0,0)"><a href="tel:503-933-1917" color="#000000" style="color:rgb(0,0,0);font-size:12px" target="_blank">503-933-1917</a></td></tr><tr height="25" style="vertical-align:middle"><td width="30" style="vertical-align:middle"><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td style="vertical-align:bottom"><span width="11" color="#3FCDD2" style="display:block;background-color:rgb(63,205,210)"><img width="13" src="https://cdn2.hubspot.net/hubfs/53/tools/email-signature-generator/icons/email-icon-2x.png" color="#3FCDD2" style="display:block"></span></td></tr></tbody></table></td><td style="padding:0px"><a href="mailto:hello@cleanaffinity.com" color="#000000" style="color:rgb(0,0,0);font-size:12px" target="_blank">hello@cleanaffinity.com</a></td></tr><tr height="25" style="vertical-align:middle"><td width="30" style="vertical-align:middle"><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td style="vertical-align:bottom"><span width="11" color="#3FCDD2" style="display:block;background-color:rgb(63,205,210)"><img width="13" src="https://cdn2.hubspot.net/hubfs/53/tools/email-signature-generator/icons/link-icon-2x.png" color="#3FCDD2" style="display:block"></span></td></tr></tbody></table></td><td style="padding:0px"><a href="https://www.cleanaffinity.com/" color="#000000" style="color:rgb(0,0,0);font-size:12px" target="_blank">www.cleanaffinity.com</a></td></tr><tr height="25" style="vertical-align:middle"><td width="30" style="vertical-align:middle"><br></td><td style="padding:0px"><br></td></tr></tbody></table></td></tr></tbody></table></td></tr><tr><td></td></tr></tbody></table><table cellpadding="0" cellspacing="0" style="color:rgb(255,255,255);font-size:medium;vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td style="vertical-align:top"></td><td width="46"></td><td style="padding:0px;vertical-align:middle"><table cellpadding="0" cellspacing="0" style="vertical-align:-webkit-baseline-middle;font-family:Arial"><tbody><tr><td height="30"></td></tr></tbody></table></td></tr></tbody></table></td></tr></tbody></table></div>
                """

        # Convert message text to HTML, preserving line breaks and paragraphs
        html_message = convert_text_to_html(message_text) + footer_html

        # Plain text version of the message
        plain_text = message_text + "\n\nBest regards,\nClean Affinity\nYour Company Address\nPhone Number\nwww.yourwebsite.com"

        # Attach both plain text and HTML versions of the message
        message.attach(MIMEText(plain_text, 'plain'))
        message.attach(MIMEText(html_message, 'html'))

        # Add headers
        message['to'] = receiver
        message['from'] = "hello@cleanaffinity.com"
        message['subject'] = subject

        # Encode the message as base64 for the Gmail API
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        draft_body = {
            'message': {
                'raw': raw
            }
        }

        # Create the draft
        draft = service.users().drafts().create(userId='me', body=draft_body).execute()
        logging.debug(f"Draft created with ID: {draft['id']}")

        # Retrieve the message ID from the draft
        message_id = draft['message']['id']

        # Create or get the label ID
        label_id = create_label_if_not_exists(service, 'me', label_name)
        if label_id:
            # Apply the label to the message in the draft
            apply_label_to_message(service, 'me', message_id, label_id)

        return draft
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


def create_draft_route(subject, message_text, gmail):
    creds = authenticate_gmail()
    if not creds:
        return "Failed to authenticate with Gmail."

    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)

    # Create the draft
    user_info = service.users().getProfile(userId='me').execute()
    sender_email = user_info['emailAddress']
    draft = create_draft(service, "Clean Affinity", sender_email, subject, message_text, gmail)


def add_to_spreadsheet(raw_data):
    # Path to your credentials.json file
    creds_file = r'emailsenderthingy.json'

    # Connect to the Google Sheets API
    creds = Credentials.from_service_account_file(creds_file, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", 'https://www.googleapis.com/auth/gmail.modify'])
    client = gspread.authorize(creds)

    # Open the spreadsheet by its ID
    spreadsheet_id = '1mZ0TseN9pucJEDvQXAzCtKUUgSWT8802SMEo-BfL3KU'  # Replace with your actual spreadsheet ID
    sheet_name = 'Sheet1'  # Replace with your actual sheet name

    # print("eawe", raw_data)
    print(raw_data, "THSI WE RAWWW")
    data = revise_list(raw_data)
    # print("rege", data)

    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
        print(f"Successfully accessed the spreadsheet '{sheet_name}'.")

        for item in data:
            # Ensure each item has exactly 12 columns
            if len(item) != 16:
                print(f"Skipping item with incorrect number of columns: {item}")
                continue

            # Find the next available row (starting from the first column)
            row_number = len(sheet.col_values(1)) + 1

            # Debugging: Print the item and its length to ensure correct insertion
            print(f"Inserting row {row_number}: {item} (Length: {len(item)})")

            # Append the revised data to the next available columns
            sheet.insert_row(item, index=row_number, value_input_option='RAW')

        print("Data appended successfully.")

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"Spreadsheet with ID '{spreadsheet_id}' not found.")
    except Exception as e:
        print(f"An error occurred: {e}")


today = date.today()
months_list = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
month = months_list[today.month-1]


def update_prices():
    global ot, initial, move, monthly, biweekly, weekly
    ot, initial, move, monthly, biweekly, weekly = map(float, update_servers())
    print("Price successfully updated!")


def calc_sqft_price(sqft):
    sqft_price = 70
    try:
        if sqft < 1000.01:
            sqft_price = 70
        elif sqft < 2000.01:
            sqft_price = 90
        elif sqft < 2701:
            sqft_price = 120
        elif sqft < 3500.01:
            sqft_price = 140
        elif sqft < 4200:
            sqft_price = 160
        elif sqft < 10500:
            sqft_price = 250
    except ValueError and UnboundLocalError and IndexError and UnboundLocalError:
        print("Error Loading Quote")
    return sqft_price


def autocalc(sqft, beds, baths, type_clean, name_first, name_last, username, city):
    print(sqft, beds, baths, type_clean, name_first, name_last, username, city)
    elite = 200
    ongoing = 140
    try:
        if type(sqft) != None:
            try:
                # These are the base prices that are the minimum cost of cleans
                try:
                    price_sqft = calc_sqft_price(int(sqft))
                except TypeError:
                    print("Error Loading Quote")
                # On the calculator on excelsheet, "NO TOUCH k9" is the same as "before price"
                before_price = float(baths) * 30 + float(beds) * 5 + price_sqft

                # ["ONETIME", "MOVE", "WEEKLY", "BIWEEKLY", "MONTHLY"]
                if type_clean == 0:
                    elite = before_price * ot
                if type_clean == 1:
                    elite = before_price * move
                if type_clean == 2:
                    ongoing = before_price * weekly
                if type_clean == 3:
                    ongoing = before_price * biweekly
                if type_clean == 4:
                    ongoing = before_price * monthly

                if type_clean == 2 or type_clean == 3 or type_clean == 4:
                    elite = before_price * initial
                    if ongoing < 140:
                        ongoing = 140
                if elite < 200:
                    elite = 200

                title = get_title(sqft, beds, baths, type_clean, name_last, name_first)
                main_info = get_quote(month, round(elite), round(ongoing), type_clean, name_first, username, city)

            except ValueError and UnboundLocalError and IndexError and UnboundLocalError:
                print("Error Loading Quote")
            return title, main_info
    except TypeError:
        return "nothing", "nothing"


# This is all the different scripts
def get_title(sqft, beds, baths, part_list, last, first):
    sqft = int(sqft)
    sqft = round(sqft/10)*10
    beds = int(beds)
    try:
        baths = int(baths)
    except ValueError:
        baths = float(baths)

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
    scripts = [f"""Hi{name},

We're grateful for the opportunity to help with your cleaning needs!

Based on the info you provided and our {date_month} special, your one-time clean will be ${initial} (Includes washing all interior window panes within arms reach!)
•	        Would you like any extras like fridge, oven, window blind or track cleaning?
•	        Are there any other cleaning needs/notes you would like for me to add to our list?
Please let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly, but we still have a few spots open in {date_month}!

We look forward to cleaning for you!
{username}""", f"""Hi{name},

We're grateful for the opportunity to help with your cleaning needs!

Based on the info you provided and our {date_month} special, your moving clean will be ${initial} (Includes washing all interior window panes within arms reach!)
•	        Would you like any extras like fridge, oven, window blind or track cleaning?
•	        Are there any other cleaning needs/notes you would like for me to add to our list?
Please let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly, but we still have a few spots open in {date_month}!

We look forward to cleaning for you!
{username}""", f"""Hi{name}!

We're grateful for the opportunity to help with your cleaning needs!

Based on the info provided, and a special we are running for {date_month}, your initial reset clean will be 50% off at ${initial} (this clean will be 2-3x as long and includes washing all interior window panes within arms reach) and weekly service is ${recuring}.

Please let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}! What works best?

We look forward to cleaning for you!
{username}
""", f"""Hi{name}!

We're grateful for the opportunity to help with your cleaning needs!

Based on the info provided, and a special we are running for {date_month}, your initial reset clean will be 50% off at ${initial} (this clean will be 2-3x as long and includes washing all interior window panes within arms reach) and biweekly service is ${recuring}.

Please let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}! What works best?

We look forward to cleaning for you!
{username}
""", f"""Hi{name}!

We're grateful for the opportunity to help with your cleaning needs!

Based on the info provided, and a special we are running for {date_month}, your initial reset clean will be 50% off at ${initial} (this clean will be 2-3x as long and includes washing all interior window panes within arms reach) and monthly service is ${recuring}.

Please let me know if you would like to get on the schedule and if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}! What works best?

We look forward to cleaning for you!
{username}
"""]
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
""", f"""Hi{name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your moving clean will be ${initial} with our {date_month} special. 

Is this something I can get on the schedule for you?
""", f"""Hi{name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your initial clean will be ${initial} and the following weekly cleans will be ${recuring} with our {date_month} special. 

Is this something I can get on the schedule for you?
""", f"""Hi{name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your initial clean will be ${initial} and the following biweekly cleans will be ${recuring} with our {date_month} special. 

Is this something I can get on the schedule for you?
""", f"""Hi{name}! {username} with Clean Affinity here! 
Thank you for reaching out! 

Based on your address it looks like {sqft} sqft, with {beds} beds and {baths} baths. If that’s correct, your initial clean will be ${initial} and the following monthly cleans will be ${recuring} with our {date_month} special. 

Is this something I can get on the schedule for you?
"""]
    return scripts[part_list]


def failed(date_month, username=""):
    scripts = f"""Hi there!

We're grateful for the opportunity to help with your cleaning needs!

Could you provide the number of bedrooms and bathrooms along with the square footage of the house so I can put a quote together for you?

Please let me know if you have any preferred days/times. Our schedule fills up quickly (especially for the longer initial clean!), but we still have a few spots in {date_month}!

We look forward to cleaning for you!

{username}
"""
    return scripts

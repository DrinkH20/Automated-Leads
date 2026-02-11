import re
import numpy as np
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
TOKEN_FILE = 'token.pickle'
CREDENTIALS_FILE = r'google_secrets.json'


def initialize_client():
    """Initializes the Google Sheets client using service account credentials."""
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


def update_servers(area):
    """Fetches data from the Google Sheet, processes formulas, and returns the calculated values."""
    client = initialize_client()

    if area == "PDX":
        spreadsheet_url = 'https://docs.google.com/spreadsheets/d/1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA/edit?pli=1&gid=0#gid=0'
    elif area == "DFW":
        spreadsheet_url = 'https://docs.google.com/spreadsheets/d/1mYiEYwutXg5R3NAD9ymzN8SwSVRmCKtnD4M_gUDzNlQ/edit?gid=1562728204#gid=1562728204'
    gsheet = client.open_by_url(spreadsheet_url)
    sheet = gsheet.worksheet('Estimator')

    # List of cell references to process
    cells_to_process = ['I20', 'I22', 'I24', 'D26', 'D28', 'D30']
    formula = []

    # Retrieve formulas from the specified cells
    for cell_ref in cells_to_process:
        cell = sheet.acell(cell_ref, value_render_option='FORMULA')
        formula.append(cell.value)

    all_floats = []
    extracted_multipliers = []

    for i in formula:
        # Extract the multiplier right after MAX(...) closes
        match = re.search(r"\)\*(\d+\.\d+|\d+)", i)
        if match:
            extracted_multipliers.append(float(match.group(1)))
        else:
            extracted_multipliers.append(None)

        # Extract numeric values from the first part before '+'
        split_point = i.find('+')
        first_half = i[:split_point] if split_point != -1 else i

        numbers = re.findall(r'\d+\.\d+|\d+', first_half)
        if numbers:
            numbers.pop(0)  # Skip the first number per your original logic
            extracted_numbers = [float(num) if '.' in num else int(num) for num in numbers]
            all_floats.append(extracted_numbers)
        else:
            all_floats.append([])

    # Multiply all the numbers in each sublist
    results = [np.prod(sublist) for sublist in all_floats]

    # Convert results to a list of floats
    calc_factors = [float(result) for result in results]

    return calc_factors, extracted_multipliers

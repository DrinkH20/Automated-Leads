import re
import numpy as np
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
TOKEN_FILE = 'token.pickle'
CREDENTIALS_FILE = r'vibrant-arcanum-432521-q2-e55244124dd0.json'


def initialize_client():
    """Initializes the Google Sheets client using service account credentials."""
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


def update_servers():
    """Fetches data from the Google Sheet, processes formulas, and returns the calculated values."""
    client = initialize_client()
    spreadsheet_url = 'https://docs.google.com/spreadsheets/d/1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA/edit?pli=1&gid=0#gid=0'
    gsheet = client.open_by_url(spreadsheet_url)
    sheet = gsheet.worksheet('Estimator')

    # List of cell references to process
    cells_to_process = ['I20', 'I22', 'I24', 'D26', 'D28', 'D30']
    formula = []

    # Retrieve formulas from the specified cells
    for cell_ref in cells_to_process:
        cell = sheet.acell(cell_ref, value_render_option='FORMULA')
        formula.append(cell.value)

    # Regular expression to extract floats and integers from the first part of each formula
    all_floats = []
    for i in formula:
        split_point = i.find('+')
        first_half = i[:split_point]
        numbers = re.findall(r'\d+\.\d+|\d+', first_half)
        numbers.pop(0)  # Remove the first number as per your original logic
        extracted_numbers = [float(num) if '.' in num else int(num) for num in numbers]
        all_floats.append(extracted_numbers)

    # Multiply all the numbers in each sublist
    results = [np.prod(sublist) for sublist in all_floats]

    # Convert results to a list of floats
    calc_factors = [float(result) for result in results]
    return calc_factors

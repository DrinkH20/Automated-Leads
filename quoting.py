import os
import xlwings as xw

import shutil
import os
# from win32com.client import gencache
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from decimal import Decimal
from gspread.exceptions import APIError
import time


import tempfile
genpy_dir = os.path.join(tempfile.gettempdir(), 'gen_py')
shutil.rmtree(genpy_dir, ignore_errors=True)
# gencache.is_readonly = False
# gencache.Rebuild()

MARKET_OUTPUT_CELLS = {
    "pdx": {
        "initial": "I22",
        "ot": "I20",
        "move": "I24",
        "weekly": "D30",
        "biweekly": "D28",
        "monthly": "D26",
    },
    "dfw": {
        "initial": "I22",
        "ot": "I20",
        "move": "I24",
        "weekly": "D30",
        "biweekly": "D28",
        "monthly": "D26",
    },
    "phx": {
        "initial": "I22",
        "ot": "I20",
        "move": "I24",
        "weekly": "I30",
        "biweekly": "I28",
        "monthly": "I26",
    },
}


def download_specific_sheet(market, download_dir="sheets"):
    import requests
    import os
    market_sheets = {
        "pdx": "1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA",
        "dfw": "1mYiEYwutXg5R3NAD9ymzN8SwSVRmCKtnD4M_gUDzNlQ",
        "phx": "1C0GogsJO1kiQkf3e4Nzr5nPsFECF4QeAl5w7nRQby6c"
    }

    sheet_id = market_sheets.get(market.lower())
    if not sheet_id:
        raise ValueError(f"Invalid market: {market}")

    os.makedirs(download_dir, exist_ok=True)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    response = requests.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to download sheet for {market}: {response.status_code}")

    file_path = os.path.join(download_dir, f"{market}.xlsx")
    with open(file_path, "wb") as f:
        f.write(response.content)

    print(f"Downloaded sheet for {market.upper()} → {file_path}")
    return file_path


def download_all_sheets(download_dir="sheets"):
    import requests
    import os

    market_sheets = {
        "pdx": "1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA",
        "dfw": "1mYiEYwutXg5R3NAD9ymzN8SwSVRmCKtnD4M_gUDzNlQ",
        "phx": "1C0GogsJO1kiQkf3e4Nzr5nPsFECF4QeAl5w7nRQby6c"
    }
    os.makedirs(download_dir, exist_ok=True)
    for market, sheet_id in market_sheets.items():
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        response = requests.get(url)
        if response.status_code == 200:
            file_path = os.path.join(download_dir, f"{market}.xlsx")
            with open(file_path, "wb") as f:
                f.write(response.content)
            print(f"{market.upper()} sheet downloaded.")
        else:
            print(f"Failed to download {market} sheet: {response.status_code}")


from decimal import Decimal

from decimal import Decimal, InvalidOperation

def safe_decimal(val):
    if val is None:
        return Decimal("0")

    if isinstance(val, (int, float, Decimal)):
        return Decimal(str(val))

    val = str(val).strip()

    if val == "":
        return Decimal("0")

    # Remove currency symbols and commas
    val = val.replace("$", "").replace(",", "")

    try:
        return Decimal(val)
    except InvalidOperation:
        print("BAD DECIMAL VALUE:", val)
        return Decimal("0")


def make_quote(initial, ot, move, weekly, biweekly, monthly):
    return {
        "initial": safe_decimal(initial),
        "ot": safe_decimal(ot),
        "move": safe_decimal(move),
        "weekly": safe_decimal(weekly),
        "biweekly": safe_decimal(biweekly),
        "monthly": safe_decimal(monthly),
    }


# def batch_get_quotes(market, quotes_list):
#     """
#     Fast batch quote engine using Google Sheets calculation.
#
#     quotes_list = [
#         {'sqft': 1500, 'beds': 1, 'baths': 1},
#         ...
#     ]
#     """
#     import time
#     import gspread
#     from oauth2client.service_account import ServiceAccountCredentials
#
#     market = market.lower()
#
#     MARKET_SHEETS = {
#         "pdx": "1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA",
#         "dfw": "1mYiEYwutXg5R3NAD9ymzN8SwSVRmCKtnD4M_gUDzNlQ",
#         "phx": "1C0GogsJO1kiQkf3e4Nzr5nPsFECF4QeAl5w7nRQby6c"
#     }
#
#     if market not in MARKET_SHEETS:
#         raise ValueError("Invalid market")
#
#     scope = [
#         "https://spreadsheets.google.com/feeds",
#         "https://www.googleapis.com/auth/drive"
#     ]
#     creds = ServiceAccountCredentials.from_json_keyfile_name(
#         "google_secrets.json", scope
#     )
#     client = gspread.authorize(creds)
#
#     sheet = client.open_by_key(MARKET_SHEETS[market]).worksheet("Estimator")
#
#     # Prepare input
#     inputs = [[q["sqft"], q["beds"], q["baths"]] for q in quotes_list]
#     start_row = 2
#     end_row = start_row + len(inputs) - 1
#     sheet.update(f"A{start_row}:C{end_row}", inputs)
#
#     time.sleep(1.2)  # add a small buffer to allow calc
#
#     # Pull results
#     results = []
#     cells = MARKET_OUTPUT_CELLS[market]
#
#     for q in quotes_list:
#         sheet.update("E3", [[int(q["sqft"])]])
#         sheet.update("E4", [[int(q["beds"])]])
#         sheet.update("E5", [[float(q["baths"])]])
#
#         time.sleep(0.15)  # small buffer for calc (tune down later)
#
#         quote = make_quote(
#             sheet.acell(cells["initial"]).value,
#             sheet.acell(cells["ot"]).value,
#             sheet.acell(cells["move"]).value,
#             sheet.acell(cells["weekly"]).value,
#             sheet.acell(cells["biweekly"]).value,
#             sheet.acell(cells["monthly"]).value,
#         )
#         results.append({"output": quote})
#
#     return results

def safe_update(sheet, range_name, values, retries=5):
    for i in range(retries):
        try:
            sheet.update(range_name, values)
            return
        except APIError as e:
            if "429" in str(e):
                time.sleep(2 ** i)
            else:
                raise

def batch_get_quotes(market, quotes_list):
    """
    Quota-safe batch quote engine using Google Sheets calculation.
    """

    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    market = market.lower()

    MARKET_SHEETS = {
        "pdx": "1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA",
        "dfw": "1mYiEYwutXg5R3NAD9ymzN8SwSVRmCKtnD4M_gUDzNlQ",
        "phx": "1C0GogsJO1kiQkf3e4Nzr5nPsFECF4QeAl5w7nRQby6c"
    }

    if market not in MARKET_SHEETS:
        raise ValueError("Invalid market")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    BASE_DIR = os.getenv("APP_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
    creds_file = os.path.join(BASE_DIR, "credentials", "google_secrets.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        creds_file, scope
    )

    client = gspread.authorize(creds)
    sheet = client.open_by_key(MARKET_SHEETS[market]).worksheet("Estimator")

    results = []
    cells = MARKET_OUTPUT_CELLS[market]

    # Prepare the output ranges for batch read
    output_ranges = [
        cells["initial"],
        cells["ot"],
        cells["move"],
        cells["weekly"],
        cells["biweekly"],
        cells["monthly"],
    ]

    for q in quotes_list:

        # 🔥 1 API CALL INSTEAD OF 3
        safe_update(sheet, "E3:E5", [
            [int(q["sqft"])],
            [int(q["beds"])],
            [float(q["baths"])]
        ])

        # 🔥 1 API CALL INSTEAD OF 6
        values = sheet.batch_get(output_ranges)

        quote = make_quote(
            values[0][0][0] if values[0] else 0,
            values[1][0][0] if values[1] else 0,
            values[2][0][0] if values[2] else 0,
            values[3][0][0] if values[3] else 0,
            values[4][0][0] if values[4] else 0,
            values[5][0][0] if values[5] else 0,
        )

        results.append({"output": quote})

    return results


def pull_quote_from_sheet(sheet, market):
    cells = MARKET_OUTPUT_CELLS[market]

    return make_quote(
        sheet.range(cells["initial"]).value,
        sheet.range(cells["ot"]).value,
        sheet.range(cells["move"]).value,
        sheet.range(cells["weekly"]).value,
        sheet.range(cells["biweekly"]).value,
        sheet.range(cells["monthly"]).value,
    )



# market = "PDX"

# download_all_sheets()

# quotes_to_run = [
#     {"sqft": 1500, "beds": 1, "baths": 1},
#     {"sqft": 2200, "beds": 2, "baths": 2},
#     {"sqft": 3400, "beds": 3, "baths": 2},
# ]
#
# batch_results = batch_get_quotes("pdx", quotes_to_run)
#
# for r in batch_results:
#     print(f"Input: {r['input']} → Quote: {r['output']}")
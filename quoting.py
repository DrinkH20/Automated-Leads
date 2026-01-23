import os
import xlwings as xw

import shutil
import os
from win32com.client import gencache


# def download_specific_sheet(market, download_dir="sheets"):
#     import requests
#     import os
#     market_sheets = {
#         "pdx": "1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA",
#         "dfw": "1mYiEYwutXg5R3NAD9ymzN8SwSVRmCKtnD4M_gUDzNlQ",
#         "phx": "1C0GogsJO1kiQkf3e4Nzr5nPsFECF4QeAl5w7nRQby6c"
#     }
#
#     sheet_id = market_sheets.get(market.lower())
#     if not sheet_id:
#         raise ValueError(f"Invalid market: {market}")
#
#     os.makedirs(download_dir, exist_ok=True)
#     url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
#     response = requests.get(url)
#     if response.status_code != 200:
#         raise RuntimeError(f"Failed to download sheet for {market}: {response.status_code}")
#
#     file_path = os.path.join(download_dir, f"{market}.xlsx")
#     with open(file_path, "wb") as f:
#         f.write(response.content)
#
#     print(f"Downloaded sheet for {market.upper()} → {file_path}")
#     return file_path


# def download_all_sheets(download_dir="sheets"):
#     import requests
#     import os
#
#     market_sheets = {
#         "pdx": "1VHiCVG3sYEwoeBHVkWruhEC5n2q5AL3K4SJzpYbj5XA",
#         "dfw": "1mYiEYwutXg5R3NAD9ymzN8SwSVRmCKtnD4M_gUDzNlQ",
#         "phx": "1C0GogsJO1kiQkf3e4Nzr5nPsFECF4QeAl5w7nRQby6c"
#     }
#     os.makedirs(download_dir, exist_ok=True)
#     for market, sheet_id in market_sheets.items():
#         url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
#         response = requests.get(url)
#         if response.status_code == 200:
#             file_path = os.path.join(download_dir, f"{market}.xlsx")
#             with open(file_path, "wb") as f:
#                 f.write(response.content)
#             print(f"{market.upper()} sheet downloaded.")
#         else:
#             print(f"Failed to download {market} sheet: {response.status_code}")


genpy_dir = os.path.join(os.environ['LOCALAPPDATA'], 'Temp', 'gen_py')
shutil.rmtree(genpy_dir, ignore_errors=True)
gencache.is_readonly = False
gencache.Rebuild()


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

def make_quote(initial, ot, move, weekly, biweekly, monthly):
    return {
        "initial": Decimal(str(initial)),
        "ot": Decimal(str(ot)),
        "move": Decimal(str(move)),
        "weekly": Decimal(str(weekly)),
        "biweekly": Decimal(str(biweekly)),
        "monthly": Decimal(str(monthly)),
    }


def batch_get_quotes(market, quotes_list, download_dir="sheets"):
    """
    Runs quotes in batch using the existing Excel estimator file.
    quotes_list = list of dicts like [{'sqft': 1500, 'beds': 1, 'baths': 1}, ...]
    Returns: List of quote results
    """
    market = market.lower()
    file_path = os.path.join(download_dir, f"{market}.xlsx")

    app = xw.App(visible=False)
    book = app.books.open(file_path)
    sheet = book.sheets["Estimator"]
    results = []

    for i, q in enumerate(quotes_list):
        # Set inputs
        sheet.range("E3").value = q['sqft']
        sheet.range("E4").value = q['beds']
        sheet.range("E5").value = q['baths']
        app.calculate()  # Excel recalculates

        # Pull values
        # if market == "phx":
        #     quote = [
        #         sheet.range("I22").value,
        #         sheet.range("I20").value,
        #         sheet.range("I24").value,
        #         sheet.range("I30").value,
        #         sheet.range("I28").value,
        #         sheet.range("I26").value
        #     ]
        # else:
        #     quote = [
        #         sheet.range("I22").value,
        #         sheet.range("I20").value,
        #         sheet.range("I24").value,
        #         sheet.range("D30").value,
        #         sheet.range("D28").value,
        #         sheet.range("D26").value
        #     ]
        if market == "phx":
            quote = make_quote(
                sheet.range("I22").value,  # initial
                sheet.range("I20").value,  # ot
                sheet.range("I24").value,  # move
                sheet.range("I30").value,  # weekly
                sheet.range("I28").value,  # biweekly
                sheet.range("I26").value  # monthly
            )
        else:
            quote = make_quote(
                sheet.range("I22").value,  # initial
                sheet.range("I20").value,  # ot
                sheet.range("I24").value,  # move
                sheet.range("D30").value,  # weekly
                sheet.range("D28").value,  # biweekly
                sheet.range("D26").value  # monthly
            )

        # results.append({
        #     "input": q,
        #     "output": quote
        # })
        results.append({
            "output": quote
        })

    book.close()
    app.quit()
    return results

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
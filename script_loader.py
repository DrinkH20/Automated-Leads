from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import os, sys

SHEET_ID = "1el4xvVhOMuUak0tfu-EVGoKHmjM8nkpa5w2gqhYuS3M"

SCRIPT_CACHE = {}  # cache per market

SCRIPT_KEYS = {
    "QUOTE": "quote_text",
    "OUT_OF_AREA": "out_of_area",
    "FAILED": "failed",
}


def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def get_script(key, market, type_, field="script"):

    market = market.upper()
    key = key.lower()
    type_ = str(type_).upper()

    scripts = load_scripts(market)

    entry = scripts.get((key, market, type_), {})
    if not entry:
        raise ValueError(
            f"No script found for key={key}, market={market}, type={type_}"
        )

    if field not in entry:
        raise ValueError(
            f"Field '{field}' missing for key={key}, market={market}, type={type_}"
        )

    return entry[field]


def load_scripts(market):
    market = market.upper()

    if market in SCRIPT_CACHE:
        return SCRIPT_CACHE[market]

    creds = Credentials.from_service_account_file(
        resource_path("credentials/google_secrets.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )

    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=SHEET_ID,
        range=market
    ).execute()

    values = result.get("values", [])

    if not values:
        SCRIPT_CACHE[market] = {}
        return {}

    headers = [h.strip().lower() for h in values[0]]
    scripts = {}

    for row in values[1:]:
        row_dict = {
            headers[i]: row[i] if i < len(row) else ""
            for i in range(len(headers))
        }

        key_tuple = (
            row_dict["key"].strip().lower(),
            market,
            row_dict["type"].strip().upper()
        )

        scripts[key_tuple] = {
            "script": row_dict.get("script", ""),
            "title": row_dict.get("title", ""),
            "texting": row_dict.get("texting", "")
        }

    SCRIPT_CACHE[market] = scripts
    return scripts


def get_email_script(key, market, type_):
    return get_script(key, market, type_, field="script")


def get_text_script(key, market, type_):
    return get_script(key, market, type_, field="texting")


def get_title(key, market, type_):
    return get_script(key, market, type_, field="title")

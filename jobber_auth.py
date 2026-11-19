"""
One-time Jobber approval: gets the refresh token the quote engine uses to look
up PHX clients, and saves it to .env. Run it on your own computer:

    venv\\Scripts\\python.exe jobber_auth.py

Needs in .env first (from the app in Jobber's Developer Center):
    JOBBER_CLIENT_ID=...
    JOBBER_CLIENT_SECRET=...
Jobber allows localhost redirects without listing them, so this script
catches Jobber's reply itself on http://localhost:8765 (override with
JOBBER_REDIRECT_URI). The app's Callback URL setting isn't used.

Nothing is printed except the approval link and a success/failure line, so the
output is safe to share.
"""

import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
AUTHORIZE_URL = "https://api.getjobber.com/api/oauth/authorize"
TOKEN_URL = "https://api.getjobber.com/api/oauth/token"
GRAPHQL_URL = "https://api.getjobber.com/api/graphql"
API_VERSION = os.getenv("JOBBER_API_VERSION", "2025-04-16")


def save_env(key, value):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def wait_for_reply(redirect_uri):
    """Catch the browser's redirect from Jobber; return its query parameters."""
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            if "code" in params or "error" in params:
                got.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Done - you can close this tab and go back to PowerShell.</h2>")

        def log_message(self, *args):
            pass

    port = urlparse(redirect_uri).port or 80
    server = HTTPServer(("localhost", port), Handler)
    server.timeout = 5
    deadline = time.time() + 300
    while not got and time.time() < deadline:
        server.handle_request()  # one request, or 5s of nothing
    server.server_close()
    if not got:
        sys.exit("Timed out waiting for Jobber. Run the script again.")
    if "error" in got:
        sys.exit(f"Jobber said: {got.get('error_description', got['error'])}")
    return got


def main():
    load_dotenv(ENV_PATH)
    client_id = os.getenv("JOBBER_CLIENT_ID")
    client_secret = os.getenv("JOBBER_CLIENT_SECRET")
    redirect_uri = os.getenv("JOBBER_REDIRECT_URI", "http://localhost:8765/jobber-callback")
    if not client_id or not client_secret:
        sys.exit("Add JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET to .env first.")

    state = secrets.token_urlsafe(16)
    link = AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "state": state})
    print("\n1. Approve the app in the browser window that opens (log in as a Jobber admin).")
    print("   If no window opens, paste this link into your browser:\n\n   " + link + "\n")
    webbrowser.open(link)
    print("2. Waiting for Jobber to send you back here (5 minutes)...")
    query = wait_for_reply(redirect_uri)
    if query.get("state", [""])[0] != state:
        sys.exit("That address doesn't match this approval (state differs). Run the script again.")
    code = query.get("code", [""])[0]
    if not code:
        sys.exit("No approval code in that address. Run the script again.")

    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret,
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
    }, timeout=30)
    if resp.status_code >= 400:
        sys.exit(f"Jobber refused the code ({resp.status_code}): {resp.text[:200]}")
    tokens = resp.json()
    save_env("JOBBER_REFRESH_TOKEN", tokens["refresh_token"])

    check = requests.post(GRAPHQL_URL, json={"query": "{ account { name } }"}, timeout=30, headers={
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-JOBBER-GRAPHQL-VERSION": API_VERSION})
    name = (((check.json() or {}).get("data") or {}).get("account") or {}).get("name")
    print(f"\nDone. Connected to Jobber account: {name or '(could not read the name)'}")
    print("JOBBER_REFRESH_TOKEN was saved to .env.")


if __name__ == "__main__":
    main()

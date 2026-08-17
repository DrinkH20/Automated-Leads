"""Gmail authentication -- one shared implementation for every entry point.

Uses the OAuth installed-app flow. Authorizing opens a browser once; the token
is then cached in credentials/token.pickle and refreshed automatically.

IMPORTANT -- the 7-day trap:
    Keep the OAuth consent screen's publishing status on "In production" in
    Google Cloud Console (project vibrant-arcanum-432521-q2). While it is set to
    "Testing", Google expires every refresh token after 7 days. The automation
    then dies mid-week with 'invalid_grant: Token has been expired or revoked',
    and the droplet has no browser to re-approve it.

To (re)authorize, on a machine with a browser:
    python gmail_auth.py
then copy credentials/token.pickle to the droplet.
"""
import logging
import os
import pickle

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = os.getenv("APP_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "credentials", "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "credentials", "token.pickle")

GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.modify',
]


def _save(creds):
    with open(TOKEN_FILE, 'wb') as fh:
        pickle.dump(creds, fh)


def get_gmail_credentials(scopes=None, allow_browser=False):
    """Return usable Gmail credentials from the cached token.

    allow_browser defaults to False so that unattended runs (cron on the
    droplet) fail loudly instead of hanging forever on a consent screen that
    nobody is there to click. Pass True only from an interactive session.
    """
    scopes = scopes or GMAIL_SCOPES
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as fh:
            creds = pickle.load(fh)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except RefreshError as e:
            # Revoked, or expired past recovery -- a password change, or the
            # 7-day expiry that applies while the consent screen is in Testing.
            # Nothing to salvage; a fresh consent is the only fix.
            logging.warning("Cached Gmail token is unusable (%s).", e)
            creds = None

    if not allow_browser:
        raise RuntimeError(
            "No usable Gmail token at {}. Run 'python gmail_auth.py' on a machine "
            "with a browser, then copy credentials/token.pickle here.".format(TOKEN_FILE)
        )

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, scopes)
    creds = flow.run_local_server(port=8080, prompt='consent')
    _save(creds)
    return creds


if __name__ == '__main__':
    from googleapiclient.discovery import build

    print("Opening a browser to authorize Gmail access...")
    creds = get_gmail_credentials(allow_browser=True)

    profile = build('gmail', 'v1', credentials=creds,
                    cache_discovery=False).users().getProfile(userId='me').execute()
    print("\nAUTHORIZED ->", profile.get('emailAddress'))
    print("token saved to:", TOKEN_FILE)

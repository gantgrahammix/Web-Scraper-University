"""One Google sign-in (your javon@naturl.audio account) shared by Sheets and Gmail.

The first time, a browser window opens so you can approve access; the token is
saved to token.json and refreshed automatically after that."""
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",   # lets the tool create its own spreadsheet
    "https://www.googleapis.com/auth/gmail.compose",   # create drafts and send mail
    "https://www.googleapis.com/auth/gmail.readonly",  # detect replies, bounces and drafts you sent
]


class GoogleAuthError(RuntimeError):
    pass


def is_connected():
    return config.GOOGLE_TOKEN.exists()


def get_credentials(interactive=True):
    creds = None
    if config.GOOGLE_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(config.GOOGLE_TOKEN))
        if not creds.has_scopes(SCOPES):  # signed in before new permissions were added
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            config.GOOGLE_TOKEN.write_text(creds.to_json())
            return creds
        except Exception:
            creds = None
    if not interactive:
        raise GoogleAuthError("Not signed in to Google. Use 'Connect Google account' in the app or `python cli.py google-login`.")
    if not config.GOOGLE_OAUTH_CLIENT.exists():
        raise GoogleAuthError(
            f"Missing {config.GOOGLE_OAUTH_CLIENT.name}. Download your OAuth client (Desktop app) "
            "from Google Cloud Console; see README 'Google setup'."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(config.GOOGLE_OAUTH_CLIENT), SCOPES)
    creds = flow.run_local_server(port=0, login_hint=config.GMAIL_SENDER, prompt="consent")
    config.GOOGLE_TOKEN.write_text(creds.to_json())
    return creds


def disconnect():
    if config.GOOGLE_TOKEN.exists():
        config.GOOGLE_TOKEN.unlink()

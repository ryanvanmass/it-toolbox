from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from it_toolbox.core.auth.credential_store import (
    clear_credentials,
    load_credentials,
    save_credentials,
)
from it_toolbox.core.settings import oauth_client_path

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class OAuthClientNotConfigured(Exception):
    """Raised when no OAuth client JSON has been placed at oauth_client_path()."""


def is_configured() -> bool:
    return oauth_client_path().is_file()


def sign_in() -> Credentials:
    """Run the interactive OAuth loopback flow, opening the user's browser.

    Blocking — call from a background thread, never the Qt main thread.
    """
    if not is_configured():
        raise OAuthClientNotConfigured(
            f"No OAuth client found at {oauth_client_path()}. "
            "Download a 'Desktop app' OAuth client JSON from the Google Cloud "
            "Console and save it at that path."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(oauth_client_path()), SCOPES)
    # timeout_seconds guards against the browser flow never redirecting back
    # (e.g. the user abandons it, or Google shows a block page instead of
    # completing the redirect) — without it this blocks the calling thread
    # forever and the UI can never recover.
    credentials = flow.run_local_server(port=0, timeout_seconds=180)
    save_credentials(credentials)
    return credentials


def get_credentials() -> Credentials | None:
    """Return valid credentials from the keyring, refreshing if needed.

    Returns None if the user has never signed in, or if the stored refresh
    token is no longer valid (the caller should then prompt sign_in() again).
    Blocking (refresh does a network call) — call from a background thread.
    """
    credentials = load_credentials()
    if credentials is None:
        return None

    if credentials.valid:
        return credentials

    if credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            clear_credentials()
            return None
        save_credentials(credentials)
        return credentials

    clear_credentials()
    return None


def sign_out() -> None:
    clear_credentials()

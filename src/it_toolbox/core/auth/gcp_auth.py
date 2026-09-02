import shutil
import subprocess

from google.oauth2.credentials import Credentials

GCLOUD_CMD = "gcloud"

INSTALL_URL = "https://cloud.google.com/sdk/docs/install"


class GcloudNotFound(Exception):
    """Raised when the gcloud CLI is not installed / not on PATH."""


def is_available() -> bool:
    return shutil.which(GCLOUD_CMD) is not None


def _run(*args: str) -> str:
    if not is_available():
        raise GcloudNotFound(
            f"gcloud CLI not found on PATH. Install it from {INSTALL_URL} and relaunch."
        )
    result = subprocess.run(
        [GCLOUD_CMD, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gcloud {' '.join(args)} failed")
    return result.stdout.strip()


def get_active_account() -> str | None:
    account = _run("config", "get-value", "account")
    if not account or account == "(unset)":
        return None
    return account


def sign_in() -> str:
    """Runs the interactive `gcloud auth login` browser flow.

    Blocking — call from a background thread, never the Qt main thread.
    """
    _run("auth", "login", "--brief")
    account = get_active_account()
    if account is None:
        raise RuntimeError("gcloud auth login completed but no active account was found.")
    return account


def sign_out() -> None:
    account = get_active_account()
    if account is not None:
        _run("auth", "revoke", account)


def get_credentials() -> Credentials:
    """A Credentials wrapper around a freshly minted access token.

    Minted fresh on every call rather than cached — gcloud already handles
    token storage/refresh on disk, so there's nothing to duplicate here, and
    a bare token-only Credentials object never refreshes itself once expired.
    """
    return Credentials(token=_run("auth", "print-access-token"))

import json
import platform
import shutil
import subprocess

from google.oauth2.credentials import Credentials

GCLOUD_CMD = "gcloud"

# On Windows, gcloud is a .cmd batch script — CreateProcess (what subprocess
# uses under shell=False) can't launch those directly, only cmd.exe can.
# Linux/macOS's gcloud is a real executable script, so this only applies here.
_IS_WINDOWS = platform.system() == "Windows"

INSTALL_URL = "https://cloud.google.com/sdk/docs/install"


class GcloudNotFound(Exception):
    """Raised when the gcloud CLI is not installed / not on PATH."""


class GcloudUpdateUnsupported(Exception):
    """Raised when this gcloud install can't update itself -- installed by
    a package manager (dnf/apt/snap/Homebrew...), which disables gcloud's
    component manager. gcloud's own error names the package-manager
    command that does the equivalent; that's kept in suggested_command
    (None if it couldn't be picked out of the message).
    """

    def __init__(self, message: str, suggested_command: str | None) -> None:
        super().__init__(message)
        self.suggested_command = suggested_command


# gcloud's wording when the component manager is disabled; it's followed by
# "...to achieve the same result for this installation:" and the command.
_COMPONENT_MANAGER_DISABLED = "component manager is disabled"
_SUGGESTED_COMMAND_MARKER = "for this installation:"


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
        shell=_IS_WINDOWS,
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


def get_version() -> str:
    """The installed Google Cloud SDK version, e.g. "540.0.0"."""
    return json.loads(_run("version", "--format=json"))["Google Cloud SDK"]


def update() -> tuple[str, str]:
    """Runs `gcloud components update` and returns (old, new) versions --
    equal when it was already up to date.

    Blocking (can take minutes) — call from a background thread, never the
    Qt main thread. Raises GcloudUpdateUnsupported for a package-manager
    install, and RuntimeError for anything else (e.g. no write access to a
    system-wide install directory).
    """
    old_version = get_version()
    try:
        _run("components", "update", "--quiet")
    except RuntimeError as error:
        message = str(error)
        # gcloud hard-wraps its error text, so the phrase can straddle a line.
        if _COMPONENT_MANAGER_DISABLED not in " ".join(message.split()):
            raise
        _, found, after = message.partition(_SUGGESTED_COMMAND_MARKER)
        suggested_command = " ".join(after.split()) if found else None
        raise GcloudUpdateUnsupported(message, suggested_command or None) from error
    return old_version, get_version()


def get_credentials() -> Credentials:
    """A Credentials wrapper around a freshly minted access token.

    Minted fresh on every call rather than cached — gcloud already handles
    token storage/refresh on disk, so there's nothing to duplicate here, and
    a bare token-only Credentials object never refreshes itself once expired.
    """
    return Credentials(token=_run("auth", "print-access-token"))

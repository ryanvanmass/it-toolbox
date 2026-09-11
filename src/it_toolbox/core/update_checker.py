"""Checks the installed app version against GitHub Releases — see
docs/releasing.md for how a release actually gets published (a version
tag pushed by hand, never by the app itself).
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import requests
from packaging.version import InvalidVersion, Version

PACKAGE_NAME = "it-toolbox"
REPO = "ryanvanmass/it-toolbox"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
_REQUEST_TIMEOUT = 10
_DOWNLOAD_TIMEOUT_SEC = 60
# Generous but bounded -- a silent Inno Setup install of this app's size
# should take seconds, not minutes; this just guards against a hung
# installer process rather than expecting to be hit in practice.
_INSTALL_TIMEOUT_SEC = 300


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    html_url: str
    windows_installer_url: str | None = None


class UpdateInstallError(Exception):
    pass


def get_installed_version() -> str:
    return metadata.version(PACKAGE_NAME)


def get_latest_release() -> ReleaseInfo | None:
    """None means no release has been published yet (a real, expected
    state right now — see docs/releasing.md), not an error."""
    response = requests.get(_LATEST_RELEASE_URL, timeout=_REQUEST_TIMEOUT)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    tag_name = data["tag_name"]
    version = tag_name.removeprefix("v")
    windows_installer_url = next(
        (
            asset["browser_download_url"]
            for asset in data.get("assets", [])
            if asset["name"].endswith(".exe")
        ),
        None,
    )
    return ReleaseInfo(
        version=version,
        html_url=data["html_url"],
        windows_installer_url=windows_installer_url,
    )


def download_and_install_windows_update(installer_url: str) -> None:
    """Downloads the Windows installer and runs it silently in place,
    then relaunches the app -- Windows-only (the caller is expected to
    only reach this from a platform-gated UI action, same convention as
    settings/ui/main_view.py's FreeRDP-fetch button).

    Inno Setup's default PrivilegesRequired=admin (see
    packaging/windows/it-toolbox.iss) bakes a requireAdministrator
    manifest into the installer -- Windows honors that for *any*
    process-creation call, so plain subprocess.Popen below still shows
    the same UAC consent prompt the user would get double-clicking the
    installer by hand. Nothing extra (ShellExecute/"runas") is needed to
    trigger it.

    Raises UpdateInstallError on download failure, a non-zero installer
    exit code, or a timeout waiting for it. On success, the new version
    has already been launched as a separate process before this returns
    -- the caller is expected to quit this process right after.
    """
    response = requests.get(installer_url, timeout=_DOWNLOAD_TIMEOUT_SEC)
    response.raise_for_status()

    fd, installer_path_str = tempfile.mkstemp(suffix=".exe")
    installer_path = Path(installer_path_str)
    with os.fdopen(fd, "wb") as f:
        f.write(response.content)

    proc = subprocess.Popen(
        [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    )
    try:
        returncode = proc.wait(timeout=_INSTALL_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as e:
        # Deliberately not cleaning up installer_path here -- the process
        # may still be running and holding the file open, and Windows
        # (unlike POSIX) refuses to delete a file a running process still
        # has open. Attempting it would raise a PermissionError that
        # masks this more useful TimeoutExpired-derived error.
        raise UpdateInstallError(
            f"Installer at {installer_path} did not finish within {_INSTALL_TIMEOUT_SEC}s"
        ) from e

    # proc.wait() returned (didn't raise) -- the installer process has
    # actually exited by this point, so the file is no longer in use.
    installer_path.unlink(missing_ok=True)

    if returncode != 0:
        raise UpdateInstallError(f"Installer exited with code {returncode}")

    # Fixed by packaging/windows/it-toolbox.iss's DefaultDirName -- not a
    # frozen build with a discoverable sys.frozen/sys.executable path to
    # introspect (see that file's own comment), so this known-fixed
    # location is looked up the same way settings/ui/main_view.py's
    # FreeRDP-fetch code looks up LOCALAPPDATA, rather than guessed at.
    # Deliberately pythonw.exe -m it_toolbox, not the
    # {app}\Scripts\it-toolbox.exe launcher pip generates at build time --
    # that launcher hardcodes the *absolute* interpreter path from build
    # time (pip/distlib script stubs aren't relocatable), which breaks the
    # instant this tree is copied anywhere else, same failure
    # packaging/windows/it-toolbox.iss's own [Icons]/[Run] entries hit and
    # now avoid the same way.
    app_exe = Path(os.environ["ProgramFiles"]) / "IT Toolbox" / "pythonw.exe"
    subprocess.Popen([str(app_exe), "-m", "it_toolbox"])


def is_update_available(installed_version: str, latest_version: str) -> bool:
    try:
        return Version(latest_version) > Version(installed_version)
    except InvalidVersion:
        # Unparseable version strings shouldn't crash the check — treat as
        # "can't tell, assume up to date" rather than surfacing an error for
        # what's ultimately just a version display comparison.
        return False

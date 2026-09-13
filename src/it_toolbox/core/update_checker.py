"""Checks the installed app version against GitHub Releases — see
docs/releasing.md for how a release actually gets published (a version
tag pushed by hand, never by the app itself).
"""

import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import requests
from packaging.version import InvalidVersion, Version

PACKAGE_NAME = "it-toolbox"
REPO = "ryanvanmass/it-toolbox"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
# /releases/latest (above) only ever returns the newest *non*-prerelease,
# non-draft release -- this is the plain list endpoint instead, which
# does include pre-releases (unauthenticated requests never see drafts
# regardless, so no filtering needed there), sorted newest-created-first.
_RELEASES_LIST_URL = f"https://api.github.com/repos/{REPO}/releases"
_REQUEST_TIMEOUT = 10
_DOWNLOAD_TIMEOUT_SEC = 60
# Matches gcp_client.download_object's chunk size -- also the unit
# progress gets reported in, rather than per-byte, for the same reason:
# an installer this size (~100-200MB) would otherwise fire the
# cross-thread progress signal thousands of times a second for no
# perceptible benefit to a status bar.
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    html_url: str
    windows_installer_url: str | None = None


class UpdateInstallError(Exception):
    pass


def get_installed_version() -> str:
    return metadata.version(PACKAGE_NAME)


def get_latest_release(include_prerelease: bool = False) -> ReleaseInfo | None:
    """None means no release has been published yet (a real, expected
    state right now — see docs/releasing.md), not an error.

    include_prerelease=True is Settings > App Updates' opt-in beta-testing
    toggle (settings.load_include_prerelease_updates()) -- it switches
    from GitHub's /releases/latest (which never returns a pre-release) to
    the plain releases list and takes its first, newest entry instead,
    pre-release or not.
    """
    if include_prerelease:
        response = requests.get(_RELEASES_LIST_URL, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        releases = response.json()
        if not releases:
            return None
        data = releases[0]
    else:
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


def download_and_install_windows_update(
    installer_url: str, on_progress: Callable[[int, int], None] | None = None
) -> None:
    """Downloads the Windows installer and launches it silently,
    detached from this process -- Windows-only (the caller is expected
    to only reach this from a platform-gated UI action, same convention
    as settings/ui/main_view.py's FreeRDP-fetch button).

    Deliberately does NOT wait for the installer to finish, and does NOT
    relaunch the app itself -- an earlier version did both from this
    same process, but that process's own pythonw.exe/python312.dll are
    files inside {app} that the installer is about to delete and
    replace. Inno Setup's default CloseApplications=yes uses Windows
    Restart Manager to silently kill (no prompt, since this is a silent
    install) any process holding a handle into that directory before it
    touches files -- which is exactly this process, mid-wait(). Confirmed
    on a real install, not theoretical: the waiting process was killed
    before the installer ever reached its own [InstallDelete] step, so
    it never returned to relaunch anything, and no error surfaced
    anywhere because the process that would've reported it was gone.

    So instead: launch the installer and immediately get out of its way
    -- the caller is still expected to quit this process right after
    this returns, same as before, just sooner (before waiting on
    anything, not after). Freeing this process's own file handles before
    Inno ever reaches [InstallDelete] avoids the conflict entirely.
    packaging/windows/it-toolbox.iss's [Run] postinstall entry
    (deliberately without skipifsilent) launches the new version once
    Inno's done, since this process won't be around to do it.

    Inno Setup's default PrivilegesRequired=admin (see that same .iss
    file) bakes a requireAdministrator manifest into the installer --
    Windows honors that for *any* process-creation call, so plain
    subprocess.Popen below still shows the same UAC consent prompt the
    user would get double-clicking the installer by hand. Nothing extra
    (ShellExecute/"runas") is needed to trigger it.

    on_progress, if given, is called periodically during the download
    with (bytes_downloaded, total_bytes) -- total_bytes is 0 if the
    server didn't send a Content-Length. This function runs on a
    background thread (see settings/ui/main_view.py's
    run_in_background), so on_progress must itself be safe to call from
    there -- the caller is expected to pass a Qt Signal's .emit (safe
    cross-thread by Qt's own design), not touch any widget directly.

    Raises UpdateInstallError on download failure, or if the installer
    process itself fails to even start. Does NOT raise for anything that
    happens during or after the actual install -- this process is gone
    long before that, by design.
    """
    with requests.get(installer_url, timeout=_DOWNLOAD_TIMEOUT_SEC, stream=True) as response:
        response.raise_for_status()
        # Only created once the response is confirmed good -- a failed
        # request (404, network error) shouldn't leak an empty temp file.
        fd, installer_path_str = tempfile.mkstemp(suffix=".exe")
        installer_path = Path(installer_path_str)
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with os.fdopen(fd, "wb") as f:
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)

    # Not cleaned up afterward -- this process doesn't wait around to
    # learn when the installer is done with it, and Windows won't allow
    # deleting a file a running process still has open anyway. Left for
    # Windows' own temp-directory cleanup.
    try:
        subprocess.Popen([str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    except OSError as e:
        raise UpdateInstallError(f"Failed to launch installer at {installer_path}: {e}") from e


def is_update_available(installed_version: str, latest_version: str) -> bool:
    try:
        return Version(latest_version) > Version(installed_version)
    except InvalidVersion:
        # Unparseable version strings shouldn't crash the check — treat as
        # "can't tell, assume up to date" rather than surfacing an error for
        # what's ultimately just a version display comparison.
        return False

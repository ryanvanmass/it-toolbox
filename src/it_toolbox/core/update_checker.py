"""Checks the installed app version against GitHub Releases — see
docs/releasing.md for how a release actually gets published (a version
tag pushed by hand, never by the app itself).
"""

import os
import shutil
import subprocess
import sys
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
# regardless, so no filtering needed there). NOT reliably newest-first --
# see _newest_release's own comment for why that can't be assumed here.
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
    macos_dmg_url: str | None = None


class UpdateInstallError(Exception):
    pass


def get_installed_version() -> str:
    return metadata.version(PACKAGE_NAME)


def _newest_release(releases: list[dict]) -> dict:
    """Picks by actual version comparison, not list position.

    Confirmed on a real repo, not theoretical: right after publishing
    v0.3.0-beta.10, /releases still listed it 4th -- behind beta.9,
    beta.8, and beta.7 -- despite beta.10 having the highest release id
    *and* the latest created_at/published_at of everything in the list.
    GitHub's listing here just isn't reliably newest-first immediately
    after a publish (some indexing lag, apparently), so trusting
    releases[0] can silently offer a stale "latest" release for a while.
    Comparing versions directly sidesteps needing that ordering to be
    right at all. Tags that don't parse as a version are skipped rather
    than crashing the comparison; if none parse, falls back to the first
    entry rather than returning nothing for what's still a real list.
    """
    versioned = []
    for release in releases:
        try:
            versioned.append((Version(release["tag_name"].removeprefix("v")), release))
        except InvalidVersion:
            continue
    if not versioned:
        return releases[0]
    return max(versioned, key=lambda pair: pair[0])[1]


def get_latest_release(include_prerelease: bool = False) -> ReleaseInfo | None:
    """None means no release has been published yet (a real, expected
    state right now — see docs/releasing.md), not an error.

    include_prerelease=True is Settings > App Updates' opt-in beta-testing
    toggle (settings.load_include_prerelease_updates()) -- it switches
    from GitHub's /releases/latest (which never returns a pre-release) to
    the plain releases list, picking the highest-versioned entry there
    (see _newest_release) rather than assuming it's the first one.
    """
    if include_prerelease:
        response = requests.get(_RELEASES_LIST_URL, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        releases = response.json()
        if not releases:
            return None
        data = _newest_release(releases)
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
    dmg_assets = [asset for asset in data.get("assets", []) if asset["name"].endswith(".dmg")]
    # The .dmg is arm64-only today (packaging/macos/build.sh); preferring an
    # explicitly "-arm64" one keeps this right if other architectures ever
    # get their own .dmg alongside it.
    macos_dmg = next(
        (asset for asset in dmg_assets if asset["name"].endswith("-arm64.dmg")),
        dmg_assets[0] if dmg_assets else None,
    )
    return ReleaseInfo(
        version=version,
        html_url=data["html_url"],
        windows_installer_url=windows_installer_url,
        macos_dmg_url=macos_dmg["browser_download_url"] if macos_dmg else None,
    )


def _download(url: str, suffix: str, on_progress: Callable[[int, int], None] | None) -> Path:
    """Streams url to a new temp file and returns its path -- see
    download_and_install_windows_update's docstring for on_progress's
    contract."""
    with requests.get(url, timeout=_DOWNLOAD_TIMEOUT_SEC, stream=True) as response:
        response.raise_for_status()
        # Only created once the response is confirmed good -- a failed
        # request (404, network error) shouldn't leak an empty temp file.
        fd, path_str = tempfile.mkstemp(suffix=suffix)
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with os.fdopen(fd, "wb") as f:
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)
    return Path(path_str)


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
    installer_path = _download(installer_url, ".exe", on_progress)

    # Not cleaned up afterward -- this process doesn't wait around to
    # learn when the installer is done with it, and Windows won't allow
    # deleting a file a running process still has open anyway. Left for
    # Windows' own temp-directory cleanup.
    #
    # /SILENT, not /VERYSILENT: both skip the wizard and require no
    # interaction (/SUPPRESSMSGBOXES still suppresses any error message
    # boxes), but /SILENT still shows Inno's own small installation
    # progress window. Without it there was a stretch with literally no
    # IT Toolbox window at all -- this one already quit, the new one
    # hasn't launched yet -- where a real hang was indistinguishable from
    # normal progress. /SILENT's progress window closes that gap for
    # free, without this process needing to stick around to show
    # anything itself (which is exactly what it can't safely do -- see
    # this function's own docstring for why).
    try:
        subprocess.Popen([str(installer_path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    except OSError as e:
        raise UpdateInstallError(f"Failed to launch installer at {installer_path}: {e}") from e


def running_app_bundle() -> Path | None:
    """The .app bundle this process runs from (packaging/macos/build.sh's
    IT Toolbox.app), or None for a source/pip install -- only a bundle can
    be replaced by download_and_install_macos_update."""
    for parent in Path(sys.executable).absolute().parents:
        if parent.suffix == ".app":
            return parent
    return None


def _macos_install_target(running_bundle: Path) -> Path:
    """Replaces the running bundle in place when its folder is writable
    (the normal drag-to-/Applications install); otherwise -- e.g. run
    straight off the mounted .dmg -- installs into /Applications, or
    ~/Applications for a user who can't write there."""
    if os.access(running_bundle.parent, os.W_OK):
        return running_bundle
    if os.access("/Applications", os.W_OK):
        return Path("/Applications") / running_bundle.name
    user_apps = Path.home() / "Applications"
    user_apps.mkdir(exist_ok=True)
    return user_apps / running_bundle.name


# Run detached by download_and_install_macos_update: waits for the app
# ($1 = its PID) to quit, swaps the staged bundle ($2) into place ($3),
# restoring the old one if the move fails, then relaunches whichever
# version ended up there and removes the staging dir ($4).
_MACOS_SWAP_SCRIPT = """
pid=$1 staged=$2 target=$3 workdir=$4
i=0
while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 120 ]; do sleep 0.5; i=$((i + 1)); done
rm -rf "$target.old"
if [ -e "$target" ] && ! mv "$target" "$target.old"; then
    open "$target"; rm -rf "$workdir"; exit 1
fi
if mv "$staged" "$target"; then
    rm -rf "$target.old"
else
    rm -rf "$target"
    [ -e "$target.old" ] && mv "$target.old" "$target"
fi
open "$target"
rm -rf "$workdir"
"""


def download_and_install_macos_update(
    dmg_url: str, on_progress: Callable[[int, int], None] | None = None
) -> None:
    """Downloads the macOS .dmg, copies the new IT Toolbox.app out of it
    into a staging dir, and hands off to a detached shell helper that
    replaces the running bundle once this process quits, then relaunches
    it -- macOS-only, and only from inside a bundle (the caller gates on
    running_app_bundle(), same convention as the Windows updater).

    Same shape as download_and_install_windows_update, for the same
    reason: this process's own interpreter and libraries live inside the
    bundle being replaced, so the helper (not this process) does the swap
    and the relaunch, and the caller quits right after this returns.

    No Gatekeeper prompt for the new version even though it's only
    ad-hoc signed: files fetched by requests carry no quarantine
    attribute, unlike a browser download.

    Raises UpdateInstallError if this isn't a bundle install, the .dmg
    can't be mounted or holds no .app, or the helper fails to start.
    """
    running_bundle = running_app_bundle()
    if running_bundle is None:
        raise UpdateInstallError("In-app updates are only available for the IT Toolbox.app install.")
    target = _macos_install_target(running_bundle)

    dmg_path = _download(dmg_url, ".dmg", on_progress)
    workdir = Path(tempfile.mkdtemp(prefix="it-toolbox-update-"))
    mountpoint = workdir / "mnt"
    try:
        subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mountpoint), str(dmg_path)],
            check=True,
            capture_output=True,
        )
        try:
            apps = sorted(mountpoint.glob("*.app"))
            if not apps:
                raise UpdateInstallError("The downloaded update doesn't contain an app bundle.")
            staged = workdir / apps[0].name
            # ditto, not shutil.copytree: preserves the bundle's symlinks,
            # extended attributes and code signatures exactly.
            subprocess.run(["ditto", str(apps[0]), str(staged)], check=True, capture_output=True)
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", str(mountpoint)], check=False, capture_output=True)
    except subprocess.CalledProcessError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        detail = (e.stderr or b"").decode(errors="replace").strip()
        raise UpdateInstallError(f"Failed to unpack the update: {detail or e}") from e
    except UpdateInstallError:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    finally:
        dmg_path.unlink(missing_ok=True)

    try:
        subprocess.Popen(
            ["/bin/sh", "-c", _MACOS_SWAP_SCRIPT, "it-toolbox-update", str(os.getpid()), str(staged), str(target), str(workdir)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise UpdateInstallError(f"Failed to start the update helper: {e}") from e


def is_update_available(installed_version: str, latest_version: str) -> bool:
    try:
        return Version(latest_version) > Version(installed_version)
    except InvalidVersion:
        # Unparseable version strings shouldn't crash the check — treat as
        # "can't tell, assume up to date" rather than surfacing an error for
        # what's ultimately just a version display comparison.
        return False

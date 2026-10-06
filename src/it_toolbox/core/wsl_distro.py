"""The app-managed WSL distro that hosts this app's Linux-only tools on
Windows (see docs/wsl-interconnect-plan.md).

The distro is named "it-toolbox", is imported from a rootfs tarball CI
builds (packaging/wsl/) and publishes as a GitHub release asset, and is
owned entirely by this app: users never pick a distro or install
packages into it. It holds no state the app can't regenerate (SSH
material is re-synced by sync_ssh_credentials), so updating to a newer
rootfs is just unregister + re-import.

Every read-only check here (status(), is_wsl_installed()) avoids
spawning wsl.exe -- it's called on the UI thread at startup, and on a
machine where WSL was never set up, wsl.exe is a System32 stub whose
side effect is starting Windows' "install WSL" flow (see
core/shell_discovery._wsl_has_registered_distros for the same concern).
Only the explicit Settings actions (install/update/remove) run it.
"""

import enum
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from it_toolbox.core import settings
from it_toolbox.core.subprocess_utils import no_window_kwargs
from it_toolbox.core.update_checker import REPO

DISTRO_NAME = "it-toolbox"

# Bump whenever core/linux_tools.TOOLS gains a package (or the base image
# needs refreshing), then tag `wsl-rootfs-<N>` so package-wsl.yml
# publishes the matching tarball. An app expecting a newer rootfs than the
# one installed reports OUTDATED and Settings offers "Update Linux tools".
ROOTFS_VERSION = 1

_RELEASE_TAG = f"wsl-rootfs-{ROOTFS_VERSION}"
ROOTFS_ASSET_NAME = f"it-toolbox-wsl-rootfs-{ROOTFS_VERSION}.tar.gz"
ROOTFS_URL = f"https://github.com/{REPO}/releases/download/{_RELEASE_TAG}/{ROOTFS_ASSET_NAME}"
ROOTFS_SHA256_URL = f"{ROOTFS_URL}.sha256"

_DOWNLOAD_TIMEOUT_SEC = 60
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_WSL_COMMAND_TIMEOUT_SEC = 300  # --import of a ~150 MB tarball is not instant
_LXSS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Lxss"

# SSH material copied into the distro. Deliberately not ~/.ssh/config:
# it's free to contain Windows paths (IdentityFile C:\...) that mean
# nothing inside the distro.
_SSH_FILE_PREFIXES = ("id_",)
_SSH_FILE_NAMES = ("known_hosts",)


class WslDistroError(Exception):
    pass


class DistroState(enum.Enum):
    UNSUPPORTED = "unsupported"  # not Windows -- Linux tools run natively
    NO_WSL = "no_wsl"  # WSL itself isn't installed
    NOT_INSTALLED = "not_installed"  # WSL is, the it-toolbox distro isn't
    OUTDATED = "outdated"  # installed, but an older rootfs than this app expects
    READY = "ready"


@dataclass(frozen=True)
class DistroStatus:
    state: DistroState
    installed_version: int | None = None

    @property
    def ready(self) -> bool:
        return self.state is DistroState.READY


def install_dir() -> Path:
    """Where the distro's virtual disk lives. A subdirectory of data_dir()
    on purpose: core/config_backup.py only backs up data_dir()'s flat
    files, so a multi-GB ext4.vhdx never ends up in a config backup."""
    return settings.data_dir() / "wsl"


def _version_marker() -> Path:
    return install_dir() / "rootfs-version"


def wsl_exe() -> str:
    """Prefer the Store-delivered WSL over the System32 inbox stub when
    both exist -- the inbox one is what triggers the install flow."""
    modern = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WSL" / "wsl.exe"
    if modern.is_file():
        return str(modern)
    return shutil.which("wsl.exe") or "wsl.exe"


def wsl_env() -> dict[str, str]:
    """wsl.exe's *own* messages (not a Linux program's output) are UTF-16
    when piped; WSL_UTF8=1 switches them to UTF-8 on any WSL new enough
    to matter here."""
    return {**os.environ, "WSL_UTF8": "1"}


def clean_wsl_output(text: str) -> str:
    """Belt and braces for an older wsl.exe ignoring WSL_UTF8: UTF-16LE
    decoded as UTF-8 is the real text with a NUL after every ASCII char."""
    return text.replace("\x00", "").replace("\ufeff", "").strip()


def _registered_distro_names() -> list[str]:
    try:
        import winreg
    except ImportError:
        return []
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _LXSS_KEY) as key:
            index = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(key, sub_name) as sub:
                        name, _ = winreg.QueryValueEx(sub, "DistributionName")
                        names.append(name)
                except OSError:
                    continue
    except OSError:
        return []
    return names


def is_wsl_installed() -> bool:
    """No process spawned -- see this module's docstring. True if the
    Store-delivered WSL package is present, or any distro is already
    registered (which can't happen without a working WSL)."""
    if sys.platform != "win32":
        return False
    modern = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WSL" / "wsl.exe"
    return modern.is_file() or bool(_registered_distro_names())


def is_distro_registered() -> bool:
    return DISTRO_NAME in _registered_distro_names()


def installed_rootfs_version() -> int | None:
    try:
        return int(_version_marker().read_text().strip())
    except (OSError, ValueError):
        return None


def status() -> DistroStatus:
    if sys.platform != "win32":
        return DistroStatus(DistroState.UNSUPPORTED)
    if not is_wsl_installed():
        return DistroStatus(DistroState.NO_WSL)
    if not is_distro_registered():
        return DistroStatus(DistroState.NOT_INSTALLED)
    version = installed_rootfs_version()
    if version is None or version < ROOTFS_VERSION:
        return DistroStatus(DistroState.OUTDATED, version)
    return DistroStatus(DistroState.READY, version)


# --- Settings actions (explicit user clicks only) --------------------------


def _run_wsl(*args: str, timeout: float = _WSL_COMMAND_TIMEOUT_SEC) -> str:
    try:
        result = subprocess.run(
            [wsl_exe(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=wsl_env(),
            **no_window_kwargs(),
        )
    except FileNotFoundError as e:
        raise WslDistroError("wsl.exe not found — is WSL installed?") from e
    except subprocess.TimeoutExpired as e:
        raise WslDistroError(f"wsl {' '.join(args[:1])} timed out") from e
    if result.returncode != 0:
        message = clean_wsl_output(result.stderr) or clean_wsl_output(result.stdout)
        raise WslDistroError(message or f"wsl {' '.join(args[:1])} failed")
    return clean_wsl_output(result.stdout)


def start_wsl_install() -> None:
    """Kicks off `wsl --install --no-distribution` in its own console.
    It asks for elevation itself and usually needs a reboot, so this
    doesn't wait for it -- Settings tells the user to restart afterwards.
    """
    try:
        subprocess.Popen(
            [wsl_exe(), "--install", "--no-distribution"],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except OSError as e:
        raise WslDistroError(f"Couldn't start the WSL installer: {e}") from e


def _download(url: str, dest: Path, on_progress: Callable[[int, int], None] | None) -> None:
    with requests.get(url, timeout=_DOWNLOAD_TIMEOUT_SEC, stream=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with dest.open("wb") as f:
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)


def _expected_sha256() -> str:
    response = requests.get(ROOTFS_SHA256_URL, timeout=_DOWNLOAD_TIMEOUT_SEC)
    response.raise_for_status()
    # `sha256sum` format: "<hex>  <filename>"
    digest = response.text.split()[0].lower() if response.text.split() else ""
    if len(digest) != 64:
        raise WslDistroError("The rootfs checksum file is malformed.")
    return digest


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_DOWNLOAD_CHUNK_SIZE), b""):
            h.update(block)
    return h.hexdigest()


def install(on_progress: Callable[[int, int], None] | None = None) -> None:
    """Downloads, verifies and imports the rootfs this app version
    expects, replacing any older it-toolbox distro. Runs on a background
    thread (Settings' run_in_background); on_progress follows
    update_checker.download_and_install_windows_update's contract.
    """
    if sys.platform != "win32":
        raise WslDistroError("The managed Linux tools distro is Windows-only.")
    target = install_dir()
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        expected = _expected_sha256()
    except requests.RequestException as e:
        raise WslDistroError(f"Couldn't fetch the rootfs checksum: {e}") from e

    fd, tarball_str = tempfile.mkstemp(suffix=".tar.gz", dir=target.parent)
    os.close(fd)
    tarball = Path(tarball_str)
    try:
        try:
            _download(ROOTFS_URL, tarball, on_progress)
        except requests.RequestException as e:
            raise WslDistroError(f"Couldn't download the Linux tools rootfs: {e}") from e
        if _sha256_of(tarball) != expected:
            raise WslDistroError("The downloaded rootfs failed its checksum — not installing it.")

        if is_distro_registered():
            _run_wsl("--unregister", DISTRO_NAME)
        target.mkdir(parents=True, exist_ok=True)
        _run_wsl("--import", DISTRO_NAME, str(target), str(tarball), "--version", "2")
        _version_marker().write_text(str(ROOTFS_VERSION))
    finally:
        tarball.unlink(missing_ok=True)


def remove() -> None:
    if is_distro_registered():
        _run_wsl("--unregister", DISTRO_NAME)
    shutil.rmtree(install_dir(), ignore_errors=True)


def windows_ssh_dir() -> Path:
    return Path.home() / ".ssh"


def _ssh_files_to_sync(ssh_dir: Path) -> list[Path]:
    if not ssh_dir.is_dir():
        return []
    return sorted(
        p
        for p in ssh_dir.iterdir()
        if p.is_file() and (p.name.startswith(_SSH_FILE_PREFIXES) or p.name in _SSH_FILE_NAMES)
    )


_WRITE_SSH_FILE_SCRIPT = (
    'umask 077 && mkdir -p "$HOME/.ssh" && cat > "$HOME/.ssh/$1" && chmod 600 "$HOME/.ssh/$1"'
)


def sync_ssh_credentials(backend, ssh_dir: Path | None = None) -> int:
    """Copies the Windows user's SSH keys and known_hosts into the
    distro's ~/.ssh with 0600 perms, so `virsh -c qemu+ssh://` and the
    SPICE helper's tunnel authenticate exactly as the Windows side would.
    Pointing at /mnt/c/... directly doesn't work: DrvFs presents those
    files as 0777, which ssh refuses for a private key. Returns how many
    files were copied. `backend` is a core.linux_backend.WslBackend.
    """
    copied = 0
    for path in _ssh_files_to_sync(ssh_dir or windows_ssh_dir()):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        result = backend.run(
            ["sh", "-c", _WRITE_SSH_FILE_SCRIPT, "sh", path.name], timeout=30, input=content
        )
        if result.returncode != 0:
            raise WslDistroError(f"Couldn't copy {path.name} into the Linux tools distro: {result.stderr.strip()}")
        copied += 1
    return copied

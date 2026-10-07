"""Mounts rclone remotes as local folders (Linux/macOS) or drive letters
(Windows) via `rclone mount`.

Each mount is a long-running foreground `rclone mount` child process
owned by this app rather than `--daemon` (which rclone doesn't support
on Windows): unmounting means stopping that process, which rclone
handles by cleanly unmounting first. Mounts don't outlive the app — the
Cloud Storage view unmounts everything on quit.

Pending uploads: with `--vfs-cache-mode writes`, a saved file is
uploaded in the background *after* it's closed, and stopping rclone
mid-upload aborts it (confirmed live — the upload resumes only on the
next mount of that remote). So each mount also serves rclone's remote
control API on a random localhost port, guarded by a per-mount random
password passed via environment (not argv, which other local users can
read), and unmount() waits for in-flight transfers to drain first.

`rclone mount` needs a FUSE layer the OS doesn't always ship: FUSE
(fusermount) on Linux, macFUSE or FUSE-T on macOS, WinFsp on Windows.
mount_support_problem() checks for it up front so a missing layer is a
clear message, not an opaque rclone error.
"""

import os
import secrets
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from it_toolbox.core import rclone_client
from it_toolbox.core.subprocess_utils import no_window_kwargs

MOUNT_ROOT_DIRNAME = "CloudMounts"
# How long to wait for a freshly started `rclone mount` to either show
# up as a mount or exit with an error.
MOUNT_START_TIMEOUT_SEC = 20
UNMOUNT_TIMEOUT_SEC = 10
# How long unmount() waits for pending uploads before stopping rclone
# anyway (the upload then resumes on the next mount of that remote).
UPLOAD_DRAIN_TIMEOUT_SEC = 30 * 60
QUIT_UPLOAD_DRAIN_TIMEOUT_SEC = 60
_RC_USER = "it-toolbox"
_RC_TIMEOUT_SEC = 5
_POLL_INTERVAL_SEC = 0.25

FUSE_INSTALL_HINTS = {
    "linux": (
        "Mounting needs FUSE, which isn't installed. Install the fuse3 package "
        "(e.g. `sudo dnf install fuse3` or `sudo apt install fuse3`) and try again."
    ),
    "darwin": (
        "Mounting needs macFUSE or FUSE-T, and neither is installed. Install one "
        "from https://macfuse.github.io or https://www.fuse-t.org and try again."
    ),
    "win32": (
        "Mounting needs WinFsp, which isn't installed. Install it from "
        "https://winfsp.dev/rel/ and try again."
    ),
}

_MACOS_FUSE_PATHS = (
    "/Library/Filesystems/macfuse.fs",
    "/Library/Filesystems/osxfuse.fs",
    "/usr/local/lib/libfuse-t.dylib",
    "/Library/Application Support/fuse-t",
)


class MountError(Exception):
    pass


def _windows_has_winfsp() -> bool:
    for env_var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env_var)
        if base and (Path(base) / "WinFsp" / "bin").is_dir():
            return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\WinFsp") as key:
            install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
            return Path(install_dir).is_dir()
    except (ImportError, OSError):
        return False


def mount_support_problem() -> str | None:
    """A user-facing explanation of why mounting can't work on this
    machine (missing FUSE layer, unsupported OS), or None if it can.
    """
    if sys.platform.startswith("linux"):
        if shutil.which("fusermount3") or shutil.which("fusermount"):
            return None
        return FUSE_INSTALL_HINTS["linux"]
    if sys.platform == "darwin":
        if any(Path(p).exists() for p in _MACOS_FUSE_PATHS):
            return None
        return FUSE_INSTALL_HINTS["darwin"]
    if sys.platform == "win32":
        return None if _windows_has_winfsp() else FUSE_INSTALL_HINTS["win32"]
    return f"Mounting isn't supported on {sys.platform}."


def free_drive_letter() -> str | None:
    """The last unused drive letter (Z: first, working backwards — the
    usual convention for network-style mounts), or None if all are taken.
    """
    for letter in reversed(string.ascii_uppercase[3:]):  # skip A:-C:
        if not os.path.exists(f"{letter}:\\"):
            return f"{letter}:"
    return None


def default_mount_point(remote_name: str) -> str:
    """Where `remote_name` gets mounted: a free drive letter on Windows,
    else ~/CloudMounts/<remote_name>.
    """
    if sys.platform == "win32":
        letter = free_drive_letter()
        if letter is None:
            raise MountError("No free drive letter to mount on.")
        return letter
    return str(Path.home() / MOUNT_ROOT_DIRNAME / remote_name)


def _is_mounted(mount_point: str) -> bool:
    if sys.platform == "win32":
        return os.path.exists(mount_point + "\\")
    return os.path.ismount(mount_point)


@dataclass
class Mount:
    remote_name: str
    mount_point: str
    process: subprocess.Popen
    log_path: str
    rc_port: int = 0
    rc_password: str = ""
    _log_file: object = field(repr=False, default=None)

    def read_log(self) -> str:
        try:
            return Path(self.log_path).read_text(errors="replace").strip()
        except OSError:
            return ""

    def pending_transfers(self) -> int:
        """In-flight/queued uploads (plus any transfers still running),
        via rclone's remote control API. 0 if it can't be reached.
        """
        auth = (_RC_USER, self.rc_password)
        base = f"http://127.0.0.1:{self.rc_port}"
        try:
            core = requests.post(f"{base}/core/stats", auth=auth, timeout=_RC_TIMEOUT_SEC)
            vfs = requests.post(f"{base}/vfs/stats", auth=auth, timeout=_RC_TIMEOUT_SEC)
            core.raise_for_status()
            vfs.raise_for_status()
            disk_cache = vfs.json().get("diskCache") or {}
            return (
                len(core.json().get("transferring") or [])
                + int(disk_cache.get("uploadsInProgress", 0))
                + int(disk_cache.get("uploadsQueued", 0))
            )
        except (requests.RequestException, ValueError):
            return 0

    def close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        try:
            os.unlink(self.log_path)
        except OSError:
            pass


class MountManager:
    """Tracks the `rclone mount` processes this app started, keyed by
    remote name. mount()/unmount() block (polling for the mount to come
    up or go away), so call them off the UI thread.
    """

    def __init__(self) -> None:
        self._mounts: dict[str, Mount] = {}

    def has_pending_uploads(self, remote_name: str) -> bool:
        mount = self._mounts.get(remote_name)
        return mount is not None and mount.pending_transfers() > 0

    def mount_point(self, remote_name: str) -> str | None:
        mount = self._mounts.get(remote_name)
        if mount is not None and mount.process.poll() is not None:
            # rclone died on its own (e.g. network failure, external unmount).
            mount.close_log()
            del self._mounts[remote_name]
            return None
        return mount.mount_point if mount is not None else None

    def is_mounted(self, remote_name: str) -> bool:
        return self.mount_point(remote_name) is not None

    def mounted_remotes(self) -> list[str]:
        return [name for name in list(self._mounts) if self.is_mounted(name)]

    def mount(self, remote_name: str, mount_point: str | None = None) -> str:
        if self.is_mounted(remote_name):
            return self._mounts[remote_name].mount_point
        if not rclone_client.is_available():
            raise MountError(f"rclone CLI not found. Install it from {rclone_client.INSTALL_URL}.")
        problem = mount_support_problem()
        if problem is not None:
            raise MountError(problem)

        target = mount_point or default_mount_point(remote_name)
        if sys.platform != "win32":
            # rclone needs an existing, empty directory on Linux/macOS.
            Path(target).mkdir(parents=True, exist_ok=True)
            if _is_mounted(target):
                raise MountError(f"{target} is already a mount point.")
            if any(Path(target).iterdir()):
                raise MountError(f"{target} isn't empty, so it can't be used as a mount point.")

        rc_port = _free_local_port()
        rc_password = secrets.token_urlsafe(24)
        log_fd, log_path = tempfile.mkstemp(prefix=f"rclone-mount-{remote_name}-", suffix=".log")
        log_file = os.fdopen(log_fd, "w")
        process = subprocess.Popen(
            [
                rclone_client.rclone_executable(),
                "mount",
                f"{remote_name}:",
                target,
                # Lets ordinary apps write/edit files in place, which a
                # bare mount (no cache) mostly can't.
                "--vfs-cache-mode",
                "writes",
                # Start uploading as soon as a file is closed, rather than
                # rclone's default 5s delay, so unmount waits less.
                "--vfs-write-back",
                "0s",
                "--rc",
                "--rc-addr",
                f"127.0.0.1:{rc_port}",
            ],
            env={**os.environ, "RCLONE_RC_USER": _RC_USER, "RCLONE_RC_PASS": rc_password},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log_file,
            **no_window_kwargs(),
        )
        mount = Mount(remote_name, target, process, log_path, rc_port, rc_password, log_file)

        deadline = time.monotonic() + MOUNT_START_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if process.poll() is not None:
                message = mount.read_log() or f"rclone mount exited with code {process.returncode}"
                mount.close_log()
                raise MountError(message)
            if _is_mounted(target):
                self._mounts[remote_name] = mount
                return target
            time.sleep(_POLL_INTERVAL_SEC)

        _stop(process)
        message = mount.read_log()
        mount.close_log()
        raise MountError(
            f"Timed out waiting for {remote_name} to mount at {target}."
            + (f"\n\n{message}" if message else "")
        )

    def unmount(self, remote_name: str, upload_timeout: float = UPLOAD_DRAIN_TIMEOUT_SEC) -> None:
        mount = self._mounts.get(remote_name)
        if mount is None:
            return
        deadline = time.monotonic() + upload_timeout
        while (
            time.monotonic() < deadline
            and mount.process.poll() is None
            and mount.pending_transfers() > 0
        ):
            time.sleep(1)
        self._mounts.pop(remote_name, None)
        _stop(mount.process)
        mount.close_log()
        if sys.platform != "win32" and _is_mounted(mount.mount_point):
            # rclone was killed before it could unmount — clean up the
            # stale FUSE mount so the folder is usable again.
            _force_unmount(mount.mount_point)

    def unmount_all(self) -> None:
        for name in list(self._mounts):
            self.unmount(name, upload_timeout=QUIT_UPLOAD_DRAIN_TIMEOUT_SEC)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    # SIGTERM on Linux/macOS: rclone unmounts cleanly, then exits. On
    # Windows this is TerminateProcess, and WinFsp drops the drive letter
    # when its owning process goes away.
    process.terminate()
    try:
        process.wait(timeout=UNMOUNT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=UNMOUNT_TIMEOUT_SEC)


def _force_unmount(mount_point: str) -> None:
    candidates = (
        [["fusermount3", "-uz", mount_point], ["fusermount", "-uz", mount_point]]
        if sys.platform.startswith("linux")
        else [["umount", mount_point], ["diskutil", "unmount", "force", mount_point]]
    )
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        result = subprocess.run(cmd, capture_output=True, timeout=UNMOUNT_TIMEOUT_SEC)
        if result.returncode == 0:
            return


manager = MountManager()

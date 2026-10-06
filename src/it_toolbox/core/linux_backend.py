"""Where this app's Linux-only tools actually run.

On Linux (and macOS, for whatever Homebrew provides) that's this machine,
exactly as before this module existed (NativeBackend). On Windows it's
the app-managed WSL distro (WslBackend, see core/wsl_distro.py and
docs/wsl-interconnect-plan.md): every call becomes
`wsl.exe -d it-toolbox --exec <argv>`, so callers like
qemu_client.run_virsh don't need to know which side of the boundary
they're on.

`--exec` rather than a shell string, so VM names and libvirt URIs are
passed through as separate argv entries and never need quoting.
"""

import shutil
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import PureWindowsPath
from typing import Protocol

from it_toolbox.core import linux_tools, wsl_distro
from it_toolbox.core.subprocess_utils import no_window_kwargs

# A stopped WSL distro takes a few seconds to boot on its first call --
# long enough to blow through callers' normal timeouts (virsh's is 8s).
# Until one call has succeeded, every call gets at least this long.
_WSL_BOOT_TIMEOUT_SEC = 45


class LinuxBackend(Protocol):
    kind: str

    def run(
        self, argv: Sequence[str], *, timeout: float, input: str | None = None
    ) -> subprocess.CompletedProcess[str]: ...

    def is_tool_available(self, tool: linux_tools.LinuxTool) -> bool: ...

    def popen_argv(self, argv: Sequence[str]) -> list[str]: ...

    def popen_kwargs(self) -> dict: ...

    def to_linux_path(self, path: str) -> str: ...


class NativeBackend:
    kind = "native"

    def run(
        self, argv: Sequence[str], *, timeout: float, input: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        # Same subprocess.run shape callers used directly before this
        # module existed -- their tests monkeypatch subprocess.run and
        # assert on exactly these keyword arguments.
        extra = no_window_kwargs()
        if input is not None:
            extra["input"] = input
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, **extra)

    def is_tool_available(self, tool: linux_tools.LinuxTool) -> bool:
        return shutil.which(tool.binary) is not None

    def popen_argv(self, argv: Sequence[str]) -> list[str]:
        return list(argv)

    def popen_kwargs(self) -> dict:
        return no_window_kwargs()

    def to_linux_path(self, path: str) -> str:
        return path


class WslBackend:
    kind = "wsl"

    def __init__(self, distro: str = wsl_distro.DISTRO_NAME) -> None:
        self.distro = distro
        self._booted = False
        self._lock = threading.Lock()

    def popen_argv(self, argv: Sequence[str]) -> list[str]:
        return [wsl_distro.wsl_exe(), "-d", self.distro, "--exec", *argv]

    def popen_kwargs(self) -> dict:
        # No console window flashing up behind a GUI-subsystem app.
        return {"env": wsl_distro.wsl_env(), **no_window_kwargs()}

    def run(
        self, argv: Sequence[str], *, timeout: float, input: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        with self._lock:
            booted = self._booted
        result = subprocess.run(
            self.popen_argv(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout if booted else max(timeout, _WSL_BOOT_TIMEOUT_SEC),
            input=input,
            **self.popen_kwargs(),
        )
        with self._lock:
            self._booted = True
        # A Linux program's own output passes through untouched (UTF-8),
        # but wsl.exe's *own* errors (e.g. "command not found" for a
        # missing binary under --exec) may still be UTF-16 on an older WSL.
        result.stderr = wsl_distro.clean_wsl_output(result.stderr) if "\x00" in result.stderr else result.stderr
        return result

    def warm_up(self) -> None:
        """Boots the distro ahead of the first real call -- meant for a
        background thread at startup, so the first QEMU tree expansion
        doesn't pay the boot cost."""
        try:
            self.run(["true"], timeout=_WSL_BOOT_TIMEOUT_SEC)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def is_tool_available(self, tool: linux_tools.LinuxTool) -> bool:
        """No process spawned: get_backend() only hands out a WslBackend
        for a distro at exactly this app's ROOTFS_VERSION, which by
        construction contains every registry tool (packaging/wsl/ builds
        it from linux_tools.all_packages()). probe_tool() is the real,
        process-spawning check, for Settings' "Check" button."""
        return True

    def probe_tool(self, tool: linux_tools.LinuxTool) -> bool:
        argv = tool.probe or ("sh", "-c", 'command -v "$1" >/dev/null', "sh", tool.binary)
        try:
            return self.run(argv, timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def to_linux_path(self, path: str) -> str:
        return windows_to_wsl_path(path)


def windows_to_wsl_path(path: str) -> str:
    r"""C:\Users\me\x.xml -> /mnt/c/Users/me/x.xml, matching WSL's default
    DrvFs automount root (packaging/wsl/wsl.conf leaves it at /mnt/).
    Pure string translation rather than spawning `wslpath` per call."""
    p = PureWindowsPath(path)
    if not p.drive or not p.drive.endswith(":"):
        raise ValueError(f"Can't map {path!r} into WSL: only drive-letter paths are supported")
    drive = p.drive[0].lower()
    rest = "/".join(p.parts[1:])
    return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"


_UNSET = object()
_backend: object = _UNSET
_backend_lock = threading.Lock()


def get_backend() -> LinuxBackend | None:
    """The backend Linux tools run through, or None when there isn't one
    (Windows without the managed distro installed and current) -- callers
    treat None exactly like "virsh isn't installed" today: the feature is
    hidden. Cached; call reset_backend() after installing/removing the
    distro."""
    global _backend
    with _backend_lock:
        if _backend is _UNSET:
            if sys.platform != "win32":
                _backend = NativeBackend()
            elif wsl_distro.status().ready:
                _backend = WslBackend()
            else:
                _backend = None
        return _backend  # type: ignore[return-value]


def reset_backend() -> None:
    global _backend
    with _backend_lock:
        _backend = _UNSET


def is_tool_available(tool_id: str) -> bool:
    backend = get_backend()
    return backend is not None and backend.is_tool_available(linux_tools.get(tool_id))


def is_wsl() -> bool:
    backend = get_backend()
    return backend is not None and backend.kind == "wsl"

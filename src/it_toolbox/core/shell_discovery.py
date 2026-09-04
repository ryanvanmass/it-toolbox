"""Discovers shells installed on the local machine — the data source for
the Shell Launcher module. Qt-free, platform-branched the same way
core/session_launcher.py is, and independently testable/runnable without
any UI.
"""

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_POSIX_SHELLS_PATH = Path("/etc/shells")

# Supplements /etc/shells for shells installed but not registered there
# (e.g. a user-local install, or a distro that doesn't maintain the file).
_SUPPLEMENTAL_POSIX_SHELL_NAMES = ("bash", "zsh", "fish", "pwsh", "nu", "dash", "tcsh", "ksh")

_WSL_TIMEOUT_SEC = 5


@dataclass(frozen=True)
class Shell:
    name: str  # display name, e.g. "bash", "PowerShell 7", "WSL: Ubuntu"
    argv: tuple[str, ...]  # full spawn command, e.g. ("/bin/bash",) or ("wsl.exe", "-d", "Ubuntu")


def discover_shells() -> list[Shell]:
    if platform.system() == "Windows":
        return _discover_windows_shells()
    return _discover_posix_shells()


def _discover_posix_shells() -> list[Shell]:
    shells: list[Shell] = []
    seen_paths: set[str] = set()

    def _add(path: str) -> None:
        resolved = str(Path(path).resolve())
        if resolved in seen_paths:
            return
        seen_paths.add(resolved)
        shells.append(Shell(name=Path(resolved).name, argv=(resolved,)))

    if _POSIX_SHELLS_PATH.is_file():
        for line in _POSIX_SHELLS_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if Path(line).is_file() and os.access(line, os.X_OK):
                _add(line)

    for name in _SUPPLEMENTAL_POSIX_SHELL_NAMES:
        path = shutil.which(name)
        if path:
            _add(path)

    return sorted(shells, key=lambda s: s.name.lower())


def _discover_windows_shells() -> list[Shell]:
    shells: list[Shell] = [
        Shell(name="Command Prompt", argv=("cmd.exe",)),
        Shell(name="Windows PowerShell", argv=("powershell.exe",)),
    ]

    pwsh = shutil.which("pwsh")
    if pwsh:
        shells.append(Shell(name="PowerShell 7", argv=(pwsh,)))

    git_bash = _find_git_bash()
    if git_bash:
        shells.append(Shell(name="Git Bash", argv=(git_bash,)))

    shells.extend(_discover_wsl_distros())
    return shells


def _find_git_bash() -> str | None:
    on_path = shutil.which("bash")
    if on_path and "git" in on_path.lower():
        return on_path
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _discover_wsl_distros() -> list[Shell]:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return []

    try:
        result = subprocess.run(
            [wsl, "-l", "-q"], capture_output=True, timeout=_WSL_TIMEOUT_SEC
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    # `wsl -l -q` writes UTF-16LE (with embedded null bytes and often a
    # leading BOM) when its stdout isn't a real console, which is always
    # true here (a Python subprocess pipe) — decoding as UTF-8 or ASCII
    # leaves interleaved nulls in every distro name. utf-16-le sometimes
    # still leaves a BOM character at the start, so strip that too.
    try:
        raw = result.stdout.decode("utf-16-le")
    except UnicodeDecodeError:
        raw = result.stdout.decode("utf-8", errors="ignore")
    raw = raw.lstrip("\ufeff")

    distros = [line.strip() for line in raw.splitlines() if line.strip()]
    return [Shell(name=f"WSL: {distro}", argv=(wsl, "-d", distro)) for distro in distros]

"""Per-OS handoff from a local tunnel port to a real RDP/SSH client.

Deliberately spawns separate top-level processes/windows rather than trying
to embed mstsc/xfreerdp/a terminal inside the app — cross-platform window
embedding of foreign GUI apps is unreliable.
"""

import os
import platform
import shlex
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

RDP_INSTALL_HINT = (
    "FreeRDP not found. Install it (e.g. 'sudo apt install freerdp3-x11', or your "
    "distro's freerdp package) to connect via RDP on Linux."
)

MACOS_RDP_INSTALL_HINT = (
    "No RDP client found. Install Microsoft's \"Windows App\" from the App Store, "
    "or FreeRDP via Homebrew ('brew install freerdp'), to connect via RDP on macOS."
)

# macOS RDP clients that register for .rdp files, opened by name with
# `open -a` rather than trusting whatever the default .rdp handler is (which
# may be nothing, or a text editor). "Windows App" is the 2024 rename of
# "Microsoft Remote Desktop"; both are still in the wild.
_MACOS_RDP_APPS = ("Windows App", "Microsoft Remote Desktop")
_MACOS_APP_DIRS = ("/Applications", os.path.expanduser("~/Applications"))

# Homebrew's bin dirs (Apple Silicon, then Intel) -- an app launched from
# Finder/the Dock doesn't inherit a login shell's PATH, so shutil.which()
# alone wouldn't find a Homebrew-installed FreeRDP.
_HOMEBREW_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")


class SessionLaunchError(Exception):
    """Raised when there's no way to launch the requested session on this OS."""


def launch_rdp(host: str, port: int, username: str | None = None) -> None:
    system = platform.system()
    if system == "Windows":
        _launch_rdp_windows(host, port, username)
    elif system == "Linux":
        _launch_rdp_linux(host, port, username)
    elif system == "Darwin":
        _launch_rdp_macos(host, port, username)
    else:
        raise SessionLaunchError(f"RDP is not supported on {system} yet.")


def launch_ssh(host: str, port: int, username: str | None = None) -> None:
    target = f"{username}@{host}" if username else host
    ssh_cmd = ["ssh", "-p", str(port), target]

    system = platform.system()
    if system == "Windows":
        _spawn_in_windows_terminal(ssh_cmd)
    elif system == "Darwin":
        _spawn_in_macos_terminal(ssh_cmd)
    else:
        _spawn_in_linux_terminal(ssh_cmd)


# -- RDP --------------------------------------------------------------------


def _write_rdp_file(host: str, port: int, username: str | None) -> str:
    """Writes a temp .rdp file for mstsc/Windows App and schedules its
    deletion; returns its path."""
    lines = [
        "screen mode id:i:2",
        "use multimon:i:0",
        f"full address:s:{host}:{port}",
        "audiomode:i:0",
        "redirectclipboard:i:1",
    ]
    if username:
        lines.append(f"username:s:{username}")

    fd, path = tempfile.mkstemp(suffix=".rdp", prefix="it-toolbox-")
    with open(fd, "w") as f:
        f.write("\n".join(lines) + "\n")

    # The client reads the file at startup (well under a second in practice),
    # so deleting it immediately risks a race — instead delete it shortly
    # after on a timer rather than leaving it behind indefinitely.
    threading.Timer(15.0, lambda: Path(path).unlink(missing_ok=True)).start()
    return path


def _launch_rdp_windows(host: str, port: int, username: str | None) -> None:
    subprocess.Popen(["mstsc.exe", _write_rdp_file(host, port, username)])


def _launch_rdp_linux(host: str, port: int, username: str | None) -> None:
    xfreerdp = shutil.which("xfreerdp3") or shutil.which("xfreerdp")
    if not xfreerdp:
        raise SessionLaunchError(RDP_INSTALL_HINT)

    args = [xfreerdp, f"/v:{host}:{port}", "/cert:ignore", "/dynamic-resolution"]
    if username:
        args.append(f"/u:{username}")
    subprocess.Popen(args)


def _launch_rdp_macos(host: str, port: int, username: str | None) -> None:
    for app in _MACOS_RDP_APPS:
        if any(Path(d, f"{app}.app").is_dir() for d in _MACOS_APP_DIRS):
            subprocess.Popen(["open", "-a", app, _write_rdp_file(host, port, username)])
            return

    # Homebrew's FreeRDP 3 ships sdl-freerdp (native Cocoa via SDL);
    # xfreerdp only works with XQuartz running, so it's the last resort.
    freerdp = _which_homebrew("sdl-freerdp3", "sdl-freerdp", "xfreerdp3", "xfreerdp")
    if not freerdp:
        raise SessionLaunchError(MACOS_RDP_INSTALL_HINT)

    args = [freerdp, f"/v:{host}:{port}", "/cert:ignore", "/dynamic-resolution"]
    if username:
        args.append(f"/u:{username}")
    subprocess.Popen(args)


def _which_homebrew(*names: str) -> str | None:
    search_path = os.pathsep.join([*_HOMEBREW_BIN_DIRS, os.environ.get("PATH", "")])
    for name in names:
        found = shutil.which(name, path=search_path)
        if found:
            return found
    return None


# -- SSH terminal spawning ----------------------------------------------


def _spawn_in_windows_terminal(argv: list[str]) -> None:
    wt = shutil.which("wt.exe") or shutil.which("wt")
    if wt:
        subprocess.Popen([wt, "--", *argv])
        return
    # Fallback: a plain cmd window that stays open after ssh exits.
    subprocess.Popen(["cmd.exe", "/c", "start", "IT Toolbox SSH", "cmd", "/k", *argv])


def _spawn_in_macos_terminal(argv: list[str]) -> None:
    # Terminal.app has no "run this argv" CLI; AppleScript's `do script` is
    # the supported way to open a new window running a command. The shell
    # command is shlex-quoted, then escaped again for the AppleScript string
    # literal it's embedded in.
    command = shlex.join(argv).replace("\\", "\\\\").replace('"', '\\"')
    subprocess.Popen(
        [
            "osascript",
            "-e",
            f'tell application "Terminal" to do script "{command}"',
            "-e",
            'tell application "Terminal" to activate',
        ]
    )


def _spawn_in_linux_terminal(argv: list[str]) -> None:
    x_terminal_emulator = shutil.which("x-terminal-emulator")
    if x_terminal_emulator:
        subprocess.Popen([x_terminal_emulator, "-e", *argv])
        return

    gnome_terminal = shutil.which("gnome-terminal")
    if gnome_terminal:
        subprocess.Popen([gnome_terminal, "--", *argv])
        return

    for candidate in ("konsole", "xterm"):
        path = shutil.which(candidate)
        if path:
            subprocess.Popen([path, "-e", *argv])
            return

    raise SessionLaunchError(
        "No terminal emulator found (tried gnome-terminal, konsole, xterm). "
        "Install one, or run manually: " + " ".join(argv)
    )

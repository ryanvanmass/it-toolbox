"""Per-OS handoff from a local tunnel port to a real RDP/SSH client.

Deliberately spawns separate top-level processes/windows rather than trying
to embed mstsc/xfreerdp/a terminal inside the app — cross-platform window
embedding of foreign GUI apps is unreliable.
"""

import platform
import shutil
import subprocess
import tempfile

RDP_INSTALL_HINT = (
    "FreeRDP not found. Install it (e.g. 'sudo apt install freerdp3-x11', or your "
    "distro's freerdp package) to connect via RDP on Linux."
)


class SessionLaunchError(Exception):
    """Raised when there's no way to launch the requested session on this OS."""


def launch_rdp(host: str, port: int, username: str | None = None) -> None:
    system = platform.system()
    if system == "Windows":
        _launch_rdp_windows(host, port, username)
    elif system == "Linux":
        _launch_rdp_linux(host, port, username)
    else:
        raise SessionLaunchError(f"RDP is not supported on {system} yet.")


def launch_ssh(host: str, port: int, username: str | None = None) -> None:
    target = f"{username}@{host}" if username else host
    ssh_cmd = ["ssh", "-p", str(port), target]

    if platform.system() == "Windows":
        _spawn_in_windows_terminal(ssh_cmd)
    else:
        _spawn_in_linux_terminal(ssh_cmd)


# -- RDP --------------------------------------------------------------------


def _launch_rdp_windows(host: str, port: int, username: str | None) -> None:
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

    # Not deleting the temp file here — mstsc reads it asynchronously after
    # this returns. It's small and lands in the OS temp dir, so it's left
    # for normal temp-directory cleanup rather than tracked and removed.
    subprocess.Popen(["mstsc.exe", path])


def _launch_rdp_linux(host: str, port: int, username: str | None) -> None:
    xfreerdp = shutil.which("xfreerdp3") or shutil.which("xfreerdp")
    if not xfreerdp:
        raise SessionLaunchError(RDP_INSTALL_HINT)

    args = [xfreerdp, f"/v:{host}:{port}", "/cert:ignore", "/dynamic-resolution"]
    if username:
        args.append(f"/u:{username}")
    subprocess.Popen(args)


# -- SSH terminal spawning ----------------------------------------------


def _spawn_in_windows_terminal(argv: list[str]) -> None:
    wt = shutil.which("wt.exe") or shutil.which("wt")
    if wt:
        subprocess.Popen([wt, "--", *argv])
        return
    # Fallback: a plain cmd window that stays open after ssh exits.
    subprocess.Popen(["cmd.exe", "/c", "start", "IT Toolbox SSH", "cmd", "/k", *argv])


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

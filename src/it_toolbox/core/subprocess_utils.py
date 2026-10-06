"""Shared subprocess helpers.

On Windows, every console-subsystem executable (rclone.exe, gcloud.cmd,
virsh.exe, wsl.exe, powershell.exe, ssh.exe...) spawned from this GUI app
gets its own brand-new, visible console window unless told otherwise --
confirmed live: a terminal window briefly flashed on every Cloud Storage
interaction, one per background `rclone` call. Any subprocess whose output
is captured or discarded (i.e. not a terminal the user is meant to see)
should pass **no_window_kwargs() through to subprocess.run/Popen.
"""

import subprocess
import sys


def no_window_kwargs() -> dict:
    """subprocess.run/Popen kwargs that keep a background child process
    from opening a visible console window on Windows; empty elsewhere.

    A function, not a module-level constant, so the win32 branch is
    testable from a non-Windows interpreter -- CREATE_NO_WINDOW only
    exists as a subprocess attribute on Windows, hence getattr with a
    harmless fallback rather than a direct attribute reference.
    """
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}

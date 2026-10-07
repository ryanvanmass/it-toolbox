"""Echo service: proves the whole app <-> WSL helper path works (spawn,
handshake, localhost forwarding, framing) without needing any of the
real tools. Settings' "Check Tools" runs it.

Replies to START with READY(json: python version, rootfs version), then
echoes every message back until STOP or the connection closes.
"""

import json
import platform
import threading
from pathlib import Path

from it_toolbox.core.wsl import transport

READY = transport.MSG_SERVICE_BASE


def _rootfs_version() -> str | None:
    try:
        return Path("/etc/it-toolbox-rootfs").read_text().strip()
    except OSError:
        return None


def run(conn: transport.Connection, params: dict, stop: threading.Event) -> None:
    conn.send(
        READY,
        json.dumps({"python": platform.python_version(), "rootfs": _rootfs_version()}).encode(),
    )
    while not stop.is_set():
        try:
            msg_type, payload = conn.recv()
        except (EOFError, OSError):
            return
        if msg_type == transport.MSG_STOP:
            return
        conn.send(msg_type, payload)

"""python3 -m it_toolbox.wsl_helper <service>

Prints the transport handshake line, waits for the app to connect, then
hands the connection to the service. Exits when the service returns, or
when its stdin closes -- the app holds the other end of that pipe, so a
crashed or killed app never leaves a helper running.
"""

import importlib
import os
import sys
import threading
import traceback

from it_toolbox.core.wsl import transport

# name -> "module:function", imported lazily so e.g. selftest works
# without spice-glib installed.
SERVICES = {
    "selftest": "it_toolbox.wsl_helper.selftest_service:run",
    "spice": "it_toolbox.wsl_helper.spice_service:run",
}

_STDIN_EOF_GRACE_SEC = 5


def _watch_stdin(stop: threading.Event, holder: dict) -> None:
    # os.read on the raw fd, not sys.stdin.buffer: a daemon thread blocked
    # inside the buffered reader aborts the interpreter at shutdown
    # ("could not acquire lock for <stdin>"), turning every clean exit
    # into SIGABRT.
    try:
        while os.read(sys.stdin.fileno(), 4096):
            pass
    except (OSError, ValueError):
        pass
    stop.set()
    conn = holder.get("conn")
    if conn is not None:
        conn.close()  # unblocks the service's recv()
    # Give the service a moment to clean up (tunnel, SPICE session), then
    # make sure this process is gone regardless.
    threading.Timer(_STDIN_EOF_GRACE_SEC, lambda: os._exit(0)).start()


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SERVICES:
        print(f"usage: python3 -m it_toolbox.wsl_helper {{{','.join(SERVICES)}}}", file=sys.stderr)
        return 2
    module_name, func_name = SERVICES[argv[0]].split(":")

    stop = threading.Event()
    holder: dict = {}
    threading.Thread(target=_watch_stdin, args=(stop, holder), daemon=True).start()

    listener = transport.Listener()
    print(listener.handshake_line(), flush=True)
    try:
        conn, params = listener.accept()
    except transport.TransportError as exc:
        print(f"wsl_helper: {exc}", file=sys.stderr)
        return 1
    holder["conn"] = conn

    try:
        run = getattr(importlib.import_module(module_name), func_name)
        run(conn, params, stop)
    except Exception as exc:  # noqa: BLE001 - report anything to the app, then exit non-zero
        traceback.print_exc()
        try:
            conn.send(transport.MSG_ERROR, str(exc).encode())
        except OSError:
            pass
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

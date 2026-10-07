"""SPICE viewer service: runs the same SpiceSessionRunner the Linux build
uses in-process, and streams its frames/events to the app's
RemoteSpiceWorker (core/spice/remote_protocol.py), feeding input back.

Owns the qemu+ssh:// tunnel too: running it on the Windows side would
mean this process has to reach Windows' loopback, which only works in
WSL's mirrored networking mode; from inside the distro it works in both.

START params: {"uri": libvirt URI, "port": the VM's SPICE port on that
host, "password": SPICE password or ""}.
"""

import threading

from it_toolbox.core.qemu_tunnel import QemuTunnel, is_local_uri
from it_toolbox.core.spice import remote_protocol as proto
from it_toolbox.core.wsl import transport


def _make_runner(host: str, port: int, password: str, **callbacks):
    # Imported here, not at module level, so a missing spice-glib shows up
    # as a clean MSG_ERROR to the app rather than an import-time crash.
    from it_toolbox.core.spice.spice_session_runner import SpiceSessionRunner

    return SpiceSessionRunner(host, port, password, **callbacks)


def _make_tunnel(uri: str, port: int):
    return QemuTunnel(uri, port)


def run(conn: transport.Connection, params: dict, stop: threading.Event) -> None:
    uri = params["uri"]
    spice_port = int(params["port"])
    password = params.get("password") or ""

    tunnel = None
    try:
        if is_local_uri(uri):
            port = spice_port
        else:
            tunnel = _make_tunnel(uri, spice_port)
            tunnel.start()
            port = tunnel.port

        def send(msg_type: int, payload: bytes = b"") -> None:
            try:
                conn.send(msg_type, payload)
            except OSError:
                stop.set()

        def on_frame(pixels, band_top, band_height, canvas_width, canvas_height, stride):
            send(
                proto.FRAME,
                proto.FRAME_HEADER.pack(band_top, band_height, canvas_width, canvas_height, stride) + pixels,
            )

        session_over = threading.Event()

        def on_disconnected():
            session_over.set()
            send(proto.DISCONNECTED)

        runner = _make_runner(
            "127.0.0.1",
            port,
            password,
            on_frame=on_frame,
            on_connected=lambda: send(proto.CONNECTED),
            on_agent_connected=lambda: send(proto.AGENT_CONNECTED),
            on_error=lambda message: send(transport.MSG_ERROR, message.encode()),
            on_disconnected=on_disconnected,
        )
        runner.start()
        try:
            _pump_input(conn, runner, stop)
        finally:
            runner.stop()
            if not session_over.is_set():
                send(proto.DISCONNECTED)
    finally:
        if tunnel is not None:
            tunnel.stop()


def _pump_input(conn: transport.Connection, runner, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            msg_type, payload = conn.recv()
        except (EOFError, OSError):
            return
        if msg_type == transport.MSG_STOP:
            return
        if msg_type == proto.MOUSE_MOVE:
            runner.send_mouse_move(*proto.POINT.unpack(payload))
        elif msg_type == proto.MOUSE_BUTTON:
            (down,) = proto.BUTTON.unpack_from(payload)
            runner.send_mouse_button(payload[proto.BUTTON.size :].decode(), down)
        elif msg_type == proto.MOUSE_WHEEL:
            runner.send_mouse_wheel(*proto.WHEEL.unpack(payload))
        elif msg_type == proto.KEY_SCANCODE:
            runner.send_key_scancode(*proto.KEY.unpack(payload))
        elif msg_type == proto.RESIZE:
            runner.send_resize(*proto.SIZE.unpack(payload))

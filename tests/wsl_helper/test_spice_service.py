import threading
from typing import ClassVar

from it_toolbox.core.spice import remote_protocol as proto
from it_toolbox.core.wsl import transport
from it_toolbox.wsl_helper import spice_service


class _FakeRunner:
    instances: ClassVar[list["_FakeRunner"]] = []

    def __init__(self, host, port, password, **callbacks):
        self.host, self.port, self.password = host, port, password
        self.callbacks = callbacks
        self.inputs = []
        self.stopped = False
        _FakeRunner.instances.append(self)

    def start(self):
        self.callbacks["on_connected"]()
        self.callbacks["on_frame"](b"\x01\x02\x03\x04" * 2, 3, 1, 2, 10, 8)

    def stop(self):
        self.stopped = True

    def send_mouse_move(self, x, y):
        self.inputs.append(("move", x, y))

    def send_mouse_button(self, button, down):
        self.inputs.append(("button", button, down))

    def send_mouse_wheel(self, steps):
        self.inputs.append(("wheel", steps))

    def send_key_scancode(self, code, extended, down):
        self.inputs.append(("key", code, extended, down))

    def send_resize(self, width, height):
        self.inputs.append(("resize", width, height))


class _FakeTunnel:
    def __init__(self, uri, port):
        self.uri, self.remote_port, self.port = uri, port, 47000
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _connected_pair():
    listener = transport.Listener()
    port, token = transport.parse_handshake_line(listener.handshake_line())
    result = {}
    thread = threading.Thread(target=lambda: result.update(pair=listener.accept(timeout=5)))
    thread.start()
    return port, token, thread, result


def _run_service(monkeypatch, params, tunnels):
    _FakeRunner.instances.clear()
    monkeypatch.setattr(spice_service, "_make_runner", _FakeRunner)
    monkeypatch.setattr(
        spice_service, "_make_tunnel", lambda uri, port: tunnels.append(_FakeTunnel(uri, port)) or tunnels[-1]
    )
    port, token, thread, result = _connected_pair()
    app = transport.connect(port, token, params)
    thread.join(5)
    helper_conn, started_params = result["pair"]
    service = threading.Thread(target=spice_service.run, args=(helper_conn, started_params, threading.Event()))
    service.start()
    return app, service


def test_spice_service_tunnels_streams_frames_and_forwards_input(monkeypatch):
    tunnels = []
    app, service = _run_service(monkeypatch, {"uri": "qemu+ssh://u@lab/system", "port": 5901, "password": ""}, tunnels)

    assert app.recv() == (proto.CONNECTED, b"")
    msg_type, payload = app.recv()
    assert msg_type == proto.FRAME
    assert proto.FRAME_HEADER.unpack_from(payload) == (3, 1, 2, 10, 8)
    assert payload[proto.FRAME_HEADER.size :] == b"\x01\x02\x03\x04" * 2

    app.send(proto.MOUSE_MOVE, proto.POINT.pack(10, -2))
    app.send(proto.MOUSE_BUTTON, proto.BUTTON.pack(True) + b"left")
    app.send(proto.MOUSE_WHEEL, proto.WHEEL.pack(-3))
    app.send(proto.KEY_SCANCODE, proto.KEY.pack(0x1C, True, False))
    app.send(proto.RESIZE, proto.SIZE.pack(1280, 720))
    app.send(transport.MSG_STOP)
    service.join(5)

    runner = _FakeRunner.instances[0]
    # The SPICE client connects through the helper's own tunnel.
    assert (runner.host, runner.port) == ("127.0.0.1", 47000)
    assert tunnels[0].started and tunnels[0].stopped
    assert (tunnels[0].uri, tunnels[0].remote_port) == ("qemu+ssh://u@lab/system", 5901)
    assert runner.inputs == [
        ("move", 10, -2),
        ("button", "left", True),
        ("wheel", -3),
        ("key", 0x1C, True, False),
        ("resize", 1280, 720),
    ]
    assert runner.stopped
    assert app.recv() == (proto.DISCONNECTED, b"")
    app.close()


def test_spice_service_local_uri_skips_tunnel(monkeypatch):
    tunnels = []
    app, service = _run_service(monkeypatch, {"uri": "qemu:///system", "port": 5930}, tunnels)
    app.recv()
    app.close()  # app gone without STOP -- service must still wind down
    service.join(5)

    assert not service.is_alive()
    assert tunnels == []
    assert _FakeRunner.instances[0].port == 5930
    assert _FakeRunner.instances[0].stopped

import threading

from it_toolbox.core.spice import remote_protocol as proto
from it_toolbox.core.spice import remote_spice_worker
from it_toolbox.core.wsl import transport


class _FakeHelper:
    """Stands in for HelperProcess: hands RemoteSpiceWorker one end of a
    real transport connection and lets the test play the helper."""

    def __init__(self, service, params, backend=None):
        self.service, self.params = service, params
        listener = transport.Listener()
        port, token = transport.parse_handshake_line(listener.handshake_line())
        result = {}
        thread = threading.Thread(target=lambda: result.update(pair=listener.accept(timeout=5)))
        thread.start()
        self._app_conn = transport.connect(port, token, params)
        thread.join(5)
        self.helper_conn, self.started_params = result["pair"]
        self.stopped = False
        _FakeHelper.last = self

    def start(self):
        return self._app_conn

    def stop(self):
        self.stopped = True
        self._app_conn.close()

    def stderr_tail(self):
        return ""


def test_remote_worker_mirrors_helper_messages_as_signals(qtbot, monkeypatch):
    monkeypatch.setattr(remote_spice_worker, "HelperProcess", _FakeHelper)
    worker = remote_spice_worker.RemoteSpiceWorker("qemu+ssh://u@lab/system", 5901, "pw")
    helper = _FakeHelper.last
    assert helper.service == "spice"
    assert helper.started_params == {"uri": "qemu+ssh://u@lab/system", "port": 5901, "password": "pw"}

    frames, events = [], []
    worker.signals.frame_ready.connect(lambda *args: frames.append(args))
    worker.signals.connected.connect(lambda: events.append("connected"))
    worker.signals.agent_connected.connect(lambda: events.append("agent"))
    worker.signals.error.connect(lambda message: events.append(("error", message)))
    worker.signals.disconnected.connect(lambda: events.append("disconnected"))
    worker.start()

    helper.helper_conn.send(proto.CONNECTED)
    helper.helper_conn.send(proto.FRAME, proto.FRAME_HEADER.pack(0, 1, 2, 1, 8) + b"\xff" * 8)
    helper.helper_conn.send(proto.AGENT_CONNECTED)
    helper.helper_conn.send(transport.MSG_ERROR, b"guest went away")
    qtbot.waitUntil(lambda: len(events) == 3)

    assert frames == [(b"\xff" * 8, 0, 1, 2, 1, 8)]
    assert events == ["connected", "agent", ("error", "guest went away")]

    worker.send_mouse_move(4, 5)
    worker.send_mouse_button("right", False)
    worker.send_key_scancode(0x2A, False, True)
    worker.send_resize(800, 600)
    worker.send_mouse_wheel(2)
    received = [helper.helper_conn.recv() for _ in range(5)]
    assert received == [
        (proto.MOUSE_MOVE, proto.POINT.pack(4, 5)),
        (proto.MOUSE_BUTTON, proto.BUTTON.pack(False) + b"right"),
        (proto.KEY_SCANCODE, proto.KEY.pack(0x2A, False, True)),
        (proto.RESIZE, proto.SIZE.pack(800, 600)),
        (proto.MOUSE_WHEEL, proto.WHEEL.pack(2)),
    ]

    helper.helper_conn.send(proto.DISCONNECTED)
    qtbot.waitUntil(lambda: "disconnected" in events)
    worker.stop()
    assert helper.stopped
    assert events.count("disconnected") == 1
    helper.helper_conn.close()


def test_remote_worker_reports_helper_start_failure(qtbot, monkeypatch):
    class _FailingHelper:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise transport.TransportError("Linux tools aren't set up")

        def stop(self):
            pass

    monkeypatch.setattr(remote_spice_worker, "HelperProcess", _FailingHelper)
    worker = remote_spice_worker.RemoteSpiceWorker("qemu:///system", 5900)
    events = []
    worker.signals.error.connect(lambda message: events.append(message))
    worker.signals.disconnected.connect(lambda: events.append("disconnected"))
    worker.start()

    qtbot.waitUntil(lambda: "disconnected" in events)
    assert events == ["Linux tools aren't set up", "disconnected"]

import pytest

try:
    from it_toolbox.core.rdp import rdp_session_worker
except OSError:  # FreeRDP3 isn't installed on this machine
    pytest.skip("FreeRDP3 libraries not installed", allow_module_level=True)


class _EndsBeforeFirstFrameSession:
    on_frame = None

    def connect(self, *args, **kwargs):
        pass

    def pump_once(self):
        return False

    def last_error_text(self):
        return "ERRCONNECT_CONNECT_TRANSPORT_FAILED (code 0x2000d)"

    def disconnect(self):
        pass


def test_a_session_ending_before_its_first_frame_reports_freerdps_reason(qtbot, monkeypatch):
    monkeypatch.setattr(rdp_session_worker, "FreeRdpSession", _EndsBeforeFirstFrameSession)
    worker = rdp_session_worker.RdpSessionWorker("host", 3389, "user", "pass")
    errors, disconnects = [], []
    worker.signals.error.connect(errors.append)
    worker.signals.disconnected.connect(lambda: disconnects.append(True))

    worker._run()

    assert errors == [
        "The connection closed before the remote desktop appeared: "
        "ERRCONNECT_CONNECT_TRANSPORT_FAILED (code 0x2000d)"
    ]
    assert disconnects == [True]


class _RecordingSession:
    on_frame = None

    def __init__(self):
        self.calls = []
        self.frames_read = 0

    def send_mouse_move(self, x, y):
        self.calls.append(("move", x, y))

    def send_mouse_button(self, x, y, button, down):
        self.calls.append(("button", x, y, button, down))

    def get_frame(self):
        self.frames_read += 1
        return b"\0" * 16, 2, 2, 8


def _worker_with(monkeypatch, session):
    monkeypatch.setattr(rdp_session_worker, "FreeRdpSession", lambda: session)
    return rdp_session_worker.RdpSessionWorker("host", 3389, "user", "pass")


def test_consecutive_mouse_moves_collapse_into_the_last_one(qtbot, monkeypatch):
    session = _RecordingSession()
    worker = _worker_with(monkeypatch, session)
    for x in range(5):
        worker.send_mouse_move(x, 0)
    worker.send_mouse_button(4, 0, "left", True)
    worker.send_mouse_move(7, 1)
    worker.send_mouse_move(8, 1)

    worker._drain_input_queue()

    assert session.calls == [("move", 4, 0), ("button", 4, 0, "left", True), ("move", 8, 1)]


def test_frames_are_held_back_until_the_previous_one_is_consumed(qtbot, monkeypatch):
    session = _RecordingSession()
    worker = _worker_with(monkeypatch, session)
    delivered = []
    worker.signals.frame_ready.connect(lambda *frame: delivered.append(frame))

    worker._on_frame()
    worker._on_frame()
    worker._deliver_frame()
    worker._on_frame()
    worker._deliver_frame()  # previous frame not consumed yet: held back
    assert (len(delivered), session.frames_read) == (1, 1)

    worker.frame_consumed()
    worker._deliver_frame()
    worker._deliver_frame()  # nothing new painted since
    assert (len(delivered), session.frames_read) == (2, 2)

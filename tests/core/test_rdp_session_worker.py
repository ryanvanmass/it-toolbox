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

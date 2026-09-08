import pytest

from it_toolbox.core.rdp.rdp_session_worker import RdpSessionSignals
from it_toolbox.widgets.rdp_widget import RdpWidget


class _FakeWorker:
    """Stands in for RdpSessionWorker — the real one spawns a background
    thread that tries to actually connect over the network in start().
    Uses the real RdpSessionSignals so RdpWidget's own signal connections
    (made in __init__, before a test can intervene) work unmodified.
    """

    def __init__(self, *args, **kwargs):
        self.signals = RdpSessionSignals()
        self.resize_calls = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self, timeout=5):
        self.stopped = True

    def request_resize(self, width, height):
        self.resize_calls.append((width, height))


@pytest.fixture
def rdp_widget(qtbot, monkeypatch):
    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _FakeWorker)
    widget = RdpWidget("host", 3389, "user", "pass")
    qtbot.addWidget(widget)
    return widget


def test_refresh_resolution_sends_the_current_size_on_demand(rdp_widget):
    rdp_widget.resize(800, 600)

    rdp_widget.refresh_resolution()

    assert rdp_widget._worker.resize_calls[-1] == (800, 600)


def test_refresh_resolution_has_no_deduplication(rdp_widget):
    rdp_widget.resize(800, 600)

    rdp_widget.refresh_resolution()
    rdp_widget.refresh_resolution()

    assert rdp_widget._worker.resize_calls == [(800, 600), (800, 600)]

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


def test_refresh_resolution_sends_the_current_size_once_the_debounce_settles(qtbot, rdp_widget):
    rdp_widget.resize(800, 600)
    rdp_widget._resize_debounce.setInterval(10)  # don't wait a real 250ms in a test

    rdp_widget.refresh_resolution()

    qtbot.waitUntil(lambda: bool(rdp_widget._worker.resize_calls), timeout=1000)
    assert rdp_widget._worker.resize_calls[-1] == (800, 600)


def test_refresh_resolution_coalesces_with_an_already_pending_resize(qtbot, rdp_widget):
    # Regression test for the actual bug this fix addresses: a real RDP
    # resize is a round trip to the server plus a full-desktop redraw --
    # measurably slow on its own, confirmed in real usage. The original
    # implementation called _send_resize_request() immediately, so
    # clicking "Refresh Resolution" while a drag-triggered resize was
    # already debounced queued a *second*, separate round trip instead
    # of coalescing with the first -- stacking into several seconds of
    # extra lag. Simulates "a drag is in progress" the same way
    # resizeEvent itself does: starting the debounce timer directly,
    # without needing a real QResizeEvent.
    rdp_widget.resize(800, 600)
    rdp_widget._resize_debounce.setInterval(10)
    rdp_widget._resize_debounce.start()

    rdp_widget.refresh_resolution()

    qtbot.waitUntil(lambda: bool(rdp_widget._worker.resize_calls), timeout=1000)
    qtbot.wait(50)  # let anything else pending settle too
    assert rdp_widget._worker.resize_calls == [(800, 600)]

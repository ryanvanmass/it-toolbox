import pytest
from PySide6.QtCore import QPointF, QRect

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


@pytest.fixture
def fixed_resolution_rdp_widget(qtbot, monkeypatch):
    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _FakeWorker)
    widget = RdpWidget("host", 3389, "user", "pass", desktop_size=(1920, 1080))
    qtbot.addWidget(widget)
    return widget


def test_fixed_desktop_size_is_passed_to_the_worker(qtbot, monkeypatch):
    captured = {}

    class _CapturingWorker(_FakeWorker):
        def __init__(self, host, port, username, password, domain="", desktop_size=None):
            super().__init__()
            captured["desktop_size"] = desktop_size

    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _CapturingWorker)

    widget = RdpWidget("host", 3389, "user", "pass", desktop_size=(1920, 1080))
    qtbot.addWidget(widget)

    assert captured["desktop_size"] == (1920, 1080)


def test_resizing_with_a_fixed_desktop_size_does_not_request_a_resize(qtbot, fixed_resolution_rdp_widget):
    fixed_resolution_rdp_widget.resize(800, 600)

    qtbot.wait(300)  # longer than the (unstarted) debounce interval

    assert fixed_resolution_rdp_widget._worker.resize_calls == []


def test_refresh_resolution_sends_the_fixed_size_not_the_widget_size(qtbot, fixed_resolution_rdp_widget):
    fixed_resolution_rdp_widget.resize(800, 600)

    fixed_resolution_rdp_widget.refresh_resolution()

    assert fixed_resolution_rdp_widget._worker.resize_calls == [(1920, 1080)]


# -- Letterboxing: a fixed resolution renders at its own aspect ratio, ------
# -- not stretched to fill a differently-shaped widget ----------------------


def _set_image(widget, width, height):
    stride = width * 4  # Format_RGB32, no padding needed for this synthetic buffer
    widget._on_frame_ready(bytes(stride * height), width, height, stride)


def test_scaled_image_rect_has_no_bars_when_aspect_ratios_match(qtbot, rdp_widget):
    rdp_widget.resize(800, 600)
    _set_image(rdp_widget, 800, 600)

    assert rdp_widget._scaled_image_rect() == rdp_widget.rect()


def test_scaled_image_rect_pillarboxes_a_narrower_image(qtbot, rdp_widget):
    # A 4:3 image (800x600) in a 16:9 widget (1600x900) leaves equal bars
    # on the left and right, full height, rather than stretching the
    # image horizontally to fill the widget.
    rdp_widget.resize(1600, 900)
    _set_image(rdp_widget, 800, 600)

    assert rdp_widget._scaled_image_rect() == QRect(200, 0, 1200, 900)


def test_remote_pos_maps_through_the_letterboxed_rect(qtbot, rdp_widget):
    rdp_widget.resize(1600, 900)
    _set_image(rdp_widget, 800, 600)

    # The image area's left edge, vertically centered.
    assert rdp_widget._remote_pos(QPointF(200, 450)) == (0, 300)


def test_remote_pos_clamps_clicks_in_the_letterbox_bars(qtbot, rdp_widget):
    rdp_widget.resize(1600, 900)
    _set_image(rdp_widget, 800, 600)

    # Left bar and right bar both clamp to the nearest image edge instead
    # of mapping to a negative or out-of-range remote coordinate.
    assert rdp_widget._remote_pos(QPointF(0, 450)) == (0, 300)
    assert rdp_widget._remote_pos(QPointF(1600, 450)) == (799, 300)

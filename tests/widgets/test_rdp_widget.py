"""Covers RdpWidget's "settle window" (see its module docstring): both
the very first frame after connecting and any frame after a resize
arrive as a series of incremental bitmap updates, not one shot, so the
last *settled* frame stays displayed until a frame confirmed to have
settled arrives — rather than switching over to a partially-painted
(possibly still-black) frame the instant its dimensions match the
target. RdpSessionWorker is replaced with a fake so these tests never
attempt a real RDP connection.
"""

from PySide6.QtCore import QObject, QPointF, Signal

from it_toolbox.widgets.rdp_widget import RdpWidget


class _FakeSignals(QObject):
    frame_ready = Signal(bytes, int, int, int)
    connected = Signal()
    error = Signal(str)
    disconnected = Signal()


class _FakeWorker:
    def __init__(self, *args, **kwargs):
        self.signals = _FakeSignals()
        self.resize_requests: list[tuple[int, int]] = []
        self.stopped = False

    def start(self) -> None:
        pass

    def request_resize(self, width: int, height: int) -> None:
        self.resize_requests.append((width, height))

    def stop(self, timeout: float = 5) -> None:
        self.stopped = True


def _make_widget(qtbot, monkeypatch):
    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _FakeWorker)
    widget = RdpWidget("host", 3389, "user", "password")
    qtbot.addWidget(widget)
    return widget


def _frame_bytes(width: int, height: int) -> bytes:
    return bytes(width * height * 4)


def _settle(widget, width: int, height: int) -> None:
    """Delivers one frame at (width, height) and settles it immediately
    (bypassing the real 2s timer) — for tests that need an
    already-displayed frame to build on, not testing the settle
    mechanism itself. Also stops the real QTimer the frame started,
    matching the state it would be in had it actually fired on its own
    (a singleShot timer is no longer "active" once it's fired)."""
    widget._on_frame_ready(_frame_bytes(width, height), width, height, width * 4)
    widget._resize_settle_timer.stop()
    widget._on_resize_settled()


def test_first_frame_is_not_displayed_until_settled(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)

    widget._on_frame_ready(_frame_bytes(800, 600), 800, 600, 800 * 4)

    assert widget._display_image is None
    assert widget._resize_settle_timer.isActive()

    widget._on_resize_settled()

    assert widget._display_image.size().width() == 800


def test_first_frame_hides_the_connecting_label_only_once_settled(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    widget._on_connected()
    widget._on_frame_ready(_frame_bytes(800, 600), 800, 600, 800 * 4)

    assert widget._status_label.isHidden() is False

    widget._on_resize_settled()

    assert widget._status_label.isHidden() is True


def test_resize_defers_display_until_settle_timer_fires(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    _settle(widget, 800, 600)
    old_display = widget._display_image

    widget._pending_resize_size = (1920, 1080)
    widget._on_frame_ready(_frame_bytes(1920, 1080), 1920, 1080, 1920 * 4)

    # New frame arrived at the target size, but the settle window hasn't
    # elapsed yet — the old (already-settled) frame must stay displayed.
    assert widget._display_image is old_display
    assert widget._resize_settle_timer.isActive()

    widget._on_resize_settled()

    assert widget._display_image.size().width() == 1920
    assert widget._pending_resize_size is None


def test_frames_not_matching_target_size_never_get_displayed(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    _settle(widget, 800, 600)
    old_display = widget._display_image

    widget._pending_resize_size = (1920, 1080)
    # A late frame at the *old* size, still trickling in after the resize
    # was requested but before the server has caught up.
    widget._on_frame_ready(_frame_bytes(800, 600), 800, 600, 800 * 4)

    assert widget._display_image is old_display
    assert not widget._resize_settle_timer.isActive()


def test_repeated_frames_at_target_size_do_not_restart_the_settle_timer(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    widget._pending_resize_size = (1920, 1080)

    widget._on_frame_ready(_frame_bytes(1920, 1080), 1920, 1080, 1920 * 4)
    first_remaining = widget._resize_settle_timer.remainingTime()
    qtbot.wait(50)
    widget._on_frame_ready(_frame_bytes(1920, 1080), 1920, 1080, 1920 * 4)
    second_remaining = widget._resize_settle_timer.remainingTime()

    # If the second frame had restarted the timer, remaining time would
    # jump back up close to the full interval instead of continuing to
    # count down.
    assert second_remaining < first_remaining


def test_send_resize_request_records_pending_target(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    widget.resize(1024, 768)

    widget._send_resize_request()

    assert widget._pending_resize_size == (widget.width(), widget.height())
    assert widget._worker.resize_requests == [(widget.width(), widget.height())]


def test_send_resize_request_invalidates_a_stale_in_flight_settle(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    _settle(widget, 800, 600)
    widget._pending_resize_size = (1920, 1080)
    widget._on_frame_ready(_frame_bytes(1920, 1080), 1920, 1080, 1920 * 4)
    assert widget._resize_settle_timer.isActive()  # counting down for 1920x1080

    widget.resize(2560, 1440)
    widget._send_resize_request()  # a newer resize supersedes the 1920x1080 target

    assert widget._pending_resize_size == (2560, 1440)
    assert not widget._resize_settle_timer.isActive()


def test_remote_pos_scales_against_display_image_not_pending_image(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    widget.resize(400, 300)
    _settle(widget, 800, 600)
    widget._pending_resize_size = (1920, 1080)
    widget._on_frame_ready(_frame_bytes(1920, 1080), 1920, 1080, 1920 * 4)  # not yet settled

    x, y = widget._remote_pos(QPointF(200, 150))  # widget's own midpoint

    # Still scaled against the old 800x600 display image, not 1920x1080.
    assert (x, y) == (400, 300)


def test_disconnected_before_any_frame_shows_disconnected_label(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)

    widget._on_disconnected()

    assert widget._status_label.text() == "Disconnected"
    assert widget._status_label.isHidden() is False


def test_disconnected_after_a_settled_frame_does_not_show_label(qtbot, monkeypatch):
    widget = _make_widget(qtbot, monkeypatch)
    _settle(widget, 800, 600)

    widget._on_disconnected()

    assert widget._status_label.isHidden() is True

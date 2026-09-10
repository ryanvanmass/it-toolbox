import pytest
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QVBoxLayout, QWidget

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
        self.clipboard_texts = []
        self.scancode_calls = []
        self.unicode_calls = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self, timeout=5):
        self.stopped = True

    def request_resize(self, width, height):
        self.resize_calls.append((width, height))

    def send_clipboard_text(self, text):
        self.clipboard_texts.append(text)

    def send_key_scancode(self, code, extended, down):
        self.scancode_calls.append((code, extended, down))

    def send_key_unicode(self, codepoint, down):
        self.unicode_calls.append((codepoint, down))


@pytest.fixture
def rdp_widget(qtbot, monkeypatch):
    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _FakeWorker)
    widget = RdpWidget("host", 3389, "user", "pass")
    qtbot.addWidget(widget)
    yield widget
    # Each widget connects QApplication.clipboard().dataChanged to itself
    # (a process-wide singleton outliving any single test) — close_session()
    # tears that down the same way real teardown does, so later tests in
    # this file (or elsewhere in the same session) don't accumulate stale
    # connections against the shared clipboard.
    widget.close_session()


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
    yield widget
    widget.close_session()


def test_fixed_desktop_size_is_passed_to_the_worker(qtbot, monkeypatch):
    captured = {}

    class _CapturingWorker(_FakeWorker):
        def __init__(self, host, port, username, password, domain="", desktop_size=None, keyboard_layout=None):
            super().__init__()
            captured["desktop_size"] = desktop_size

    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _CapturingWorker)

    widget = RdpWidget("host", 3389, "user", "pass", desktop_size=(1920, 1080))
    qtbot.addWidget(widget)

    assert captured["desktop_size"] == (1920, 1080)


def test_keyboard_layout_is_passed_to_the_worker(qtbot, monkeypatch):
    captured = {}

    class _CapturingWorker(_FakeWorker):
        def __init__(
            self, host, port, username, password, domain="", desktop_size=None, keyboard_layout=None
        ):
            super().__init__()
            captured["keyboard_layout"] = keyboard_layout

    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _CapturingWorker)

    widget = RdpWidget("host", 3389, "user", "pass", keyboard_layout=0x040C)
    qtbot.addWidget(widget)

    assert captured["keyboard_layout"] == 0x040C


def test_keyboard_layout_defaults_to_english_us(qtbot, monkeypatch):
    captured = {}

    class _CapturingWorker(_FakeWorker):
        def __init__(
            self, host, port, username, password, domain="", desktop_size=None, keyboard_layout=None
        ):
            super().__init__()
            captured["keyboard_layout"] = keyboard_layout

    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _CapturingWorker)

    widget = RdpWidget("host", 3389, "user", "pass")
    qtbot.addWidget(widget)

    assert captured["keyboard_layout"] == 0x0409


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


# -- Clipboard: local clipboard changes are announced to the worker --------


def test_local_clipboard_change_sends_text_to_the_worker(rdp_widget):
    del rdp_widget._worker.clipboard_texts[:]  # drop whatever __init__/_on_connected already sent

    QApplication.clipboard().setText("copied text")

    assert rdp_widget._worker.clipboard_texts[-1] == "copied text"


def test_local_clipboard_change_to_empty_sends_none(rdp_widget):
    QApplication.clipboard().setText("")

    assert rdp_widget._worker.clipboard_texts[-1] is None


def test_on_connected_pushes_the_current_clipboard_text_once(qtbot, monkeypatch):
    QApplication.clipboard().setText("already on the clipboard")
    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _FakeWorker)
    widget = RdpWidget("host", 3389, "user", "pass")
    qtbot.addWidget(widget)
    del widget._worker.clipboard_texts[:]  # drop the one __init__'s dataChanged connect may have queued

    widget._on_connected()

    assert widget._worker.clipboard_texts == ["already on the clipboard"]
    widget.close_session()


def test_close_session_disconnects_the_clipboard_signal(rdp_widget):
    rdp_widget.close_session()
    calls_before = list(rdp_widget._worker.clipboard_texts)

    # Must not raise, and must not append any further calls -- proves the
    # disconnect in close_session() actually took effect.
    QApplication.clipboard().setText("after close")

    assert rdp_widget._worker.clipboard_texts == calls_before


def test_close_session_disconnect_is_safe_to_call_twice(rdp_widget):
    rdp_widget.close_session()
    rdp_widget.close_session()  # must not raise


# -- Connection failure is surfaced, not silent -----------------------------


def test_connection_error_shows_a_message_box(rdp_widget, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: calls.append(a)))

    rdp_widget._worker.signals.error.emit("Logon failed.")

    assert len(calls) == 1
    assert calls[0][2] == "Logon failed."  # (parent, title, message)
    assert "Connection failed: Logon failed." in rdp_widget._status_label.text()


def test_connection_error_after_close_does_not_show_a_message_box(rdp_widget, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: calls.append(a)))

    rdp_widget.close_session()
    rdp_widget._worker.signals.error.emit("Logon failed.")

    assert calls == []


# -- Tab / Shift+Tab: forwarded to the remote session, not stolen by -------
# -- Qt's own focus-traversal --------------------------------------------


@pytest.fixture
def rdp_widget_with_sibling(qtbot, monkeypatch):
    # Qt's default Tab-key focus-traversal only has somewhere to go (and
    # so only actually misbehaves) when there's another focusable widget
    # in the same window to steal focus to -- an isolated RdpWidget with
    # no siblings wouldn't reproduce the bug this guards against.
    monkeypatch.setattr("it_toolbox.widgets.rdp_widget.RdpSessionWorker", _FakeWorker)
    container = QWidget()
    layout = QVBoxLayout(container)
    widget = RdpWidget("host", 3389, "user", "pass", parent=container)
    sibling = QLineEdit(container)
    layout.addWidget(widget)
    layout.addWidget(sibling)
    qtbot.addWidget(container)
    container.show()
    qtbot.waitExposed(container)
    widget.setFocus()
    yield widget
    widget.close_session()


def test_tab_is_forwarded_and_does_not_steal_focus(qtbot, rdp_widget_with_sibling):
    widget = rdp_widget_with_sibling
    assert widget.hasFocus()

    qtbot.keyClick(widget, Qt.Key.Key_Tab)

    assert (0x0F, False, True) in widget._worker.scancode_calls
    assert (0x0F, False, False) in widget._worker.scancode_calls
    assert widget.hasFocus()


def test_shift_tab_is_forwarded_and_does_not_steal_focus(qtbot, rdp_widget_with_sibling):
    widget = rdp_widget_with_sibling
    assert widget.hasFocus()

    qtbot.keyClick(widget, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)

    assert (0x0F, False, True) in widget._worker.scancode_calls
    assert widget.hasFocus()


def test_regular_keys_still_forward_normally_alongside_tab_handling(rdp_widget):
    # Regression guard: the new event() override must not interfere with
    # ordinary keys that aren't Tab/Backtab.
    key = Qt.Key.Key_A
    from PySide6.QtGui import QKeyEvent

    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, "a")
    rdp_widget.keyPressEvent(event)

    assert (0x1E, False, True) in rdp_widget._worker.scancode_calls


# -- Debug logging: every forwarded key logs what was actually computed -----
#
# Added to chase a live report of Shift+symbol (e.g. Shift+; -> ":") typing
# the wrong character on one specific VM, but working fine there with mstsc,
# and working fine with this same client against a different VM. A follow-up
# fix routing printable keys through send_key_unicode instead was tried and
# reverted -- it broke typing in PowerShell/cmd *entirely* (Windows console
# input doesn't handle synthetic Unicode/VK_PACKET keyboard events the way
# GUI controls do) -- so scancode is back to being the only path for
# anything with a SCANCODES entry, Shift+symbol included, and this logging
# is what's needed to keep chasing the real fix from an actual live repro.


def test_scancode_key_forwarding_is_logged(rdp_widget, caplog):
    from PySide6.QtGui import QKeyEvent

    with caplog.at_level("DEBUG", logger="it_toolbox.widgets.rdp_widget"):
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Semicolon, Qt.KeyboardModifier.ShiftModifier, ":"
        )
        rdp_widget.keyPressEvent(event)

    messages = [r.message for r in caplog.records]
    assert any("0x27" in m and "down=True" in m for m in messages)


def test_unicode_fallback_key_forwarding_is_logged(rdp_widget, caplog):
    from PySide6.QtGui import QKeyEvent

    with caplog.at_level("DEBUG", logger="it_toolbox.widgets.rdp_widget"):
        # Key_unknown has no SCANCODES entry, forcing the unicode fallback
        # path -- mirrors how a real layout-dependent symbol with no
        # dedicated Qt key constant would be forwarded.
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, "€")
        rdp_widget.keyPressEvent(event)

    messages = [r.message for r in caplog.records]
    assert any("'€'" in m and "down=True" in m for m in messages)

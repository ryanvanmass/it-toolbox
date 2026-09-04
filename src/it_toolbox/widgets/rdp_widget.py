"""Embedded RDP viewer widget, built on the libfreerdp3 ctypes bindings in
core/rdp/ — the "build it ourselves" replacement for the Windows ActiveX
control, which turned out to be unusable on at least one real Windows
test machine (no modern MsRdpClient ProgID registered, unfixable from
app code).

Renders the desktop and forwards mouse/keyboard input back to the
server. Displayed image is stretched to fill the widget (see
paintEvent), so pointer coordinates are rescaled from widget-space to
the remote desktop's native resolution before being sent.

Both the very first frame after connecting *and* any frame after a
resize arrive as a series of incremental bitmap updates, not one shot —
the first one at a given size is typically still mostly/partly blank
(same reasoning as FreeRdpSession's capture_one_frame settle_sec, and,
for a resize specifically, the round trip needed for
FreeRdpSession._request_full_refresh's response to land, commonly
~1-2s). Rather than displaying whatever partially-painted frame happens
to land at a new size first, _display_image keeps the last *settled*
frame on screen (stretched, same as any other frame — a brief stretch
during an active resize is normal/expected) until a short settle window
after first reaching that size has passed with no further size changes.
"""

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from it_toolbox.core.rdp.rdp_session_worker import RdpSessionWorker
from it_toolbox.core.rdp.scancodes import SCANCODES

_BUTTON_NAMES = {
    Qt.MouseButton.LeftButton: "left",
    Qt.MouseButton.RightButton: "right",
    Qt.MouseButton.MiddleButton: "middle",
    Qt.MouseButton.BackButton: "x1",
    Qt.MouseButton.ForwardButton: "x2",
}


class RdpWidget(QWidget):
    # Mirrors TerminalWidget.finished — fires once the session has ended,
    # whether from a connect failure, the remote side dropping the
    # connection, or close_session() being called. main_view.py connects
    # this the same way it connects TerminalWidget.finished, to tear the
    # session tab down uniformly regardless of which widget kind it holds.
    finished = Signal()

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        domain: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image: QImage | None = None  # latest frame received, whether settled or not
        self._display_image: QImage | None = None  # latest frame actually painted (see module docstring)
        self._frame_bytes: bytes | None = None  # keeps QImage's backing buffer alive
        self._pending_resize_size: tuple[int, int] | None = None
        self._closing = False  # set by close_session(); suppresses finished re-emission
        self._finished_emitted = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        # sizeHint() below deliberately reports the live remote resolution
        # (useful context for a layout that's choosing between competing
        # hints), but this widget must never actually be *shrunk* to it —
        # the displayed image already stretches to fill whatever size we
        # are (see paintEvent), so anything less than all the space our
        # container has to offer is just wasted whitespace, not a benefit.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._status_label = QLabel("Connecting…")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)

        # Debounced so a window drag doesn't fire a resize request per
        # pixel — restarted on every resizeEvent, only actually sent once
        # the size has settled for this long.
        self._resize_debounce = QTimer(self)
        self._resize_debounce.setSingleShot(True)
        self._resize_debounce.setInterval(250)
        self._resize_debounce.timeout.connect(self._send_resize_request)

        # How long to keep showing the last fully-rendered frame (stretched)
        # after first reaching the new size, before trusting a post-resize
        # frame is actually fully painted rather than still catching up —
        # same 2s figure and reasoning as capture_one_frame()'s settle_sec
        # in freerdp_client.py (a resize's redraw is the same kind of
        # "arrives as incremental updates, not one shot" situation as the
        # very first connection). Only starts once, on the first frame that
        # reaches the target size — later frames at that same size don't
        # restart it, or a continuously-updating desktop (e.g. a cursor
        # blink) would keep pushing it out forever.
        self._resize_settle_timer = QTimer(self)
        self._resize_settle_timer.setSingleShot(True)
        self._resize_settle_timer.setInterval(2000)
        self._resize_settle_timer.timeout.connect(self._on_resize_settled)

        self._worker = RdpSessionWorker(host, port, username, password, domain)
        self._worker.signals.frame_ready.connect(self._on_frame_ready)
        self._worker.signals.connected.connect(self._on_connected)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.disconnected.connect(self._on_disconnected)
        self._worker.start()

    def _on_connected(self) -> None:
        # Deliberately doesn't hide the "Connecting…" label — the RDP
        # handshake completing doesn't mean there's anything to show yet
        # (see module docstring); _on_resize_settled hides it once the
        # first real frame actually settles.
        pass

    def _on_frame_ready(self, pixels: bytes, width: int, height: int, stride: int) -> None:
        self._frame_bytes = pixels  # QImage below wraps this buffer without copying it
        self._image = QImage(self._frame_bytes, width, height, stride, QImage.Format.Format_RGB32)
        if self._pending_resize_size is None and self._display_image is None:
            # The very first frame ever: RDP delivers even the initial
            # screen as a series of incremental updates, not one shot
            # (same reasoning as capture_one_frame's settle_sec in
            # freerdp_client.py) — needs the same settle treatment as a
            # post-resize frame, not an instant, possibly-still-mostly-
            # blank display.
            self._pending_resize_size = (width, height)
        if self._pending_resize_size == (width, height) and not self._resize_settle_timer.isActive():
            self._resize_settle_timer.start()
        self.update()

    def _on_resize_settled(self) -> None:
        self._pending_resize_size = None
        self._display_image = self._image
        self._status_label.hide()  # no-op if this isn't the first-ever settle
        self.update()

    def _emit_finished_once(self) -> None:
        if not self._closing and not self._finished_emitted:
            self._finished_emitted = True
            self.finished.emit()

    def _on_error(self, message: str) -> None:
        if not self._closing:
            self._status_label.setText(f"Connection failed: {message}")
            self._status_label.show()
        self._emit_finished_once()

    def _on_disconnected(self) -> None:
        if not self._closing and self._display_image is None:
            self._status_label.setText("Disconnected")
            self._status_label.show()
        self._emit_finished_once()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if self._display_image is None:
            return
        painter = QPainter(self)
        painter.drawImage(self.rect(), self._display_image, self._display_image.rect())

    def sizeHint(self):
        if self._display_image is not None:
            return self._display_image.size()
        return super().sizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._resize_debounce.start()

    def _send_resize_request(self) -> None:
        self._pending_resize_size = (self.width(), self.height())
        # Any countdown already running was for whatever the previous
        # target was — no longer relevant now that a newer resize has
        # superseded it. Only a frame actually matching *this* new
        # target should be allowed to start (and complete) a countdown.
        self._resize_settle_timer.stop()
        self._worker.request_resize(self.width(), self.height())

    def close_session(self) -> None:
        """Matches the close_session() convention main_view uses to tear
        down any session tab (terminal, bucket browser, ...) uniformly."""
        self._closing = True
        self._worker.stop()

    # --- input: widget-space -> remote desktop-space, then forwarded ----

    def _remote_pos(self, widget_pos) -> tuple[int, int]:
        # Deliberately scaled against _display_image (what's actually on
        # screen right now), not the possibly-newer-but-not-yet-trusted
        # _image — otherwise clicks would target coordinates on a frame
        # the user can't see yet.
        if self._display_image is None or self.width() == 0 or self.height() == 0:
            return int(widget_pos.x()), int(widget_pos.y())
        scale_x = self._display_image.width() / self.width()
        scale_y = self._display_image.height() / self.height()
        return int(widget_pos.x() * scale_x), int(widget_pos.y() * scale_y)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x, y = self._remote_pos(event.position())
        self._worker.send_mouse_move(x, y)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        button = _BUTTON_NAMES.get(event.button())
        if button is None:
            return
        x, y = self._remote_pos(event.position())
        self._worker.send_mouse_button(x, y, button, True)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        button = _BUTTON_NAMES.get(event.button())
        if button is None:
            return
        x, y = self._remote_pos(event.position())
        self._worker.send_mouse_button(x, y, button, False)

    def wheelEvent(self, event) -> None:  # noqa: N802
        x, y = self._remote_pos(event.position())
        steps = event.angleDelta().y() // 120
        if steps:
            self._worker.send_mouse_wheel(x, y, steps)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self._forward_key_event(event, down=True)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        self._forward_key_event(event, down=False)

    def _forward_key_event(self, event, down: bool) -> None:
        key = Qt.Key(event.key())
        scancode = SCANCODES.get(key)
        if scancode is not None:
            code, extended = scancode
            self._worker.send_key_scancode(code, extended, down)
            return
        text = event.text()
        for char in text:
            if char.isprintable():
                self._worker.send_key_unicode(ord(char), down)

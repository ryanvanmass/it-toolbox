"""Embedded RDP viewer widget, built on the libfreerdp3 ctypes bindings in
core/rdp/ — the "build it ourselves" replacement for the Windows ActiveX
control, which turned out to be unusable on at least one real Windows
test machine (no modern MsRdpClient ProgID registered, unfixable from
app code).

Renders the desktop and forwards mouse/keyboard input back to the
server. Displayed image is stretched to fill the widget (see
paintEvent), so pointer coordinates are rescaled from widget-space to
the remote desktop's native resolution before being sent.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

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
        self._image: QImage | None = None
        self._frame_bytes: bytes | None = None  # keeps QImage's backing buffer alive
        self._closing = False  # set by close_session(); suppresses finished re-emission
        self._finished_emitted = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._status_label = QLabel("Connecting…")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)

        self._worker = RdpSessionWorker(host, port, username, password, domain)
        self._worker.signals.frame_ready.connect(self._on_frame_ready)
        self._worker.signals.connected.connect(self._on_connected)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.disconnected.connect(self._on_disconnected)
        self._worker.start()

    def _on_connected(self) -> None:
        self._status_label.hide()

    def _on_frame_ready(self, pixels: bytes, width: int, height: int, stride: int) -> None:
        self._frame_bytes = pixels  # QImage below wraps this buffer without copying it
        self._image = QImage(self._frame_bytes, width, height, stride, QImage.Format.Format_RGB32)
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
        if not self._closing and self._image is None:
            self._status_label.setText("Disconnected")
            self._status_label.show()
        self._emit_finished_once()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if self._image is None:
            return
        painter = QPainter(self)
        painter.drawImage(self.rect(), self._image, self._image.rect())

    def sizeHint(self):
        if self._image is not None:
            return self._image.size()
        return super().sizeHint()

    def close_session(self) -> None:
        """Matches the close_session() convention main_view uses to tear
        down any session tab (terminal, bucket browser, ...) uniformly."""
        self._closing = True
        self._worker.stop()

    # --- input: widget-space -> remote desktop-space, then forwarded ----

    def _remote_pos(self, widget_pos) -> tuple[int, int]:
        if self._image is None or self.width() == 0 or self.height() == 0:
            return int(widget_pos.x()), int(widget_pos.y())
        scale_x = self._image.width() / self.width()
        scale_y = self._image.height() / self.height()
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

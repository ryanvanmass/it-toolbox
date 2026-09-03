"""Embedded RDP viewer widget, built on the libfreerdp3 ctypes bindings in
core/rdp/ — the "build it ourselves" replacement for the Windows ActiveX
control, which turned out to be unusable on at least one real Windows
test machine (no modern MsRdpClient ProgID registered, unfixable from
app code).

Read-only viewer for now: renders the desktop, does not yet forward
mouse/keyboard input back to the server.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from it_toolbox.core.rdp.rdp_session_worker import RdpSessionWorker


class RdpWidget(QWidget):
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

    def _on_error(self, message: str) -> None:
        self._status_label.setText(f"Connection failed: {message}")
        self._status_label.show()

    def _on_disconnected(self) -> None:
        if self._image is None:
            self._status_label.setText("Disconnected")
            self._status_label.show()

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
        self._worker.stop()

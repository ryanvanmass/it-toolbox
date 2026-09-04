"""Embedded SPICE viewer widget, built on core/spice/ — renders a
libvirt-managed VM's display directly in the app (see
docs/qemu-spice-status.md for why: SPICE has no native Qt widget, and the
GTK one would mean embedding a foreign toolkit's window, which the
embedded-RDP branch already ruled out doing for a similar reason).

Milestone 5 scope: rendering only, mirroring RdpWidget's paintEvent/
frame_ready/finished/close_session shape. Mouse/keyboard input forwarding
(mirroring RdpWidget's mouse*Event/key*Event handlers) and resize support
land in later milestones — see docs/qemu-spice-status.md's milestone
list. Until then this is a read-only view of the VM's screen.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from it_toolbox.core.spice.spice_session_worker import SpiceSessionWorker


class SpiceWidget(QWidget):
    # Mirrors RdpWidget.finished/TerminalWidget.finished — fires once the
    # session has ended, whether from a connect failure, the remote side
    # dropping the connection, or close_session() being called.
    finished = Signal()

    def __init__(
        self,
        host: str,
        port: int,
        password: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._frame_bytes: bytes | None = None  # keeps QImage's backing buffer alive
        self._closing = False  # set by close_session(); suppresses finished re-emission
        self._finished_emitted = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._status_label = QLabel("Connecting…")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)

        self._worker = SpiceSessionWorker(host, port, password)
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
        down any session tab (terminal, RDP, ...) uniformly."""
        self._closing = True
        self._worker.stop()

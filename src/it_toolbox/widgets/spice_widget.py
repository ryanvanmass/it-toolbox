"""Embedded SPICE viewer widget, built on core/spice/ — renders a
libvirt-managed VM's display directly in the app (see
docs/qemu-spice-status.md for why: SPICE has no native Qt widget, and the
GTK one would mean embedding a foreign toolkit's window, which the
embedded-RDP branch already ruled out doing for a similar reason).

Milestones 5-6 scope: rendering and mouse/keyboard input, mirroring
RdpWidget's paintEvent/mouse*Event/key*Event/frame_ready/finished/
close_session shape. Resize support isn't implemented yet — see
docs/qemu-spice-status.md's milestone list.

The displayed image is scaled to fit the widget *without* distorting its
aspect ratio (see paintEvent/_scaled_canvas_rect) -- letterboxed with
bars rather than stretched, exactly mirroring RdpWidget's own reasoning:
an embedding QTabWidget stretches this widget to whatever size the tab
area happens to be, unrelated to the guest's actual resolution, and a
naive stretch-to-fill visibly distorts (and, without smooth scaling,
degrades the legibility of) the picture -- confirmed live against a
report that a native SPICE client (virt-viewer, which sizes its own
window to the guest instead of the reverse) looked "crystal clear" on
the exact same VM where this widget didn't. Pointer coordinates are
rescaled (and clamped, for clicks landing in the letterbox bars) from
widget-space to the guest's native resolution before being sent.

Unlike RDP, SPICE's InputsChannel has no unicode-text fast path — every
key goes through core/rdp/scancodes.SCANCODES (reused as-is; same PC/AT
Set 1 table), and a character with no entry there (e.g. non-US-layout
symbols) simply can't be forwarded through this widget. See
SpiceSession's input methods for the underlying reasoning.
"""

import math

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from it_toolbox.core.rdp.scancodes import SCANCODES
from it_toolbox.core.spice.spice_session_worker import SpiceSessionWorker

_BUTTON_NAMES = {
    Qt.MouseButton.LeftButton: "left",
    Qt.MouseButton.RightButton: "right",
    Qt.MouseButton.MiddleButton: "middle",
}


class SpiceWidget(QWidget):
    # Mirrors RdpWidget.finished/TerminalWidget.finished — fires once the
    # session has ended, whether from a connect failure, the remote side
    # dropping the connection, or close_session() being called.
    finished = Signal()

    # TEMPORARY diagnostic HUD (see paintEvent) -- printing the widget/
    # canvas/target sizes directly on screen so a real report of "still
    # looks distorted" after the letterbox fix can be checked against
    # exact numbers instead of a manual measurement. Remove once the
    # remaining distortion/blur report is resolved.
    _DEBUG_OVERLAY_RECT = QRect(0, 0, 620, 20)

    def __init__(
        self,
        host: str,
        port: int,
        password: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # A persistent backing canvas, not a fresh QImage per signal --
        # each frame_ready delivers only the rows that actually changed
        # (see SpiceSession.get_dirty_band()), so this widget owns the
        # full picture and composites each incoming band into it at the
        # right offset. QImage's own drawImage() call copies the band's
        # pixel data into the canvas's independently-allocated buffer, so
        # nothing needs to be kept alive past _on_frame_ready() returning.
        self._canvas: QImage | None = None
        self._debug_overlay_text = ""  # TEMPORARY -- see paintEvent
        self._closing = False  # set by close_session(); suppresses finished re-emission
        self._finished_emitted = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

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

    def _on_frame_ready(
        self, pixels: bytes, band_top: int, band_height: int, canvas_width: int, canvas_height: int, stride: int
    ) -> None:
        if self._canvas is None or self._canvas.width() != canvas_width or self._canvas.height() != canvas_height:
            # First frame, or the guest's resolution changed -- either way
            # the old canvas (if any) no longer corresponds to anything,
            # and get_dirty_band() itself always reports the full frame as
            # dirty right after a resolution change, so this always gets
            # fully repainted by the drawImage() below regardless.
            self._canvas = QImage(canvas_width, canvas_height, QImage.Format.Format_RGB32)
        band_image = QImage(pixels, canvas_width, band_height, stride, QImage.Format.Format_RGB32)
        painter = QPainter(self._canvas)
        try:
            painter.drawImage(0, band_top, band_image)
        finally:
            # Must run even if drawImage() raises -- an active QPainter
            # left on a paint device when its Python object is destroyed
            # doesn't reliably auto-end() itself here (confirmed the hard
            # way: a raised exception in the *other* drawImage() call
            # below, in paintEvent, left its QPainter active and crashed
            # the whole process with a segfault once Qt's own backing
            # store tried to end the paint cycle).
            painter.end()
        self.update(self._dirty_widget_rect(band_top, band_height))
        self.update(self._DEBUG_OVERLAY_RECT)  # keep the diagnostic HUD current every frame

    def _scaled_canvas_rect(self) -> QRect:
        """The largest rect, centered in the widget, that fits self._canvas
        at its native aspect ratio -- mirrors RdpWidget._scaled_image_rect()
        exactly, and for the same reason: an embedding QTabWidget stretches
        this widget to fill whatever arbitrary size the tab area happens to
        be, with no relation to the guest's actual resolution/aspect ratio
        (confirmed live: reported "crystal clear" in virt-viewer, which
        sizes its own window to the guest instead, but visibly degraded
        here). Stretching the image to cover a mismatched-aspect-ratio rect
        distorts it outright; letterboxing with bars instead keeps it
        undistorted at whatever size it does render.
        """
        if self._canvas is None:
            return self.rect()
        scaled = self._canvas.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return QRect(QPoint(x, y), scaled)

    def _dirty_widget_rect(self, band_top: int, band_height: int) -> QRect:
        """Maps a dirty row range in the canvas's own pixel space to the
        (possibly scaled and letterboxed) widget-space rect that needs
        repainting -- passed to update() so Qt only re-composites that
        area instead of the whole widget on every partial update (e.g.
        dragging a window only changes a limited band of the screen, not
        all of it)."""
        if self._canvas is None or self._canvas.height() == 0:
            return self.rect()
        target = self._scaled_canvas_rect()
        if target.height() == 0:
            return self.rect()
        scale_y = target.height() / self._canvas.height()
        top = target.y() + math.floor(band_top * scale_y)
        bottom = target.y() + math.ceil((band_top + band_height) * scale_y)
        return QRect(target.x(), top, target.width(), bottom - top)

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
        if not self._closing and self._canvas is None:
            self._status_label.setText("Disconnected")
            self._status_label.show()
        self._emit_finished_once()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if self._canvas is None or self.width() == 0 or self.height() == 0:
            return
        target = self._scaled_canvas_rect()
        self._debug_overlay_text = (
            f"widget={self.width()}x{self.height()}  "
            f"canvas={self._canvas.width()}x{self._canvas.height()}  "
            f"target={target.width()}x{target.height()} @ ({target.x()},{target.y()})  "
            f"devicePixelRatio={self.devicePixelRatioF():.2f}"
        )
        # Only re-composite the region Qt actually asked for (event.rect())
        # intersected with the actual image area -- update() above requests
        # just the dirty band's widget-space rect, so a partial update
        # (dragging a window, scrolling, ...) only ever costs a blit
        # proportional to what changed, not the whole display, however
        # large. Clip to `target` since event.rect() can include letterbox
        # bars, which have nothing to draw from the image.
        dest = event.rect().intersected(target)
        painter = QPainter(self)
        try:
            if target != self.rect():
                painter.fillRect(self.rect(), Qt.GlobalColor.black)
            # TEMPORARY diagnostic HUD -- drawn unconditionally (even when
            # `dest` below turns out empty) so it's always current; remove
            # once the remaining distortion/blur report is resolved.
            painter.fillRect(self._DEBUG_OVERLAY_RECT, Qt.GlobalColor.black)
            painter.setPen(Qt.GlobalColor.yellow)
            painter.drawText(self._DEBUG_OVERLAY_RECT.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignVCenter, self._debug_overlay_text)
            if dest.isEmpty():
                return
            scale_x = self._canvas.width() / target.width()
            scale_y = self._canvas.height() / target.height()
            src = QRectF(
                (dest.x() - target.x()) * scale_x,
                (dest.y() - target.y()) * scale_y,
                dest.width() * scale_x,
                dest.height() * scale_y,
            )
            if target.size() != self._canvas.size():
                # drawImage() defaults to nearest-neighbor scaling, which
                # looks blocky/aliased for anything but an exact pixel
                # match -- matches RdpWidget.paintEvent's own reasoning
                # exactly, only worth the cost when actually scaling.
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            # Both rects must be the *same* concrete type (QRectF here, not
            # a QRect target mixed with a QRectF source) -- confirmed the
            # hard way: PySide6's drawImage(rect, image, rect) overload
            # resolution rejects a mixed QRect/QRectF pair with a
            # ValueError even though each individually is a documented-
            # acceptable type for that slot, and the resulting exception
            # (if not for this try/finally) left this QPainter active on
            # the widget's backing store, which segfaulted the whole
            # process once Qt tried to end the paint cycle itself.
            painter.drawImage(QRectF(dest), self._canvas, src)
        finally:
            painter.end()

    def sizeHint(self):
        if self._canvas is not None:
            return self._canvas.size()
        return super().sizeHint()

    def close_session(self) -> None:
        """Matches the close_session() convention main_view uses to tear
        down any session tab (terminal, RDP, ...) uniformly."""
        self._closing = True
        self._worker.stop()

    # --- input: widget-space -> remote desktop-space, then forwarded ----

    def _remote_pos(self, widget_pos) -> tuple[int, int]:
        if self._canvas is None or self.width() == 0 or self.height() == 0:
            return int(widget_pos.x()), int(widget_pos.y())
        target = self._scaled_canvas_rect()
        if target.width() == 0 or target.height() == 0:
            return 0, 0
        scale_x = self._canvas.width() / target.width()
        scale_y = self._canvas.height() / target.height()
        x = (widget_pos.x() - target.x()) * scale_x
        y = (widget_pos.y() - target.y()) * scale_y
        # Clicks landing in the letterbox bars clamp to the nearest edge
        # of the image rather than mapping to a negative/out-of-range
        # remote coordinate -- matches RdpWidget._remote_pos() exactly.
        x = max(0, min(x, self._canvas.width() - 1))
        y = max(0, min(y, self._canvas.height() - 1))
        return int(x), int(y)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x, y = self._remote_pos(event.position())
        self._worker.send_mouse_move(x, y)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        button = _BUTTON_NAMES.get(event.button())
        if button is None:
            return
        x, y = self._remote_pos(event.position())
        self._worker.send_mouse_move(x, y)
        self._worker.send_mouse_button(button, True)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        button = _BUTTON_NAMES.get(event.button())
        if button is None:
            return
        x, y = self._remote_pos(event.position())
        self._worker.send_mouse_move(x, y)
        self._worker.send_mouse_button(button, False)

    def wheelEvent(self, event) -> None:  # noqa: N802
        x, y = self._remote_pos(event.position())
        steps = event.angleDelta().y() // 120
        if steps:
            self._worker.send_mouse_move(x, y)
            self._worker.send_mouse_wheel(steps)

    def event(self, e) -> bool:  # noqa: N802 - Qt override signature
        # Same fix as RdpWidget.event() -- Qt's default QWidget::event()
        # intercepts Tab/Shift+Tab (Key_Backtab) at this level to cycle
        # keyboard focus between widgets before keyPressEvent() ever sees
        # them; StrongFocus alone doesn't disable that. Forward these
        # directly and report the event as handled so Qt's own
        # focus-traversal never runs and silently steals local focus away
        # from the remote session.
        if e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(e)
            return True
        return super().event(e)

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

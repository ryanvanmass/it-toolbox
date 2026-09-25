"""Embedded RDP viewer widget, built on the libfreerdp3 ctypes bindings in
core/rdp/ — the "build it ourselves" replacement for the Windows ActiveX
control, which turned out to be unusable on at least one real Windows
test machine (no modern MsRdpClient ProgID registered, unfixable from
app code).

Renders the desktop and forwards mouse/keyboard input back to the
server. The displayed image is scaled to fit the widget *without*
distorting its aspect ratio (see paintEvent/_scaled_image_rect) —
letterboxed with bars rather than stretched, so a resolution requested
in Settings renders at its correct proportions even when the window
doesn't match its aspect ratio. Pointer coordinates are rescaled (and
clamped, for clicks that land in the letterbox bars) from widget-space
to the remote desktop's native resolution before being sent.
"""

import logging

from PySide6.QtCore import QEvent, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QVBoxLayout, QWidget

from it_toolbox.core.rdp.freerdp_client import KEYBOARD_LAYOUT_ENGLISH_US
from it_toolbox.core.rdp.rdp_session_worker import RdpSessionWorker
from it_toolbox.core.rdp.scancodes import SCANCODES

logger = logging.getLogger(__name__)

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
        desktop_size: tuple[int, int] | None = None,
        keyboard_layout: int = KEYBOARD_LAYOUT_ENGLISH_US,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # None means "match window size" (today's default: every resize
        # requests a matching server resolution). A fixed size instead
        # means the server resolution is requested once at connect and
        # never again from a resize — the displayed image is stretched to
        # fit the widget regardless (see paintEvent), so a window resize
        # doesn't need a round trip to look right. See settings.py's
        # load_default_rdp_resolution() docstring for why this exists.
        self._desktop_size = desktop_size
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

        # Debounced so a window drag doesn't fire a resize request per
        # pixel — restarted on every resizeEvent, only actually sent once
        # the size has settled for this long.
        self._resize_debounce = QTimer(self)
        self._resize_debounce.setSingleShot(True)
        self._resize_debounce.setInterval(250)
        self._resize_debounce.timeout.connect(self._send_resize_request)

        self._worker = RdpSessionWorker(
            host, port, username, password, domain, desktop_size, keyboard_layout
        )
        self._worker.signals.frame_ready.connect(self._on_frame_ready)
        self._worker.signals.connected.connect(self._on_connected)
        self._worker.signals.error.connect(self._on_error)
        self._worker.signals.disconnected.connect(self._on_disconnected)
        self._worker.start()

        # QApplication.clipboard() is a process-wide singleton, not scoped
        # to this widget/tab — with multiple RDP tabs open, every local
        # copy is announced to every open session, not just the focused
        # one. No existing precedent in this codebase scopes clipboard by
        # tab/focus; accepted as-is for this first iteration.
        QApplication.clipboard().dataChanged.connect(self._on_local_clipboard_changed)

    def _on_connected(self) -> None:
        self._status_label.hide()
        # Push whatever's already on the local clipboard once, so a
        # session that connects with existing clipboard content doesn't
        # have to wait for the *next* copy before paste-into-remote works.
        self._worker.send_clipboard_text(QApplication.clipboard().text() or None)

    def _on_local_clipboard_changed(self) -> None:
        self._worker.send_clipboard_text(QApplication.clipboard().text() or None)

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
            # main_view.py tears this tab down as soon as `finished` fires
            # below (same teardown path a clean disconnect uses) — often
            # too fast for the status label above to ever actually be
            # read. A blocking dialog guarantees the user sees why the
            # connection failed instead of just watching a tab flash open
            # and close.
            QMessageBox.warning(self, "RDP Connection Failed", message)
        self._emit_finished_once()

    def _on_disconnected(self) -> None:
        if not self._closing and self._image is None:
            self._status_label.setText("Disconnected")
            self._status_label.show()
        self._emit_finished_once()

    def _scaled_image_rect(self) -> QRect:
        """The largest rect, centered in the widget, that fits self._image
        at its native aspect ratio — the rest is filled with bars rather
        than stretching the image to cover it (see paintEvent).
        """
        scaled = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return QRect(QPoint(x, y), scaled)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        if self._image is None:
            return
        painter = QPainter(self)
        target = self._scaled_image_rect()
        if target != self.rect():
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if target.size() != self._image.size():
            # drawImage() defaults to nearest-neighbor scaling, which
            # looks blocky/aliased for anything but an exact pixel match
            # — and an exact match is rare even at the "right" aspect
            # ratio, since window borders/DPI scaling mean the widget is
            # essentially never exactly the image's native size. Only
            # worth the cost when actually scaling; skip it for a 1:1
            # draw (typical "Match window size" mode).
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, self._image, self._image.rect())

    def sizeHint(self):
        if self._image is not None:
            return self._image.size()
        return super().sizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # A fixed desktop_size never changes after connect — window
        # resizes just restretch the existing image (see paintEvent), no
        # server round trip needed or wanted.
        if self._desktop_size is None:
            self._resize_debounce.start()

    def _target_size(self) -> tuple[int, int]:
        return self._desktop_size if self._desktop_size is not None else (self.width(), self.height())

    def _send_resize_request(self) -> None:
        self._worker.request_resize(*self._target_size())

    def refresh_resolution(self) -> None:
        """Re-sends the current target size to the server even though it
        hasn't changed -- for when the remote desktop's resolution has
        drifted out of sync without a real resize event to trigger a fix
        (e.g. after the server's own display state changed, like a UAC
        prompt or a lock-screen transition). Exposed as a manual "Refresh
        Resolution" action on the session tab's context menu;
        request_resize() has no deduplication of its own, so this always
        sends, unlike the debounced resizeEvent path.
        """
        self._send_resize_request()

    def close_session(self) -> None:
        """Matches the close_session() convention main_view uses to tear
        down any session tab (terminal, bucket browser, ...) uniformly."""
        self._closing = True
        # QApplication.clipboard() outlives this widget (process-wide
        # singleton) -- unlike every other signal source this widget
        # listens to, which dies with its own RdpSessionWorker, a dangling
        # connection here would leak and could call into a half-destroyed
        # widget on the next local copy.
        try:
            QApplication.clipboard().dataChanged.disconnect(self._on_local_clipboard_changed)
        except (TypeError, RuntimeError):
            pass
        self._worker.stop()

    # --- input: widget-space -> remote desktop-space, then forwarded ----

    def _remote_pos(self, widget_pos) -> tuple[int, int]:
        if self._image is None or self.width() == 0 or self.height() == 0:
            return int(widget_pos.x()), int(widget_pos.y())
        target = self._scaled_image_rect()
        if target.width() == 0 or target.height() == 0:
            return 0, 0
        scale_x = self._image.width() / target.width()
        scale_y = self._image.height() / target.height()
        x = (widget_pos.x() - target.x()) * scale_x
        y = (widget_pos.y() - target.y()) * scale_y
        # Clicks landing in the letterbox bars clamp to the nearest edge
        # of the image rather than mapping to a negative/out-of-range
        # remote coordinate.
        x = max(0, min(x, self._image.width() - 1))
        y = max(0, min(y, self._image.height() - 1))
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

    def event(self, e) -> bool:  # noqa: N802 - Qt override signature
        # Qt's default QWidget::event() intercepts Tab/Shift+Tab
        # (Key_Backtab) at this level to cycle keyboard focus between
        # widgets *before* keyPressEvent() ever sees them -- StrongFocus
        # alone doesn't disable that. Left unhandled, pressing Tab in the
        # remote session can silently move local focus away from this
        # widget instead of forwarding the keystroke, and once that
        # happens every subsequent keystroke (Shift+key combos included)
        # goes to whatever local widget focus landed on instead of the
        # remote session -- until a click brings focus back here. Forward
        # these directly and report the event as handled so Qt's own
        # focus-traversal never runs.
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
        modifiers = event.modifiers()

        # REVERTED: routing printable keys through send_key_unicode (RDP's
        # "Unicode" keyboard input, which Windows synthesizes as a
        # VK_PACKET key event) broke typing in PowerShell/cmd *entirely* --
        # not just Shift+symbol. Windows console input is built around real
        # scancode events; VK_PACKET is a documented weak spot for raw
        # console input specifically (unlike GUI controls, which handle it
        # fine via WM_CHAR). So scancode has to stay the primary path for
        # everything with a SCANCODES entry, unicode only as the true
        # fallback for characters with no dedicated Qt key constant at all
        # -- back to this file's original shape. The actual Shift+symbol-
        # in-console bug (confirmed real, and still open) needs a different
        # fix than swapping the transport.
        scancode = SCANCODES.get(key)
        if scancode is not None:
            code, extended = scancode
            logger.debug(
                "key %s modifiers=%s -> scancode=0x%02X extended=%s down=%s",
                key, modifiers, code, extended, down,
            )
            self._worker.send_key_scancode(code, extended, down)
            return
        text = event.text()
        for char in text:
            if char.isprintable():
                logger.debug(
                    "key %s modifiers=%s -> unicode=%r down=%s", key, modifiers, char, down
                )
                self._worker.send_key_unicode(ord(char), down)

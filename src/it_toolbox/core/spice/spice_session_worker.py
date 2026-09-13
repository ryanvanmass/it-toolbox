"""Bridges SpiceSession's GLib-driven connection onto a plain thread and a
Qt-signal interface — same split as core/rdp/rdp_session_worker.py.

Unlike RdpSessionWorker (which pumps FreeRDP's own socket itself in a
loop on this thread), spice-glib already does all of its I/O internally
via a GLib main loop — so this thread's only job is to own a
GLib.MainLoop and run it for the life of the connection, translating
SpiceSession's callbacks into Qt signals as they fire. Those callbacks
run on whatever thread runs the loop — i.e. this one — so .emit() here
is exactly analogous to RdpSessionWorker._on_frame: never called from the
Qt thread directly, always crossing over via a queued signal emission.

Connecting is kicked off via SpiceSession.start_connecting() (a
non-blocking call), not the blocking SpiceSession.connect() convenience
wrapper the CLI smoke tests use — this thread is about to become the one
running the loop that SpiceSession's own blocking wait depends on, so
calling connect() here would deadlock (see its docstring).

Input (send_mouse_*/send_key_scancode) is safe to call from the Qt
thread — each call is marshaled onto the loop thread via GLib.idle_add(),
which is thread-safe by design (unlike RdpSessionWorker's hand-rolled
queue-plus-polling approach, needed there because FreeRDP's pump loop has
no built-in cross-thread scheduling primitive of its own; spice-glib's
GLib main loop already does).

send_mouse_move specifically coalesces bursts instead of calling
idle_add() once per Qt mouseMoveEvent -- a real, measured-to-matter
difference from a native (non-Python) SPICE client: every idle_add()
call here is a Python-GIL cross-thread handoff, and this process is
Python end to end (PySide6 + PyGObject), unlike e.g. virt-viewer, a
single native GTK+spice-gtk process with no GIL to contend for at all.
Dragging something in the guest is exactly the scenario that floods this
thread with mouseMoveEvents while the GLib loop thread is simultaneously
trying to decode incoming display data and emit frames -- see
send_mouse_move's own docstring below.
"""

import threading
import time

from gi.repository import GLib
from PySide6.QtCore import QObject, Signal

from it_toolbox.core.spice.spice_session import SpiceError, SpiceSession

# Caps how often a display-invalidate burst (video, scrolling, animation,
# dragging a window -- anything that redraws faster than a human needs to
# see it) actually triggers a real frame capture, on top of get_dirty_band()
# already limiting each capture to just the rows that changed (see that
# method's docstring) -- a busy guest can still fire display-invalidate far
# faster than any display needs, each one otherwise forcing a Qt repaint
# downstream. 60fps (matching a typical display's own refresh rate) is
# affordable now that both the copy and the repaint below are scoped to the
# dirty band rather than the whole surface -- see _on_frame's docstring for
# how the trailing-edge timeout guarantees the *latest* frame is never
# dropped, only redundant intermediate captures are skipped.
_TARGET_FRAME_INTERVAL_SEC = 1 / 60


class SpiceSessionSignals(QObject):
    # pixels (BGRX) for rows [band_top, band_top + band_height) of the full
    # canvas_width x canvas_height surface -- see SpiceSession.get_dirty_band()
    frame_ready = Signal(bytes, int, int, int, int, int)  # pixels, band_top, band_height, canvas_width, canvas_height, stride
    connected = Signal()
    error = Signal(str)
    disconnected = Signal()


class SpiceSessionWorker:
    """One SPICE session, driven by its own GLib.MainLoop on a dedicated
    background thread until stop() is called or the connection is lost.
    """

    def __init__(self, host: str, port: int, password: str = "") -> None:
        self._host = host
        self._port = port
        self._password = password
        self.signals = SpiceSessionSignals()
        self._session = SpiceSession()
        self._loop: GLib.MainLoop | None = None
        self._thread: threading.Thread | None = None
        self._last_emit_at = 0.0
        self._frame_timeout_pending = False
        self._pending_mouse_pos: tuple[int, int] | None = None
        self._mouse_move_idle_scheduled = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Safe to call from any thread. Blocks until the worker thread
        has actually torn the connection down."""
        self._session.disconnect()
        if self._loop is not None:
            self._loop.quit()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # --- input — safe to call from the Qt thread ------------------------

    def send_mouse_move(self, x: int, y: int) -> None:
        """Coalesces a burst of mouseMoveEvents (dragging something in the
        guest generates a lot of these) into at most one pending
        GLib.idle_add() at a time, instead of one idle_add() per event.
        Only the most recent position is ever "lost" by coalescing --
        exactly like the frame-capture throttle, nothing here needs the
        pointer's full path, only where it ends up next. This runs on the
        Qt thread; `_mouse_move_idle_scheduled` is also read/written from
        the GLib loop thread inside _flush_mouse_move() below, but the
        only possible race is a redundant extra idle_add() slipping
        through occasionally (harmless -- it just re-sends the same/a
        very close position) or, at worst, one coalescing opportunity
        missed -- never a lost update, since `_pending_mouse_pos` always
        holds the latest position and _flush_mouse_move() always sends
        whatever's currently there.
        """
        self._pending_mouse_pos = (x, y)
        if not self._mouse_move_idle_scheduled:
            self._mouse_move_idle_scheduled = True
            GLib.idle_add(self._flush_mouse_move)

    def _flush_mouse_move(self) -> bool:
        self._mouse_move_idle_scheduled = False
        pos = self._pending_mouse_pos
        if pos is not None:
            self._session.send_mouse_move(*pos)
        return GLib.SOURCE_REMOVE

    def send_mouse_button(self, button: str, down: bool) -> None:
        GLib.idle_add(self._session.send_mouse_button, button, down)

    def send_mouse_wheel(self, steps: int) -> None:
        GLib.idle_add(self._session.send_mouse_wheel, steps)

    def send_key_scancode(self, code: int, extended: bool, down: bool) -> None:
        GLib.idle_add(self._session.send_key_scancode, code, extended, down)

    def send_resize(self, width: int, height: int) -> None:
        """Not coalesced like send_mouse_move -- SpiceWidget already
        debounces this itself (only calling it once a resize has
        settled), so calls here are already infrequent."""
        GLib.idle_add(self._session.request_resize, width, height)

    def _run(self) -> None:
        self._loop = GLib.MainLoop()
        self._session.on_frame = self._on_frame
        self._session.on_connected = self.signals.connected.emit
        self._session.on_error = self._on_session_error
        self._session.on_disconnected = self._quit_loop

        try:
            self._session.start_connecting(self._host, self._port, self._password)
        except SpiceError as exc:
            self.signals.error.emit(str(exc))
            return

        self._loop.run()  # returns once stop()/an error/a server disconnect calls quit()
        self.signals.disconnected.emit()

    def _on_session_error(self, error: SpiceError) -> None:
        self.signals.error.emit(str(error))
        self._quit_loop()

    def _quit_loop(self) -> None:
        if self._loop is not None:
            self._loop.quit()

    def _on_frame(self) -> None:
        # Runs on this thread (the one running the GLib main loop), once per
        # display-primary-create/display-invalidate signal -- which can fire
        # much faster than _TARGET_FRAME_INTERVAL_SEC on a busy guest
        # desktop. Trailing-edge throttle: if the last real capture was
        # recent enough, just schedule one timeout for whenever the
        # interval actually elapses rather than capturing again right now
        # -- further invalidates before that timeout fires are free (the
        # `_frame_timeout_pending` guard skips scheduling a second one).
        # Everything here runs on this same GLib loop thread, so there's no
        # race between "pending" being set and the timeout callback running.
        # The timeout always captures whatever the *live* framebuffer looks
        # like at that moment (get_dirty_band() has no notion of a queued/
        # stale frame -- it reads straight from the current surface), so
        # the guest's actual latest state is never lost or delayed by more
        # than one interval -- only the redundant intermediate captures are
        # skipped. Every raw invalidate in between still contributes its
        # row range to SpiceSession's own accumulated dirty-row tracking
        # (see get_dirty_band()'s docstring), so no *area* is lost either --
        # only the redundant number of captures is reduced.
        now = time.monotonic()
        remaining = _TARGET_FRAME_INTERVAL_SEC - (now - self._last_emit_at)
        if remaining <= 0:
            self._emit_frame()
        elif not self._frame_timeout_pending:
            self._frame_timeout_pending = True
            GLib.timeout_add(int(remaining * 1000), self._on_frame_timeout)

    def _on_frame_timeout(self) -> bool:
        self._frame_timeout_pending = False
        self._emit_frame()
        return GLib.SOURCE_REMOVE  # one-shot, not repeating

    def _emit_frame(self) -> None:
        self._last_emit_at = time.monotonic()
        try:
            pixels, band_top, band_height, canvas_width, canvas_height, stride = self._session.get_dirty_band()
        except SpiceError:
            # The primary surface can be torn down (e.g. a guest resolution
            # change, or disconnect) between the invalidate that scheduled
            # this and the timeout actually firing -- nothing to paint.
            return
        if band_height <= 0:
            return
        self.signals.frame_ready.emit(pixels, band_top, band_height, canvas_width, canvas_height, stride)

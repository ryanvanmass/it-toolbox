"""Bridges FreeRdpSession's blocking pump loop onto a plain thread and a
Qt-signal interface, the same split used for the IAP tunnel
(core/tunnel_session.py): the connection/pump logic stays Qt-free and
thread-owning here, and a widget only ever touches it through signals.

RdpSessionSignals is a QObject created on (and living on) the Qt/GUI
thread; the background thread only ever calls .emit() on it. Qt's queued
connections make that emit() safe across threads on their own — this is
the standard, supported pattern, distinct from the QThreadPool/QRunnable
autoDelete pitfall documented in async_utils.py (that one was about
cross-thread *object deletion*, not signal emission).
"""

import queue
import threading
import time

from PySide6.QtCore import QObject, Signal

from it_toolbox.core.rdp.freerdp_client import KEYBOARD_LAYOUT_ENGLISH_US, FreeRdpSession, WakeEvent

# How long the pump waits for network or input activity before looping
# anyway -- the same idle timeout xfreerdp's own main loop uses. Anything
# that needs the loop sooner sets _wake instead of relying on this.
_IDLE_WAIT_MS = 100

# Frames are delivered at most this often (~60 fps). Waiting for the
# previous frame to be painted isn't a cap on its own: nothing ties a
# QWidget repaint to the display's refresh, so a busy session could
# otherwise be copied and repainted a few hundred times a second.
_MIN_FRAME_INTERVAL = 1 / 60


class RdpSessionSignals(QObject):
    frame_ready = Signal(bytes, int, int, int)  # pixels (BGRX), width, height, stride
    connected = Signal()
    error = Signal(str)
    disconnected = Signal()


class RdpSessionWorker:
    """One RDP session, pumped on a dedicated background thread until
    stop() is called or the connection is lost.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        domain: str = "",
        desktop_size: tuple[int, int] | None = None,
        keyboard_layout: int = KEYBOARD_LAYOUT_ENGLISH_US,
        shared_folder: str | None = None,
        graphics_pipeline: bool = False,
        h264: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._domain = domain
        self._desktop_size = desktop_size
        self._keyboard_layout = keyboard_layout
        self._shared_folder = shared_folder
        self._graphics_pipeline = graphics_pipeline
        self._h264 = h264
        self.signals = RdpSessionSignals()
        self._session = FreeRdpSession()
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._got_frame = False  # set from the session thread by _on_frame
        # Input events arrive on the Qt thread but libfreerdp expects a
        # session to be driven from a single thread — queue them here and
        # apply them from _run()'s own loop, same thread as pump_once().
        self._input_queue: queue.Queue = queue.Queue()
        # Interrupts the pump's wait (see _run) whenever there's input to
        # send, a frame to deliver, or a stop to act on.
        self._wake = WakeEvent()
        # Frames are copied out of the GDI surface at most once per pump
        # pass, and only once the GUI has taken the previous one: EndPaint
        # can fire many times per pass (once per graphics-pipeline
        # surface), each full copy is width*height*4 bytes, and the GUI
        # thread only ever shows the newest anyway. Without this, a GUI
        # that falls behind gets an ever-growing backlog of stale
        # full-screen copies queued up -- more lag and memory, not more
        # frames.
        self._frame_dirty = False
        self._frame_in_flight = threading.Event()
        self._last_frame_at = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Safe to call from any thread. Blocks until the worker thread
        has actually torn the connection down."""
        self._stop_requested.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # --- input — safe to call from the Qt thread ------------------------

    def send_mouse_move(self, x: int, y: int) -> None:
        self._queue_input(("mouse_move", x, y))

    def send_mouse_button(self, x: int, y: int, button: str, down: bool) -> None:
        self._queue_input(("mouse_button", x, y, button, down))

    def send_mouse_wheel(self, x: int, y: int, delta_steps: int) -> None:
        self._queue_input(("mouse_wheel", x, y, delta_steps))

    def send_key_scancode(self, code: int, extended: bool, down: bool) -> None:
        self._queue_input(("key_scancode", code, extended, down))

    def send_key_unicode(self, codepoint: int, down: bool) -> None:
        self._queue_input(("key_unicode", codepoint, down))

    def request_resize(self, width: int, height: int) -> None:
        """Safe to call from the Qt thread. Caller (RdpWidget) is
        responsible for debouncing — this queues one resize request per
        call with no coalescing of its own."""
        self._queue_input(("resize", width, height))

    def send_clipboard_text(self, text: str | None) -> None:
        """Safe to call from the Qt thread. Announces the local
        clipboard's text content to the remote session — call whenever the
        local clipboard changes."""
        self._queue_input(("clipboard_text", text))

    def frame_consumed(self) -> None:
        """Safe to call from the Qt thread. Call once a frame_ready frame
        has been taken, so the next one can be sent (see _frame_dirty)."""
        self._frame_in_flight.clear()
        self._wake.set()

    def _queue_input(self, event: tuple) -> None:
        self._input_queue.put(event)
        self._wake.set()

    def _drain_input_queue(self) -> None:
        # Consecutive mouse moves collapse into the last one: only where
        # the pointer ended up matters, and a high-rate mouse can queue
        # far more moves per pump pass than are worth sending.
        pending_move = None
        while True:
            try:
                event = self._input_queue.get_nowait()
            except queue.Empty:
                break
            kind, *args = event
            if kind == "mouse_move":
                pending_move = args
                continue
            if pending_move is not None:
                self._session.send_mouse_move(*pending_move)
                pending_move = None
            if kind == "mouse_button":
                self._session.send_mouse_button(*args)
            elif kind == "mouse_wheel":
                self._session.send_mouse_wheel(*args)
            elif kind == "key_scancode":
                self._session.send_key_scancode(*args)
            elif kind == "key_unicode":
                self._session.send_key_unicode(*args)
            elif kind == "resize":
                self._session.request_resize(*args)
            elif kind == "clipboard_text":
                self._session.announce_clipboard_text(*args)
        if pending_move is not None:
            self._session.send_mouse_move(*pending_move)

    def _run(self) -> None:
        self._session.on_frame = self._on_frame
        try:
            self._session.connect(
                self._host,
                self._port,
                self._username,
                self._password,
                domain=self._domain,
                desktop_size=self._desktop_size,
                keyboard_layout=self._keyboard_layout,
                shared_folder=self._shared_folder,
                graphics_pipeline=self._graphics_pipeline,
                h264=self._h264,
            )
        except Exception as exc:  # noqa: BLE001 - see comment below
            # Deliberately broader than FreeRdpError: an uncaught exception
            # on this background thread has nothing to propagate to — it
            # just kills the thread silently, leaving the widget stuck on
            # "Connecting…" forever with no signal ever emitted and no
            # visible error. That's a strictly worse failure mode than
            # showing a slightly-less-tailored message for something
            # unanticipated (e.g. a ctypes marshaling mistake), so anything
            # unexpected here still surfaces rather than vanishing.
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
            self._wake.close()
            return

        self.signals.connected.emit()
        try:
            while not self._stop_requested.is_set():
                # Reset before draining, so anything queued from here on
                # sets it again and cuts the wait below short.
                self._wake.reset()
                self._drain_input_queue()
                if not self._session.pump_once():
                    if not self._got_frame:
                        # The session ended before showing anything, so to
                        # the user it failed; say why if FreeRDP knows.
                        reason = self._session.last_error_text()
                        if reason:
                            self.signals.error.emit(
                                f"The connection closed before the remote desktop appeared: {reason}"
                            )
                    break
                wait_ms = self._deliver_frame()
                # freerdp_check_event_handles() is non-blocking, so the loop
                # needs pacing -- this waits on FreeRDP's own handles (and
                # _wake) rather than a fixed sleep, so incoming data is
                # handled as soon as it arrives and an idle session costs
                # next to no CPU.
                self._session.wait_for_activity(wait_ms, self._wake)
        except Exception as exc:  # noqa: BLE001 - see comment above
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._session.disconnect()
            self._wake.close()
            self.signals.disconnected.emit()

    def _on_frame(self) -> None:
        # May run on one of FreeRDP's own threads (see
        # FreeRdpSession._on_end_paint) -- only flags the frame, and wakes
        # the session thread to deliver it.
        self._got_frame = True
        self._frame_dirty = True
        self._wake.set()

    def _deliver_frame(self) -> int:
        """Sends the pending frame if there is one and it's due; returns
        how long the pump may wait before it should be called again."""
        if not self._frame_dirty or self._frame_in_flight.is_set():
            return _IDLE_WAIT_MS
        due_in = self._last_frame_at + _MIN_FRAME_INTERVAL - time.monotonic()
        if due_in > 0:
            return max(1, int(due_in * 1000))
        self._frame_dirty = False
        self._frame_in_flight.set()
        self._last_frame_at = time.monotonic()
        # Runs on the background thread — reads the ctypes GDI surface here
        # (same thread that owns the connection) and hands plain bytes
        # across via emit(), never a raw pointer.
        pixels, width, height, stride = self._session.get_frame()
        self.signals.frame_ready.emit(pixels, width, height, stride)
        return _IDLE_WAIT_MS

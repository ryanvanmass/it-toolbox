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
"""

import threading

from gi.repository import GLib
from PySide6.QtCore import QObject, Signal

from it_toolbox.core.spice.spice_session import SpiceError, SpiceSession


class SpiceSessionSignals(QObject):
    frame_ready = Signal(bytes, int, int, int)  # pixels (BGRX), width, height, stride
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
        # Runs on this thread (the one running the GLib main loop) — reads
        # the shared pixel buffer here and hands plain bytes across via
        # emit(), never the raw pointer.
        pixels, width, height, stride = self._session.get_frame()
        self.signals.frame_ready.emit(pixels, width, height, stride)

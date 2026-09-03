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

import threading
import time

from PySide6.QtCore import QObject, Signal

from it_toolbox.core.rdp.freerdp_client import FreeRdpError, FreeRdpSession


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
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._domain = domain
        self.signals = RdpSessionSignals()
        self._session = FreeRdpSession()
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Safe to call from any thread. Blocks until the worker thread
        has actually torn the connection down."""
        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        self._session.on_frame = self._on_frame
        try:
            self._session.connect(
                self._host, self._port, self._username, self._password, domain=self._domain
            )
        except FreeRdpError as exc:
            self.signals.error.emit(str(exc))
            return

        self.signals.connected.emit()
        try:
            while not self._stop_requested.is_set():
                if not self._session.pump_once():
                    break
                # freerdp_check_event_handles() is non-blocking — it processes
                # whatever's ready and returns immediately, so this loop needs
                # its own pacing or it busy-spins a full CPU core. 5ms keeps
                # polling well above any useful frame rate at a small,
                # bounded CPU cost.
                time.sleep(0.005)
        except FreeRdpError as exc:
            self.signals.error.emit(str(exc))
        finally:
            self._session.disconnect()
            self.signals.disconnected.emit()

    def _on_frame(self) -> None:
        # Runs on the background thread — reads the ctypes GDI surface here
        # (same thread that owns the connection) and hands plain bytes
        # across via emit(), never a raw pointer.
        pixels, width, height, stride = self._session.get_frame()
        self.signals.frame_ready.emit(pixels, width, height, stride)

"""Bridges the asyncio-based IapTunnelConnection/TunnelManager onto a plain
thread so it can be started/stopped from Qt without Qt needing to know
anything about asyncio.
"""

import asyncio
import threading

from it_toolbox.core.iap_tunnel import GetAccessToken, IapTunnelTarget, TunnelManager


class BackgroundTunnel:
    """One IAP tunnel, running its own asyncio event loop on a dedicated
    background thread for as long as the session is connected.
    """

    def __init__(self, target: IapTunnelTarget, get_access_token: GetAccessToken) -> None:
        self._target = target
        self._get_access_token = get_access_token
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._serve_task: asyncio.Task | None = None
        self._port: int | None = None
        self._error: Exception | None = None
        self._ready = threading.Event()

    @property
    def port(self) -> int | None:
        """The bound local port, or None before start() has completed."""
        return self._port

    def start(self, timeout: float = 30) -> int:
        """Start the tunnel and block until its local port is bound.

        Call from a background (worker-pool) thread, never the Qt main
        thread — this blocks on tunnel startup.
        """
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        if not self._ready.wait(timeout):
            raise TimeoutError(f"Timed out after {timeout}s waiting for the local tunnel port")
        if self._error is not None:
            raise self._error
        assert self._port is not None
        return self._port

    def stop(self, timeout: float = 5) -> None:
        """Tear down the tunnel. Safe to call from any thread."""
        if self._loop is not None and self._serve_task is not None:
            self._loop.call_soon_threadsafe(self._serve_task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        manager = TunnelManager(self._target, self._get_access_token)
        try:
            self._port = self._loop.run_until_complete(manager.start())
            self._ready.set()
            self._serve_task = self._loop.create_task(manager.serve_forever())
            self._loop.run_until_complete(self._serve_task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 - surfaced to start()'s caller
            self._error = exc
            self._ready.set()
        finally:
            self._loop.close()

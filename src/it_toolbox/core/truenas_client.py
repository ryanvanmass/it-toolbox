"""TrueNAS's JSON-RPC 2.0 API over a websocket (wss://<host>/api/current),
logged in with a user-linked API key. TrueNAS 25.04 and later only: the
older REST API is deprecated and due to be removed, and /api/current
doesn't exist before 25.04.

No Qt here. A TrueNasConnection is one websocket plus a reader thread
that hands each reply to whichever call is waiting for its id, and each
event (core.subscribe) to its subscriber -- so several background calls
from one dashboard can be in flight on one connection at once.

Self-signed certificates are pinned the same way as core/pinned_tls's
requests sessions: the socket skips CA checks, and the certificate's
SHA-256 is compared with the trusted fingerprint before the API key is
ever sent.
"""

from __future__ import annotations

import itertools
import json
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidURI, WebSocketException
from websockets.sync.client import connect as ws_connect

from it_toolbox.core import pinned_tls

#: Oldest release with the versioned JSON-RPC endpoint.
MIN_VERSION = (25, 4)
CALL_TIMEOUT_SEC = 30
CONNECT_TIMEOUT_SEC = 15
JOB_POLL_SEC = 1.0
#: pool.query with a big topology, or a long app list, easily passes
#: websockets' 1 MiB default.
MAX_MESSAGE_BYTES = 64 * 1024 * 1024

JOB_DONE_STATES = {"SUCCESS", "FAILED", "ABORTED"}


class TrueNasError(Exception):
    """Anything that went wrong talking to a NAS, worded for the user."""


class TrueNasAuthError(TrueNasError):
    """The API key was refused (wrong, revoked, or expired)."""


class TrueNasUnsupportedError(TrueNasError):
    """The NAS is older than 25.04, or isn't TrueNAS at all."""


class TrueNasApiError(TrueNasError):
    """A method call failed on the NAS. `errname` is the middleware's own
    name for it (ENOENT, EPERM, ...) when it sends one."""

    def __init__(self, method: str, message: str, errname: str = "", code: int | None = None) -> None:
        super().__init__(message)
        self.method = method
        self.errname = errname
        self.code = code

    @property
    def is_permission_error(self) -> bool:
        return self.errname in {"EACCES", "EPERM"} or "not authorized" in str(self).lower()

    @property
    def is_method_missing(self) -> bool:
        return self.code == -32601 or "method does not exist" in str(self).lower()


class TrueNasJobError(TrueNasError):
    """A job ended FAILED or ABORTED. `job` is its last core.get_jobs entry."""

    def __init__(self, message: str, job: dict) -> None:
        super().__init__(message)
        self.job = job


def websocket_url(url: str) -> str:
    """"https://nas.lan:443" -> "wss://nas.lan:443/api/current"."""
    parts = urlsplit(url)
    scheme = "ws" if parts.scheme == "http" else "wss"
    return f"{scheme}://{parts.netloc}/api/current"


def parse_version(text: str) -> tuple[int, int] | None:
    """"TrueNAS-25.04.2.1" / "25.10.0" -> (25, 4) / (25, 10)."""
    match = re.search(r"(\d+)\.(\d+)", text or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def _error_message(error: dict) -> tuple[str, str]:
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    reason = data.get("reason") or error.get("message") or "Unknown error"
    extra = data.get("extra")
    # Validation errors carry [[field, message, errno], ...] -- the field
    # names are what tell the user what to fix.
    if isinstance(extra, list) and extra and all(isinstance(e, list) and len(e) >= 2 for e in extra):
        reason = "; ".join(f"{e[0]}: {e[1]}" for e in extra)
    return str(reason).strip(), str(data.get("errname") or "")


class _Pending:
    __slots__ = ("done", "result", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Any = None
        self.error: Exception | None = None


class TrueNasConnection:
    """One logged-in websocket to one NAS. Open with open(); every method
    is safe to call from any thread."""

    def __init__(
        self,
        url: str,
        api_key: str,
        verify_ssl: bool = False,
        fingerprint: str | None = None,
        connect: Callable[..., Any] = ws_connect,
    ) -> None:
        self.url = url
        self._api_key = api_key
        self._verify_ssl = verify_ssl
        self._fingerprint = fingerprint
        self._connect = connect
        self._ws = None
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._subscribers: dict[str, list[Callable[[str, dict], None]]] = {}
        self._subscription_ids: dict[str, Any] = {}
        self._reader: threading.Thread | None = None
        self._closed_error: TrueNasError | None = None
        self.version: tuple[int, int] | None = None
        self.system_info: dict = {}

    def __repr__(self) -> str:  # never the key
        return f"TrueNasConnection({self.url!r})"

    # -- Connecting --------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._ws is not None and self._closed_error is None

    def open(self) -> "TrueNasConnection":
        if not self._verify_ssl and not self._fingerprint and urlsplit(self.url).scheme != "http":
            raise TrueNasError(f"No pinned certificate fingerprint for {self.url}.")
        if urlsplit(self.url).scheme == "http":
            # TrueNAS revokes an API key that's ever sent in the clear.
            raise TrueNasError("TrueNAS API keys must only be sent over HTTPS -- use an https:// URL.")
        try:
            # Entered by hand: newer websockets releases want connect() used
            # as a context manager, older ones return the connection itself
            # (whose __enter__ returns itself) -- this works with both.
            self._ws = self._connect(
                websocket_url(self.url),
                ssl=pinned_tls.ssl_context_for(self._verify_ssl),
                open_timeout=CONNECT_TIMEOUT_SEC,
                max_size=MAX_MESSAGE_BYTES,
            ).__enter__()
        except InvalidStatus as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status in (404, 405):
                raise TrueNasUnsupportedError(
                    f"{self.url} has no /api/current endpoint. The TrueNAS tool needs TrueNAS 25.04 or later."
                ) from error
            raise TrueNasError(f"{self.url} refused the websocket (HTTP {status}).") from error
        except (OSError, InvalidURI, WebSocketException, TimeoutError) as error:
            raise TrueNasError(f"Couldn't connect to {self.url}: {error}") from error

        try:
            self._check_fingerprint()
        except Exception:
            self._ws.close()
            self._ws = None
            raise
        self._closed_error = None
        self._reader = threading.Thread(target=self._read_loop, name="truenas-reader", daemon=True)
        self._reader.start()

        try:
            self._login()
            self.system_info = self.call("system.info") or {}
        except Exception:
            self.close()
            raise
        self.version = parse_version(str(self.system_info.get("version", "")))
        if self.version is not None and self.version < MIN_VERSION:
            self.close()
            raise TrueNasUnsupportedError(
                f"{self.url} runs TrueNAS {self.system_info.get('version')}; the TrueNAS tool needs 25.04 or later."
            )
        return self

    def _check_fingerprint(self) -> None:
        if self._verify_ssl:
            return
        sock = getattr(self._ws, "socket", None)
        der = sock.getpeercert(binary_form=True) if sock is not None else None
        if not der:
            raise TrueNasError(f"Couldn't read the certificate {self.url} presented.")
        actual = pinned_tls.fingerprint_of(der)
        if pinned_tls.normalize_fingerprint(actual) != pinned_tls.normalize_fingerprint(self._fingerprint or ""):
            raise pinned_tls.CertificateMismatchError(self.url, self._fingerprint or "", actual)

    def _login(self) -> None:
        """The one place that knows how to log in, so a newer login method
        (TrueNAS 26 is expected to retire this one) is a one-line change."""
        try:
            ok = self.call("auth.login_with_api_key", self._api_key)
        except TrueNasApiError as error:
            raise TrueNasAuthError(f"{self.url} refused the API key: {error}") from error
        if not ok:
            raise TrueNasAuthError(f"{self.url} refused the API key. It may be wrong, revoked or expired.")

    def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001 - already gone is fine
                pass
        self._fail_pending(TrueNasError("The connection was closed."))

    # -- Reader thread -------------------------------------------------------

    def _read_loop(self) -> None:
        ws = self._ws
        try:
            while ws is not None:
                raw = ws.recv()
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(message, dict):
                    self._dispatch(message)
        except ConnectionClosed:
            self._fail_pending(TrueNasError(f"The connection to {self.url} closed."))
        except Exception as error:  # noqa: BLE001 - reported to every waiting call
            self._fail_pending(TrueNasError(f"The connection to {self.url} failed: {error}"))

    def _dispatch(self, message: dict) -> None:
        if "id" in message and ("result" in message or "error" in message):
            with self._lock:
                pending = self._pending.pop(message["id"], None)
            if pending is None:
                return
            if "error" in message and message["error"] is not None:
                error = message["error"] if isinstance(message["error"], dict) else {"message": str(message["error"])}
                text, errname = _error_message(error)
                pending.error = TrueNasApiError("", text, errname, error.get("code"))
            else:
                pending.result = message.get("result")
            pending.done.set()
            return
        params = message.get("params")
        if message.get("method") == "collection_update" and isinstance(params, dict):
            collection = str(params.get("collection") or "")
            with self._lock:
                callbacks = [
                    cb
                    for name, cbs in self._subscribers.items()
                    if collection == name or name.startswith(collection + ":") or collection.startswith(name)
                    for cb in cbs
                ]
            for callback in callbacks:
                try:
                    callback(str(params.get("msg") or ""), params.get("fields") or {})
                except Exception:  # noqa: BLE001 - one bad subscriber mustn't kill the reader
                    pass

    def _fail_pending(self, error: TrueNasError) -> None:
        with self._lock:
            if self._closed_error is None:
                self._closed_error = error
            pending, self._pending = self._pending, {}
        for item in pending.values():
            item.error = error
            item.done.set()

    # -- Calls -----------------------------------------------------------------

    def call(self, method: str, *params: Any, timeout: float = CALL_TIMEOUT_SEC) -> Any:
        if self._ws is None:
            raise TrueNasError("Not connected.")
        pending = _Pending()
        with self._lock:
            if self._closed_error is not None:
                raise self._closed_error
            request_id = next(self._ids)
            self._pending[request_id] = pending
        try:
            self._ws.send(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": list(params)}))
        except (ConnectionClosed, OSError) as error:
            with self._lock:
                self._pending.pop(request_id, None)
            raise TrueNasError(f"The connection to {self.url} closed.") from error
        if not pending.done.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            raise TrueNasError(f"{method} timed out after {timeout:.0f} seconds.")
        if pending.error is not None:
            if isinstance(pending.error, TrueNasApiError):
                pending.error.method = method
            raise pending.error
        return pending.result

    def call_job(
        self,
        method: str,
        *params: Any,
        on_progress: Callable[[int, str], None] | None = None,
        timeout: float = 3600,
    ) -> Any:
        """Calls a job method and waits for the job to finish, reporting
        (percent, description) as it goes. Returns the job's result."""
        job_id = self.call(method, *params)
        if not isinstance(job_id, int):
            return job_id  # not a job after all on this release
        return self.wait_job(job_id, on_progress=on_progress, timeout=timeout)

    def wait_job(self, job_id: int, on_progress=None, timeout: float = 3600) -> Any:
        deadline = time.monotonic() + timeout
        last = None
        while True:
            jobs = self.call("core.get_jobs", [["id", "=", job_id]])
            job = jobs[0] if jobs else {}
            progress = job.get("progress") or {}
            report = (int(progress.get("percent") or 0), str(progress.get("description") or ""))
            if on_progress is not None and report != last:
                on_progress(*report)
                last = report
            state = job.get("state")
            if state in JOB_DONE_STATES:
                if state != "SUCCESS":
                    message = job.get("error") or f"Job {job_id} ended {state}."
                    raise TrueNasJobError(str(message).strip(), job)
                return job.get("result")
            if not job:
                raise TrueNasError(f"Job {job_id} disappeared.")
            if time.monotonic() > deadline:
                raise TrueNasError(f"Job {job_id} didn't finish in {timeout:.0f} seconds.")
            time.sleep(JOB_POLL_SEC)

    # -- Events ----------------------------------------------------------------

    def subscribe(self, name: str, callback: Callable[[str, dict], None]) -> Callable[[], None]:
        """core.subscribe(name); callback(msg, fields) runs on the reader
        thread for each event. Returns an unsubscribe function."""
        with self._lock:
            first = name not in self._subscribers
            self._subscribers.setdefault(name, []).append(callback)
        if first:
            try:
                self._subscription_ids[name] = self.call("core.subscribe", name)
            except Exception:
                with self._lock:
                    self._subscribers.pop(name, None)
                raise

        def unsubscribe() -> None:
            with self._lock:
                callbacks = self._subscribers.get(name, [])
                if callback in callbacks:
                    callbacks.remove(callback)
                last = not callbacks and name in self._subscribers
                if last:
                    del self._subscribers[name]
            subscription_id = self._subscription_ids.pop(name, None) if last else None
            if subscription_id is not None and self.is_open:
                try:
                    self.call("core.unsubscribe", subscription_id, timeout=5)
                except TrueNasError:
                    pass

        return unsubscribe


def open_connection(url: str, api_key: str, verify_ssl: bool, fingerprint: str | None) -> TrueNasConnection:
    return TrueNasConnection(url, api_key, verify_ssl, fingerprint).open()


def test_connection(url: str, api_key: str, verify_ssl: bool, fingerprint: str | None) -> str:
    """One line for the add-host dialog, e.g. "TrueNAS 25.04.2, nas01"."""
    connection = open_connection(url, api_key, verify_ssl, fingerprint)
    try:
        info = connection.system_info
        return f"TrueNAS {info.get('version', '?')}, {info.get('hostname', '?')}"
    finally:
        connection.close()

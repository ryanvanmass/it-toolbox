"""Load generator behind the SFTP Server Test tool (General Tools): N
concurrent workers, each on its own SFTP connection, continuously perform
random file operations against a server until stopped, while the tab polls
a shared StressStats for live numbers.

Everything happens inside one freshly created test folder
(`it-toolbox-sftp-test-<timestamp>-<random>` under the chosen remote
directory), with a sub-folder per worker so workers never race each other
over the same paths -- real data on the server is never touched, and the
folder is removed again when the test stops (unless the user opts out).
Downloads are checked against the SHA-256 of what that worker uploaded, so
a server that silently corrupts or truncates files shows up as integrity
errors rather than passing quietly.

The workers are plain daemon threads, not core.async_utils.run_in_background
tasks: they run for as long as the test does, and parking up to dozens of
them in the shared 16-thread Qt pool would starve every other tab's
background work. The short setup/cleanup steps (StressTest.prepare and
StressTest.cleanup) are ordinary blocking calls the widget runs via
run_in_background like any other network call.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import random
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import paramiko

from it_toolbox.core.ftp_client import SftpSession

OPERATIONS = ("upload", "download", "list", "stat", "mkdir", "rename", "delete")

# Relative weights: transfers dominate (they're what a file server is for),
# metadata calls fill the gaps. Operations that need something to act on
# (download/rename/delete with no files yet) are re-rolled -- see _pick().
DEFAULT_WEIGHTS = {
    "upload": 30,
    "download": 25,
    "list": 15,
    "stat": 10,
    "mkdir": 5,
    "rename": 8,
    "delete": 7,
}

# Each worker keeps at most this many files around: past it, uploads are
# swapped for deletes so a long test doesn't slowly fill the disk.
MAX_FILES_PER_WORKER = 50
MAX_DIRS_PER_WORKER = 10
RECENT_ERRORS_LIMIT = 200
RECONNECT_DELAY_S = 2.0


@dataclass(frozen=True)
class StressTestConfig:
    host: str
    port: int = 22
    username: str = ""
    password: str | None = None
    key_path: str | None = None
    key_passphrase: str | None = None
    workers: int = 4
    min_file_size: int = 1024
    max_file_size: int = 1024 * 1024
    remote_dir: str = ""  # "" = the login's home directory
    cleanup: bool = True

    def session(self) -> SftpSession:
        return SftpSession(
            self.host,
            self.port,
            self.username,
            password=self.password,
            key_path=self.key_path,
            key_passphrase=self.key_passphrase,
        )


@dataclass
class OperationStats:
    count: int = 0
    errors: int = 0
    total_latency: float = 0.0
    max_latency: float = 0.0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.count if self.count else 0.0


@dataclass(frozen=True)
class ErrorRecord:
    seq: int  # 1-based, increasing -- lets the UI tell which records are new
    timestamp: float
    worker: int
    operation: str
    message: str


@dataclass
class StatsSnapshot:
    elapsed: float
    operations: dict[str, OperationStats]
    bytes_uploaded: int
    bytes_downloaded: int
    active_workers: int
    errors: list[ErrorRecord] = field(default_factory=list)

    @property
    def total_ops(self) -> int:
        """File operations only -- connection attempts aren't counted."""
        return sum(op.count for name, op in self.operations.items() if name != "connect")

    @property
    def total_errors(self) -> int:
        """Including failed connection attempts."""
        return sum(op.errors for op in self.operations.values())


class StressStats:
    """Counters shared by every worker thread; snapshot() is what the UI
    polls. One lock around everything -- updates are a handful of integer
    adds per file operation, nowhere near contended enough to matter."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._started = clock()
        self._stopped: float | None = None
        self._ops = {name: OperationStats() for name in (*OPERATIONS, "connect")}
        self._bytes_up = 0
        self._bytes_down = 0
        self._active = 0
        self._errors: deque[ErrorRecord] = deque(maxlen=RECENT_ERRORS_LIMIT)
        self._error_seq = 0

    def record(self, operation: str, latency: float, error: str | None = None, worker: int = 0) -> None:
        with self._lock:
            op = self._ops[operation]
            op.count += 1
            op.total_latency += latency
            op.max_latency = max(op.max_latency, latency)
            if error is not None:
                op.errors += 1
                self._error_seq += 1
                self._errors.append(ErrorRecord(self._error_seq, time.time(), worker, operation, error))

    def add_bytes(self, uploaded: int = 0, downloaded: int = 0) -> None:
        with self._lock:
            self._bytes_up += uploaded
            self._bytes_down += downloaded

    def worker_started(self) -> None:
        with self._lock:
            self._active += 1

    def worker_stopped(self) -> None:
        with self._lock:
            self._active -= 1

    def mark_stopped(self) -> None:
        with self._lock:
            if self._stopped is None:
                self._stopped = self._clock()

    def snapshot(self) -> StatsSnapshot:
        with self._lock:
            end = self._stopped if self._stopped is not None else self._clock()
            return StatsSnapshot(
                elapsed=end - self._started,
                operations={
                    name: OperationStats(op.count, op.errors, op.total_latency, op.max_latency)
                    for name, op in self._ops.items()
                },
                bytes_uploaded=self._bytes_up,
                bytes_downloaded=self._bytes_down,
                active_workers=self._active,
                errors=list(self._errors),
            )


def test_folder_name(now: float | None = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return f"it-toolbox-sftp-test-{stamp}-{secrets.token_hex(3)}"


class _Worker:
    """One connection's random walk inside its own folder. Tracks what it
    created (and the hash of each file's content) so every operation it
    picks is one that should succeed -- anything that then fails is the
    server's error, not the test's."""

    def __init__(
        self,
        index: int,
        config: StressTestConfig,
        root: str,
        stats: StressStats,
        stop: threading.Event,
        session_factory: Callable[[], SftpSession],
        rng: random.Random,
    ) -> None:
        self.index = index
        self._config = config
        self._dir = posixpath.join(root, f"worker-{index}")
        self._stats = stats
        self._stop = stop
        self._session_factory = session_factory
        self._rng = rng
        self._session: SftpSession | None = None
        self._files: dict[str, str] = {}  # remote path -> sha256 of content
        self._dirs: list[str] = []
        self._counter = 0

    def run(self) -> None:
        self._stats.worker_started()
        try:
            while not self._stop.is_set():
                if self._session is None and not self._connect():
                    self._stop.wait(RECONNECT_DELAY_S)
                    continue
                operation = self._pick()
                started = time.perf_counter()
                try:
                    getattr(self, f"_do_{operation}")()
                except _Cancelled:
                    break
                except Exception as exc:  # noqa: BLE001 - every failure is a result to report
                    self._stats.record(operation, time.perf_counter() - started, _describe(exc), self.index)
                    if _is_connection_lost(exc):
                        self._drop_session()
                else:
                    self._stats.record(operation, time.perf_counter() - started)
        finally:
            self._drop_session()
            self._stats.worker_stopped()

    def _connect(self) -> bool:
        started = time.perf_counter()
        session = self._session_factory()
        try:
            session.connect()
            try:
                session.mkdir(self._dir)
            except OSError:
                pass  # already there from a previous connection of this worker
        except Exception as exc:  # noqa: BLE001
            self._stats.record("connect", time.perf_counter() - started, _describe(exc), self.index)
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass
            return False
        self._stats.record("connect", time.perf_counter() - started)
        self._session = session
        return True

    def _drop_session(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001 - already broken, nothing to report
                pass
            self._session = None

    def _pick(self) -> str:
        weights = dict(DEFAULT_WEIGHTS)
        if not self._files:
            weights["download"] = weights["rename"] = 0
        if not self._files and not self._dirs:
            weights["delete"] = 0
        if len(self._files) >= MAX_FILES_PER_WORKER:
            weights["upload"] = 0
        if len(self._dirs) >= MAX_DIRS_PER_WORKER:
            weights["mkdir"] = 0
        names = list(weights)
        return self._rng.choices(names, weights=[weights[n] for n in names])[0]

    def _new_path(self, prefix: str) -> str:
        self._counter += 1
        parent = self._rng.choice([self._dir, *self._dirs])
        return posixpath.join(parent, f"{prefix}-{self._counter}")

    # -- Operations --------------------------------------------------------

    def _do_upload(self) -> None:
        size = self._rng.randint(self._config.min_file_size, self._config.max_file_size)
        source = _RandomSource(size, self._stats, self._stop)
        path = self._new_path("file") + ".bin"
        self._session.upload_fileobj(source, path, size)
        self._files[path] = source.digest.hexdigest()

    def _do_download(self) -> None:
        path = self._rng.choice(list(self._files))
        sink = _HashingSink(self._stats, self._stop)
        self._session.download_fileobj(path, sink)
        if sink.digest.hexdigest() != self._files[path]:
            raise IntegrityError(f"{posixpath.basename(path)}: downloaded content doesn't match what was uploaded")

    def _do_list(self) -> None:
        self._session.list_dir(self._rng.choice([self._dir, *self._dirs]))

    def _do_stat(self) -> None:
        self._session.stat(self._rng.choice([*self._files, *self._dirs, self._dir]))

    def _do_mkdir(self) -> None:
        path = self._new_path("dir")
        self._session.mkdir(path)
        self._dirs.append(path)

    def _do_rename(self) -> None:
        old = self._rng.choice(list(self._files))
        new = self._new_path("renamed") + ".bin"
        self._session.rename(old, new)
        self._files[new] = self._files.pop(old)

    def _do_delete(self) -> None:
        empty_dirs = [d for d in self._dirs if not any(p.startswith(d + "/") for p in (*self._files, *self._dirs))]
        if self._files and (not empty_dirs or self._rng.random() < 0.8):
            path = self._rng.choice(list(self._files))
            self._session.remove(path)
            del self._files[path]
        else:
            path = self._rng.choice(empty_dirs)
            self._session.rmdir(path)
            self._dirs.remove(path)


class IntegrityError(Exception):
    pass


class _Cancelled(Exception):
    """Raised from inside a transfer once the test is stopped, so a
    multi-gigabyte upload or download doesn't hold up Stop. Not an error:
    the half-written file is removed with the rest of the test folder."""


class _RandomSource:
    """A file-like object of `size` random bytes, generated as paramiko
    reads it rather than held in memory (files can be gigabytes, times
    every worker). Hashes what it hands out and counts it as uploaded."""

    def __init__(self, size: int, stats: StressStats, stop: threading.Event) -> None:
        self._remaining = size
        self._stats = stats
        self._stop = stop
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        if self._stop.is_set():
            raise _Cancelled()
        if size < 0 or size > self._remaining:
            size = self._remaining
        chunk = os.urandom(size)
        self._remaining -= size
        self.digest.update(chunk)
        self._stats.add_bytes(uploaded=size)
        return chunk


class _HashingSink:
    """Write side of a download: hashes and counts, keeps nothing."""

    def __init__(self, stats: StressStats, stop: threading.Event) -> None:
        self._stats = stats
        self._stop = stop
        self.digest = hashlib.sha256()

    def write(self, chunk: bytes) -> int:
        if self._stop.is_set():
            raise _Cancelled()
        self.digest.update(chunk)
        self._stats.add_bytes(downloaded=len(chunk))
        return len(chunk)


def _describe(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    if isinstance(exc, OSError) and exc.strerror and not exc.filename:
        text = exc.strerror
    return text


def _is_connection_lost(exc: Exception) -> bool:
    # paramiko raises SSHException, EOFError or "Socket is closed" (an
    # OSError with no errno) once the transport has gone; plain SFTP status
    # errors (no such file, permission denied) come through as an OSError
    # with an errno and leave the connection usable.
    if isinstance(exc, (EOFError, ConnectionError, paramiko.SSHException)):
        return True
    return isinstance(exc, OSError) and exc.errno is None


class StressTest:
    """One run of the tool. prepare() (blocking: connects once to check the
    credentials and host key, and creates the test folder), then start()
    the workers, stop() them, and cleanup() (blocking) to remove the
    folder again."""

    def __init__(
        self,
        config: StressTestConfig,
        session_factory: Callable[[], SftpSession] | None = None,
        seed: int | None = None,
    ) -> None:
        self.config = config
        self._session_factory = session_factory or config.session
        self._rng = random.Random(seed)
        self.stats = StressStats()
        self.root: str | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def prepare(self) -> str:
        session = self._session_factory()
        session.connect()
        try:
            base = self.config.remote_dir.strip() or session.home_dir()
            root = posixpath.join(base, test_folder_name())
            session.mkdir(root)
        finally:
            session.close()
        self.root = root
        return root

    def start(self) -> None:
        assert self.root is not None, "prepare() first"
        self.stats = StressStats()
        for index in range(1, self.config.workers + 1):
            worker = _Worker(
                index,
                self.config,
                self.root,
                self.stats,
                self._stop,
                self._session_factory,
                random.Random(self._rng.random()),
            )
            thread = threading.Thread(target=worker.run, name=f"sftp-test-worker-{index}", daemon=True)
            self._threads.append(thread)
            thread.start()

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def stop(self) -> None:
        """Signals every worker to finish its current operation; doesn't
        wait. join() (blocking) does."""
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        for thread in self._threads:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        self.stats.mark_stopped()

    def cleanup(self) -> int:
        """Removes the test folder and everything in it; returns how many
        entries were deleted. Call after join()."""
        if self.root is None:
            return 0
        session = self._session_factory()
        session.connect()
        try:
            return remove_tree(session, self.root)
        finally:
            session.close()


def remove_tree(session: SftpSession, path: str) -> int:
    removed = 0
    for entry in session.list_dir(path):
        child = posixpath.join(path, entry.name)
        if entry.is_dir:
            removed += remove_tree(session, child)
        else:
            session.remove(child)
            removed += 1
    session.rmdir(path)
    return removed + 1


def format_bytes(count: float) -> str:
    if count < 1024:
        return f"{count:.0f} B"
    for unit in ("KB", "MB", "GB"):
        count /= 1024
        if count < 1024:
            break
    return f"{count:.1f} {unit}"

import errno
import posixpath
import threading
import time

import pytest

from it_toolbox.core import sftp_stress_test
from it_toolbox.core.ftp_client import FileEntry
from it_toolbox.core.sftp_stress_test import (
    OPERATIONS,
    StressStats,
    StressTest,
    StressTestConfig,
    format_bytes,
    remove_tree,
)


class FakeServer:
    """An in-memory SFTP server shared by every FakeSession."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.files: dict[str, bytes] = {}
        self.dirs = {"/home/tester"}
        self.connects = 0
        self.corrupt = False
        self.fail_connect = False


class FakeSession:
    def __init__(self, server: FakeServer) -> None:
        self._server = server

    def _missing(self, path):
        return OSError(errno.ENOENT, "No such file", path)

    def connect(self):
        time.sleep(0.0002)  # a little network latency, so workers release the GIL
        with self._server.lock:
            self._server.connects += 1
            if self._server.fail_connect:
                raise ConnectionRefusedError(111, "Connection refused")

    def home_dir(self):
        return "/home/tester"

    def mkdir(self, path):
        time.sleep(0.0002)
        with self._server.lock:
            if path in self._server.dirs or posixpath.dirname(path) not in self._server.dirs:
                raise OSError(errno.EEXIST if path in self._server.dirs else errno.ENOENT, "mkdir failed")
            self._server.dirs.add(path)

    def rmdir(self, path):
        time.sleep(0.0002)
        with self._server.lock:
            children = [p for p in (*self._server.files, *self._server.dirs) if p.startswith(path + "/")]
            if path not in self._server.dirs or children:
                raise OSError(errno.ENOTEMPTY, "rmdir failed")
            self._server.dirs.remove(path)

    def upload_bytes(self, data, path):
        time.sleep(0.0002)
        with self._server.lock:
            if posixpath.dirname(path) not in self._server.dirs:
                raise self._missing(path)
            self._server.files[path] = data

    def download_bytes(self, path):
        time.sleep(0.0002)
        with self._server.lock:
            if path not in self._server.files:
                raise self._missing(path)
            data = self._server.files[path]
        return data[:-1] + bytes([data[-1] ^ 0xFF]) if self._server.corrupt and data else data

    def list_dir(self, path):
        time.sleep(0.0002)
        with self._server.lock:
            if path not in self._server.dirs:
                raise self._missing(path)
            entries = [FileEntry(posixpath.basename(p), True) for p in self._server.dirs if posixpath.dirname(p) == path]
            entries += [
                FileEntry(posixpath.basename(p), False, len(d))
                for p, d in self._server.files.items()
                if posixpath.dirname(p) == path
            ]
        return entries

    def stat(self, path):
        time.sleep(0.0002)
        with self._server.lock:
            if path not in self._server.files and path not in self._server.dirs:
                raise self._missing(path)

    def rename(self, old, new):
        time.sleep(0.0002)
        with self._server.lock:
            if old not in self._server.files or posixpath.dirname(new) not in self._server.dirs:
                raise self._missing(old)
            self._server.files[new] = self._server.files.pop(old)

    def remove(self, path):
        time.sleep(0.0002)
        with self._server.lock:
            if path not in self._server.files:
                raise self._missing(path)
            del self._server.files[path]

    def close(self):
        pass


CONFIG = StressTestConfig(host="sftp.test", username="tester", workers=3, min_file_size=10, max_file_size=200)


def _run(server, config=CONFIG, seconds=0.3):
    test = StressTest(config, session_factory=lambda: FakeSession(server), seed=1)
    root = test.prepare()
    test.start()
    time.sleep(seconds)
    test.stop()
    test.join(timeout=5)
    return test, root


def test_prepare_creates_a_fresh_test_folder_in_the_home_directory():
    server = FakeServer()
    test = StressTest(CONFIG, session_factory=lambda: FakeSession(server))

    root = test.prepare()

    assert posixpath.dirname(root) == "/home/tester"
    assert posixpath.basename(root).startswith("it-toolbox-sftp-test-")
    assert root in server.dirs


def test_prepare_uses_the_chosen_remote_folder():
    server = FakeServer()
    server.dirs.add("/srv/ftp")
    config = StressTestConfig(host="h", username="u", remote_dir="/srv/ftp")

    root = StressTest(config, session_factory=lambda: FakeSession(server)).prepare()

    assert posixpath.dirname(root) == "/srv/ftp"


def test_workers_exercise_every_operation_without_errors_and_stay_in_their_folder():
    server = FakeServer()

    test, root = _run(server, seconds=0.5)
    snapshot = test.stats.snapshot()

    assert not test.running
    assert snapshot.total_errors == 0, snapshot.errors
    for name in OPERATIONS:
        assert snapshot.operations[name].count > 0, name
    assert snapshot.operations["connect"].count == CONFIG.workers
    assert snapshot.bytes_uploaded > 0 and snapshot.bytes_downloaded > 0
    assert snapshot.active_workers == 0
    for path in [*server.files, *server.dirs]:
        assert path == "/home/tester" or path == root or path.startswith(root + "/worker-")


def test_cleanup_removes_the_test_folder_and_everything_in_it():
    server = FakeServer()
    test, root = _run(server)
    assert any(p.startswith(root) for p in server.files)

    removed = test.cleanup()

    assert removed > 1
    assert server.dirs == {"/home/tester"}
    assert server.files == {}


def test_corrupted_downloads_are_reported_as_errors():
    server = FakeServer()
    server.corrupt = True

    test, _ = _run(server)
    snapshot = test.stats.snapshot()

    assert snapshot.operations["download"].errors == snapshot.operations["download"].count > 0
    assert "doesn't match" in snapshot.errors[-1].message


def test_failing_connections_are_counted_and_retried(monkeypatch):
    monkeypatch.setattr(sftp_stress_test, "RECONNECT_DELAY_S", 0.01)
    server = FakeServer()
    test = StressTest(CONFIG, session_factory=lambda: FakeSession(server), seed=1)
    test.prepare()
    server.fail_connect = True
    test.start()
    time.sleep(0.2)
    test.stop()
    test.join(timeout=5)

    connect = test.stats.snapshot().operations["connect"]
    assert connect.errors == connect.count > CONFIG.workers


def test_a_lost_connection_reconnects():
    assert sftp_stress_test._is_connection_lost(OSError("Socket is closed"))
    assert sftp_stress_test._is_connection_lost(EOFError())
    assert not sftp_stress_test._is_connection_lost(OSError(errno.ENOENT, "No such file"))


def test_remove_tree_deletes_nested_entries():
    server = FakeServer()
    server.dirs |= {"/home/tester/t", "/home/tester/t/a"}
    server.files = {"/home/tester/t/a/f": b"x", "/home/tester/t/g": b"y"}

    assert remove_tree(FakeSession(server), "/home/tester/t") == 4
    assert server.dirs == {"/home/tester"}


def test_stats_snapshot_tracks_latency_and_recent_errors():
    now = [100.0]
    stats = StressStats(clock=lambda: now[0])
    stats.record("list", 0.1)
    stats.record("list", 0.3, error="boom", worker=2)
    now[0] = 102.0

    snapshot = stats.snapshot()

    assert snapshot.elapsed == 2.0
    assert snapshot.operations["list"].count == 2
    assert snapshot.operations["list"].errors == 1
    assert snapshot.operations["list"].avg_latency == pytest.approx(0.2)
    assert snapshot.operations["list"].max_latency == 0.3
    assert [(e.seq, e.worker, e.operation, e.message) for e in snapshot.errors] == [(1, 2, "list", "boom")]

    stats.mark_stopped()
    now[0] = 200.0
    assert stats.snapshot().elapsed == 2.0


def test_format_bytes():
    assert format_bytes(512) == "512 B"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(5 * 1024**3) == "5.0 GB"

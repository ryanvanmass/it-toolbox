import ftplib
import socket
import time

from it_toolbox.core.ftp_client import FtpClientError, FtpSession
from it_toolbox.core.ftp_stress_test import FtpStressTest, FtpStressTestConfig, is_ftp_connection_lost
from test_sftp_stress_test import FakeServer, FakeSession


def _wrapped(cause: BaseException) -> FtpClientError:
    try:
        raise FtpClientError(str(cause)) from cause
    except FtpClientError as exc:
        return exc


def test_server_replies_keep_the_connection():
    assert not is_ftp_connection_lost(_wrapped(ftplib.error_perm("550 No such file or directory")))
    assert not is_ftp_connection_lost(_wrapped(ftplib.error_temp("452 Insufficient storage")))


def test_dropped_connections_are_detected():
    assert is_ftp_connection_lost(_wrapped(ftplib.error_temp("421 Timeout")))
    assert is_ftp_connection_lost(_wrapped(ftplib.error_perm("530 Log in with USER and PASS first.")))
    assert is_ftp_connection_lost(_wrapped(EOFError()))
    assert is_ftp_connection_lost(_wrapped(ConnectionResetError(104, "Connection reset by peer")))
    assert is_ftp_connection_lost(_wrapped(socket.timeout("timed out")))
    assert is_ftp_connection_lost(_wrapped(ftplib.error_reply("226 Transfer complete")))
    assert not is_ftp_connection_lost(FtpClientError("no cause"))


def test_config_builds_an_ftp_session():
    session = FtpStressTestConfig("ftp.example.com", 2121, "tester", "pw", use_tls=True).session()

    assert isinstance(session, FtpSession)
    assert (session._host, session._port, session._username, session._password) == (
        "ftp.example.com",
        2121,
        "tester",
        "pw",
    )
    assert session._use_tls is True


def test_runs_the_shared_engine_in_an_ftp_test_folder():
    server = FakeServer()
    config = FtpStressTestConfig("ftp.example.com", username="tester", workers=3, min_file_size=10, max_file_size=2000)
    test = FtpStressTest(config, session_factory=lambda: FakeSession(server), seed=1)

    root = test.prepare()
    assert root.startswith("/home/tester/it-toolbox-ftp-test-")
    test.start()
    deadline = time.monotonic() + 5
    while test.stats.snapshot().total_ops < 200 and time.monotonic() < deadline:
        time.sleep(0.01)
    test.stop()
    test.join(5)
    assert test.cleanup() > 0

    snapshot = test.stats.snapshot()
    assert snapshot.total_ops >= 200
    assert snapshot.total_errors == 0
    assert not any(p.startswith(root) for p in (*server.files, *server.dirs))

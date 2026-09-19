import ftplib
import stat as stat_module

import paramiko
import pytest

from it_toolbox.core import ftp_client


# -- SftpSession --------------------------------------------------------


class _FakeSftpClient:
    def __init__(self):
        self.closed = False
        self.uploaded = []
        self.downloaded = []

    def normalize(self, path):
        return "/home/alice"

    def listdir_attr(self, path):
        file_attr = paramiko.SFTPAttributes()
        file_attr.filename = "readme.txt"
        file_attr.st_mode = stat_module.S_IFREG | 0o644
        file_attr.st_size = 42
        file_attr.st_mtime = 1700000000

        dir_attr = paramiko.SFTPAttributes()
        dir_attr.filename = "photos"
        dir_attr.st_mode = stat_module.S_IFDIR | 0o755
        dir_attr.st_size = 4096
        dir_attr.st_mtime = 1700000000
        return [file_attr, dir_attr]

    def get(self, remote_path, local_path, callback=None):
        self.downloaded.append((remote_path, local_path))
        if callback:
            callback(10, 10)

    def put(self, local_path, remote_path, callback=None):
        self.uploaded.append((local_path, remote_path))
        if callback:
            callback(10, 10)

    def mkdir(self, path):
        pass

    def rmdir(self, path):
        pass

    def remove(self, path):
        pass

    def rename(self, old, new):
        pass

    def chmod(self, path, mode):
        pass

    def close(self):
        self.closed = True


class _FakeSshClient:
    instances = []

    def __init__(self):
        self.connected_with = None
        self.host_key_policy = None
        self.sftp = _FakeSftpClient()
        self.closed = False
        _FakeSshClient.instances.append(self)

    def set_missing_host_key_policy(self, policy):
        self.host_key_policy = policy

    def load_system_host_keys(self):
        pass

    def load_host_keys(self, path):
        pass

    def connect(self, host, **kwargs):
        self.connected_with = {"host": host, **kwargs}

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_ssh_clients():
    _FakeSshClient.instances = []
    yield


def test_sftp_session_connects_with_given_credentials(monkeypatch):
    monkeypatch.setattr(paramiko, "SSHClient", _FakeSshClient)
    session = ftp_client.SftpSession(
        "example.com", 22, "alice", password="secret", skip_host_key_check=True
    )

    session.connect()

    client = _FakeSshClient.instances[0]
    assert isinstance(client.host_key_policy, paramiko.AutoAddPolicy)
    assert client.connected_with["host"] == "example.com"
    assert client.connected_with["username"] == "alice"
    assert client.connected_with["password"] == "secret"
    assert client.connected_with["allow_agent"] is True
    assert client.connected_with["look_for_keys"] is True


def test_sftp_session_uses_reject_policy_when_host_key_checking_enabled(monkeypatch):
    monkeypatch.setattr(paramiko, "SSHClient", _FakeSshClient)
    session = ftp_client.SftpSession("example.com", 22, "alice", password="secret")

    session.connect()

    client = _FakeSshClient.instances[0]
    assert isinstance(client.host_key_policy, paramiko.RejectPolicy)


def test_sftp_session_wraps_authentication_failure(monkeypatch):
    class _FailingClient(_FakeSshClient):
        def connect(self, host, **kwargs):
            raise paramiko.AuthenticationException("nope")

    monkeypatch.setattr(paramiko, "SSHClient", _FailingClient)
    session = ftp_client.SftpSession("example.com", 22, "alice", password="wrong")

    with pytest.raises(ftp_client.FtpClientError, match="Authentication failed"):
        session.connect()


def test_sftp_session_list_dir_maps_attrs_to_file_entries(monkeypatch):
    monkeypatch.setattr(paramiko, "SSHClient", _FakeSshClient)
    session = ftp_client.SftpSession("example.com", 22, "alice", skip_host_key_check=True)
    session.connect()

    entries = session.list_dir("/home/alice")

    # Directories sort first, then alphabetically.
    assert [e.name for e in entries] == ["photos", "readme.txt"]
    assert entries[0].is_dir is True
    assert entries[1].is_dir is False
    assert entries[1].size == 42


def test_sftp_session_upload_and_download_delegate_to_paramiko(monkeypatch):
    monkeypatch.setattr(paramiko, "SSHClient", _FakeSshClient)
    session = ftp_client.SftpSession("example.com", 22, "alice", skip_host_key_check=True)
    session.connect()

    progress_calls = []
    session.download("/remote/file", "/local/file", progress=lambda t, n: progress_calls.append((t, n)))
    session.upload("/local/file", "/remote/file")

    client = _FakeSshClient.instances[0]
    assert client.sftp.downloaded == [("/remote/file", "/local/file")]
    assert client.sftp.uploaded == [("/local/file", "/remote/file")]
    assert progress_calls == [(10, 10)]


def test_sftp_session_close_closes_both_client_and_sftp(monkeypatch):
    monkeypatch.setattr(paramiko, "SSHClient", _FakeSshClient)
    session = ftp_client.SftpSession("example.com", 22, "alice", skip_host_key_check=True)
    session.connect()

    session.close()

    client = _FakeSshClient.instances[0]
    assert client.sftp.closed is True
    assert client.closed is True


def test_sftp_session_join_and_parent_use_posix_semantics():
    session = ftp_client.SftpSession("example.com", 22, "alice")
    assert session.join("/home/alice", "docs") == "/home/alice/docs"
    assert session.parent("/home/alice/docs") == "/home/alice"
    assert session.parent("/home") == "/"


# -- FtpSession -----------------------------------------------------------


class _FakeFtp:
    def __init__(self):
        self.logged_in_as = None
        self.quit_called = False

    def connect(self, host, port, timeout=None):
        self.host = host
        self.port = port

    def login(self, username, password):
        self.logged_in_as = (username, password)

    def set_pasv(self, value):
        pass

    def pwd(self):
        return "/"

    def mlsd(self, path):
        return iter(
            [
                (".", {"type": "cdir"}),
                ("photos", {"type": "dir", "modify": "20231115120000"}),
                ("readme.txt", {"type": "file", "size": "42", "modify": "20231115120000"}),
            ]
        )

    def size(self, path):
        return 42

    def retrbinary(self, cmd, callback):
        callback(b"hello")

    def storbinary(self, cmd, fp, callback=None):
        data = fp.read()
        if callback:
            callback(data)

    def mkd(self, path):
        pass

    def rmd(self, path):
        pass

    def delete(self, path):
        pass

    def rename(self, old, new):
        pass

    def quit(self):
        self.quit_called = True


def test_ftp_session_connects_and_logs_in(monkeypatch):
    fake = _FakeFtp()
    monkeypatch.setattr(ftplib, "FTP", lambda: fake)
    session = ftp_client.FtpSession("example.com", 21, "alice", password="secret")

    session.connect()

    assert fake.logged_in_as == ("alice", "secret")


def test_ftp_session_defaults_to_anonymous_when_no_username(monkeypatch):
    fake = _FakeFtp()
    monkeypatch.setattr(ftplib, "FTP", lambda: fake)
    session = ftp_client.FtpSession("example.com", 21, "")

    session.connect()

    assert fake.logged_in_as[0] == "anonymous"


def test_ftp_session_connect_wraps_errors(monkeypatch):
    class _FailingFtp(_FakeFtp):
        def connect(self, host, port, timeout=None):
            raise ftplib.error_temp("can't connect")

    monkeypatch.setattr(ftplib, "FTP", _FailingFtp)
    session = ftp_client.FtpSession("example.com", 21, "alice")

    with pytest.raises(ftp_client.FtpClientError, match="Couldn't connect"):
        session.connect()


def test_ftp_session_list_dir_uses_mlsd(monkeypatch):
    fake = _FakeFtp()
    monkeypatch.setattr(ftplib, "FTP", lambda: fake)
    session = ftp_client.FtpSession("example.com", 21, "alice")
    session.connect()

    entries = session.list_dir("/")

    assert [e.name for e in entries] == ["photos", "readme.txt"]
    assert entries[0].is_dir is True
    assert entries[1].size == 42


def test_ftp_session_download_writes_file_and_reports_progress(monkeypatch, tmp_path):
    fake = _FakeFtp()
    monkeypatch.setattr(ftplib, "FTP", lambda: fake)
    session = ftp_client.FtpSession("example.com", 21, "alice")
    session.connect()

    dest = tmp_path / "out.txt"
    progress_calls = []
    session.download("/remote.txt", str(dest), progress=lambda t, n: progress_calls.append((t, n)))

    assert dest.read_bytes() == b"hello"
    assert progress_calls == [(5, 42)]


def test_ftp_session_upload_reads_file_and_reports_progress(monkeypatch, tmp_path):
    fake = _FakeFtp()
    monkeypatch.setattr(ftplib, "FTP", lambda: fake)
    session = ftp_client.FtpSession("example.com", 21, "alice")
    session.connect()

    source = tmp_path / "in.txt"
    source.write_bytes(b"hello world")
    progress_calls = []
    session.upload(str(source), "/remote.txt", progress=lambda t, n: progress_calls.append((t, n)))

    assert progress_calls == [(len(b"hello world"), len(b"hello world"))]


def test_ftp_session_close_calls_quit(monkeypatch):
    fake = _FakeFtp()
    monkeypatch.setattr(ftplib, "FTP", lambda: fake)
    session = ftp_client.FtpSession("example.com", 21, "alice")
    session.connect()

    session.close()

    assert fake.quit_called is True


# -- Local listing ----------------------------------------------------------


def test_list_local_dir_sorts_directories_first(tmp_path):
    (tmp_path / "b.txt").write_text("hi")
    (tmp_path / "a_dir").mkdir()
    (tmp_path / "a.txt").write_text("hi")

    entries = ftp_client.list_local_dir(str(tmp_path))

    assert [e.name for e in entries] == ["a_dir", "a.txt", "b.txt"]
    assert entries[0].is_dir is True

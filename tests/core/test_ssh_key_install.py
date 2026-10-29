import os
import subprocess

import paramiko
import pytest

from it_toolbox.core import settings
from it_toolbox.core import ssh_key_install as ski

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample me@laptop"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ski.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(settings.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _keypair(directory, name, public=KEY):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("private")
    (directory / f"{name}.pub").write_text(public + "\n")
    return directory / name


def test_find_local_key_prefers_the_servers_own_key(home):
    _keypair(home / ".ssh", "id_ed25519")
    own = _keypair(home / "keys", "nas", "ssh-rsa AAAAB3 nas")
    assert ski.find_local_key(str(own)) == ski.LocalKey(own, "ssh-rsa AAAAB3 nas")
    # Pointing at the .pub works too.
    assert ski.find_local_key(f"{own}.pub").private_path == own


def test_find_local_key_falls_back_to_the_default_key(home):
    default = _keypair(home / ".ssh", "id_ed25519")
    # A configured key without a .pub can't be installed.
    (home / "bare").write_text("private")
    assert ski.find_local_key(str(home / "bare")) == ski.LocalKey(default, KEY)


def test_find_local_key_with_no_key_plans_a_new_one(home):
    local = ski.find_local_key(None)
    assert local == ski.LocalKey(home / ".ssh" / "id_ed25519", None)
    assert not local.exists


def test_generate_key_writes_a_loadable_keypair(home):
    local = ski.generate_key(home / ".ssh" / "id_ed25519")
    private = paramiko.Ed25519Key.from_private_key_file(str(local.private_path))
    algorithm, blob, comment = local.public_key.split(" ")
    assert algorithm == "ssh-ed25519" and blob == private.get_base64() and "@" in comment
    assert (home / ".ssh" / "id_ed25519.pub").read_text() == local.public_key + "\n"
    if os.name == "posix":
        assert local.private_path.stat().st_mode & 0o777 == 0o600
    assert ski.find_local_key(None) == local


def test_generate_key_never_overwrites(home):
    _keypair(home / ".ssh", "id_ed25519")
    with pytest.raises(ski.KeyInstallError, match="already exists"):
        ski.generate_key(home / ".ssh" / "id_ed25519")


def _run_install(home, key=KEY):
    return subprocess.run(
        ["sh", "-c", ski.INSTALL_SCRIPT], input=key + "\n", text=True, capture_output=True,
        env={**os.environ, "HOME": str(home)},
    )


@pytest.mark.skipif(os.name != "posix", reason="runs the remote shell script locally")
def test_install_script_creates_appends_and_dedupes(tmp_path):
    assert _run_install(tmp_path).returncode == 0
    authorized = tmp_path / ".ssh" / "authorized_keys"
    assert authorized.read_text() == KEY + "\n"
    assert authorized.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / ".ssh").stat().st_mode & 0o777 == 0o700

    assert _run_install(tmp_path).returncode == 0
    assert authorized.read_text() == KEY + "\n"

    # A last line without a newline isn't glued to the new key.
    authorized.write_text("ssh-rsa AAAA other")
    assert _run_install(tmp_path).returncode == 0
    assert authorized.read_text() == "ssh-rsa AAAA other\n" + KEY + "\n"


def test_install_rejects_something_that_isnt_a_public_key():
    with pytest.raises(ski.KeyInstallError, match="public key"):
        ski.install_public_key("h", 22, "u", "pw", "-----BEGIN OPENSSH PRIVATE KEY-----")
    with pytest.raises(ski.KeyInstallError, match="public key"):
        ski.install_public_key("h", 22, "u", "pw", KEY + "\nssh-rsa evil")


class _FakeClient:
    """Stands in for paramiko.SSHClient, recording the connect kwargs and
    the install command's stdin."""

    instances = []
    status = 0
    auth_fails = False

    def __init__(self):
        self.connect_kwargs = None
        self.stdin = b""
        self.closed = False
        type(self).instances.append(self)

    def connect(self, host, **kwargs):
        if type(self).auth_fails:
            raise paramiko.AuthenticationException("no")
        self.connect_kwargs = {"host": host, **kwargs}

    def exec_command(self, command, timeout=None):
        client = self
        self.command = command

        class Channel:
            def shutdown_write(self):
                pass

            def recv_exit_status(self):
                return type(client).status

        class Stdin:
            channel = Channel()

            def write(self, data):
                client.stdin += data

        class Stream:
            channel = Channel()

            def read(self):
                return b"permission denied" if type(client).status else b""

        return Stdin(), Stream(), Stream()

    def close(self):
        self.closed = True


@pytest.fixture
def fake_client(monkeypatch):
    _FakeClient.instances = []
    _FakeClient.status = 0
    _FakeClient.auth_fails = False
    monkeypatch.setattr(ski, "_client", _FakeClient)
    return _FakeClient


def test_install_logs_in_with_only_the_password_and_sends_the_key_on_stdin(fake_client):
    ski.install_public_key("nas.lan", 2222, "admin", "pw", KEY + "\n")
    client = fake_client.instances[0]
    assert client.connect_kwargs == {
        "host": "nas.lan", "port": 2222, "username": "admin", "password": "pw",
        "allow_agent": False, "look_for_keys": False, "timeout": 15,
    }
    assert client.command == ski.INSTALL_SCRIPT and KEY not in client.command
    assert client.stdin == KEY.encode() + b"\n"
    assert client.closed


def test_install_reports_a_failed_script(fake_client):
    fake_client.status = 1
    with pytest.raises(ski.KeyInstallError, match="permission denied"):
        ski.install_public_key("nas.lan", 22, "admin", "pw", KEY)


def test_key_login_works_uses_only_the_key(fake_client, tmp_path):
    assert ski.key_login_works("nas.lan", 22, "admin", tmp_path / "k", "phrase")
    kwargs = fake_client.instances[0].connect_kwargs
    assert kwargs["key_filename"] == str(tmp_path / "k") and kwargs["passphrase"] == "phrase"
    assert kwargs["allow_agent"] is False and kwargs["look_for_keys"] is False
    fake_client.auth_fails = True
    assert not ski.key_login_works("nas.lan", 22, "admin", tmp_path / "k")

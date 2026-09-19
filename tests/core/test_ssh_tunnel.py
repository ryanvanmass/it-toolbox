import os
import socket
import subprocess
import sys

import pytest

from it_toolbox.core import ssh_tunnel
from it_toolbox.core.ssh_tunnel import SshTunnel, SshTunnelError


class _FakeProcess:
    def __init__(self, exits_immediately=False, stderr_text=""):
        self._exits_immediately = exits_immediately
        self.stderr = _FakeStderr(stderr_text)
        self.terminate_called = False
        self.killed = False

    def poll(self):
        return 1 if self._exits_immediately else None

    def terminate(self):
        self.terminate_called = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class _FakeStderr:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


def test_start_builds_forward_to_given_dest_host_and_port(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ssh_tunnel.subprocess, "Popen", lambda *a, **k: calls.append(a) or _FakeProcess()
    )
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: True)

    tunnel = SshTunnel("alice@bastion", "10.0.0.5", 3389, ssh_port=2222)
    local_port = tunnel.start(ready_timeout=1)

    (argv,) = calls[0]
    assert argv[0] == "ssh"
    assert "-L" in argv
    assert f"{local_port}:10.0.0.5:3389" in argv
    assert "-p" in argv
    assert "2222" in argv
    assert argv[-1] == "alice@bastion"


def test_start_omits_dash_p_when_no_ssh_port_given(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ssh_tunnel.subprocess, "Popen", lambda *a, **k: calls.append(a) or _FakeProcess()
    )
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: True)

    tunnel = SshTunnel("lab-host", "127.0.0.1", 5900)
    tunnel.start(ready_timeout=1)

    (argv,) = calls[0]
    assert "-p" not in argv


def test_start_without_password_uses_batch_mode_and_no_askpass_env(monkeypatch):
    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs.get("env")))
        return _FakeProcess()

    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: True)

    tunnel = SshTunnel("alice@lab-host", "127.0.0.1", 5900)
    tunnel.start(ready_timeout=1)

    argv, env = calls[0]
    assert "BatchMode=yes" in argv
    assert "StrictHostKeyChecking=accept-new" not in argv
    assert env is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod semantics assumed below")
def test_start_with_password_uses_askpass_not_batch_mode(monkeypatch):
    calls = []
    captured_askpass = {}

    def fake_popen(cmd, **kwargs):
        env = kwargs.get("env")
        calls.append((cmd, env))
        # The askpass file only exists for the duration of start() --
        # capture what it actually contains and its permissions now,
        # while the fake subprocess "sees" it, mirroring what a real ssh
        # process invoking it would read.
        askpass_path = env["SSH_ASKPASS"]
        with open(askpass_path) as f:
            captured_askpass["contents"] = f.read()
        captured_askpass["mode"] = oct(os.stat(askpass_path).st_mode & 0o777)
        captured_askpass["existed_during_start"] = os.path.exists(askpass_path)
        return _FakeProcess()

    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: True)

    tunnel = SshTunnel("alice@lab-host", "10.0.0.5", 3389, password="hunter2")
    tunnel.start(ready_timeout=1)

    argv, env = calls[0]
    assert "BatchMode=yes" not in argv
    assert "StrictHostKeyChecking=accept-new" in argv
    assert "PreferredAuthentications=password" in argv
    assert env["SSH_ASKPASS_REQUIRE"] == "force"
    assert env["IT_TOOLBOX_SSH_GATEWAY_PASSWORD"] == "hunter2"

    assert captured_askpass["existed_during_start"] is True
    assert "hunter2" not in captured_askpass["contents"]  # password only via env, not the script
    assert captured_askpass["mode"] == "0o700"


def test_start_with_password_cleans_up_askpass_file_on_success(monkeypatch):
    paths = []

    def fake_popen(cmd, **kwargs):
        paths.append(kwargs["env"]["SSH_ASKPASS"])
        return _FakeProcess()

    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: True)

    tunnel = SshTunnel("alice@lab-host", "10.0.0.5", 3389, password="hunter2")
    tunnel.start(ready_timeout=1)

    assert not os.path.exists(paths[0])


def test_start_with_password_cleans_up_askpass_file_on_auth_failure(monkeypatch):
    # Regression test for a real report: a gateway that rejects the key
    # and needs a password replies "Permission denied" immediately, which
    # is exactly the "exits right away" path -- the askpass temp file
    # must not leak a plaintext password on disk in that case either.
    paths = []

    def fake_popen(cmd, **kwargs):
        paths.append(kwargs["env"]["SSH_ASKPASS"])
        return _FakeProcess(exits_immediately=True, stderr_text="Permission denied (publickey,password).")

    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", fake_popen)

    tunnel = SshTunnel("alice@lab-host", "10.0.0.5", 3389, password="hunter2")

    with pytest.raises(SshTunnelError, match="Permission denied"):
        tunnel.start(ready_timeout=1)

    assert not os.path.exists(paths[0])


def test_start_raises_when_ssh_exits_immediately(monkeypatch):
    monkeypatch.setattr(
        ssh_tunnel.subprocess,
        "Popen",
        lambda *a, **k: _FakeProcess(exits_immediately=True, stderr_text="Host key verification failed."),
    )

    tunnel = SshTunnel("alice@lab-host", "127.0.0.1", 5900)

    with pytest.raises(SshTunnelError, match="Host key verification failed"):
        tunnel.start(ready_timeout=1)


def test_start_raises_when_ssh_binary_missing(monkeypatch):
    def fake_popen(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", fake_popen)

    tunnel = SshTunnel("alice@lab-host", "127.0.0.1", 5900)

    with pytest.raises(SshTunnelError, match="ssh not found"):
        tunnel.start(ready_timeout=1)


def test_start_times_out_when_port_never_opens(monkeypatch):
    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", lambda *a, **k: _FakeProcess())
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: False)

    tunnel = SshTunnel("alice@lab-host", "127.0.0.1", 5900)

    with pytest.raises(SshTunnelError, match="timed out"):
        tunnel.start(ready_timeout=0.3)


def test_start_returns_local_port_once_reachable(monkeypatch):
    fake_process = _FakeProcess()
    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", lambda *a, **k: fake_process)
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: True)

    tunnel = SshTunnel("alice@lab-host", "127.0.0.1", 5900)
    port = tunnel.start(ready_timeout=1)

    assert port == tunnel.port
    assert isinstance(port, int)


def test_stop_is_safe_before_start():
    tunnel = SshTunnel("alice@lab-host", "127.0.0.1", 5900)
    tunnel.stop()  # must not raise


def test_stop_kills_process_that_ignores_terminate(monkeypatch):
    class _StubbornProcess(_FakeProcess):
        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired(cmd="ssh", timeout=timeout)
            return 0

    fake_process = _StubbornProcess()
    monkeypatch.setattr(ssh_tunnel.subprocess, "Popen", lambda *a, **k: fake_process)
    monkeypatch.setattr(ssh_tunnel, "_can_connect", lambda port: True)

    tunnel = SshTunnel("alice@lab-host", "127.0.0.1", 5900)
    tunnel.start(ready_timeout=1)
    tunnel.stop(timeout=0.1)

    assert fake_process.terminate_called
    assert fake_process.killed


def test_free_local_port_returns_a_bindable_port():
    port = ssh_tunnel._free_local_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # would raise OSError if not actually free

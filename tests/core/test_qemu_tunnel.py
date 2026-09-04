import socket
import subprocess

import pytest

from it_toolbox.core import qemu_tunnel
from it_toolbox.core.qemu_tunnel import QemuTunnel, QemuTunnelError, _parse_ssh_target


@pytest.mark.parametrize(
    ("uri", "expected_target", "expected_port"),
    [
        ("qemu+ssh://alice@lab-host/system", "alice@lab-host", None),
        ("qemu+ssh://alice@lab-host:2222/system", "alice@lab-host", 2222),
        ("qemu+ssh://lab-host/system", "lab-host", None),
    ],
)
def test_parse_ssh_target(uri, expected_target, expected_port):
    target, port = _parse_ssh_target(uri)
    assert target == expected_target
    assert port == expected_port


def test_parse_ssh_target_rejects_non_ssh_scheme():
    with pytest.raises(QemuTunnelError, match="not an SSH-transport"):
        _parse_ssh_target("qemu:///system")


def test_parse_ssh_target_rejects_missing_host():
    with pytest.raises(QemuTunnelError, match="no host"):
        _parse_ssh_target("qemu+ssh:///system")


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


def test_start_raises_when_ssh_exits_immediately(monkeypatch):
    monkeypatch.setattr(
        qemu_tunnel.subprocess,
        "Popen",
        lambda *a, **k: _FakeProcess(exits_immediately=True, stderr_text="Host key verification failed."),
    )

    tunnel = QemuTunnel("qemu+ssh://alice@lab-host/system", remote_port=5900)

    with pytest.raises(QemuTunnelError, match="Host key verification failed"):
        tunnel.start(ready_timeout=1)


def test_start_raises_when_ssh_binary_missing(monkeypatch):
    def fake_popen(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(qemu_tunnel.subprocess, "Popen", fake_popen)

    tunnel = QemuTunnel("qemu+ssh://alice@lab-host/system", remote_port=5900)

    with pytest.raises(QemuTunnelError, match="ssh not found"):
        tunnel.start(ready_timeout=1)


def test_start_times_out_when_port_never_opens(monkeypatch):
    monkeypatch.setattr(qemu_tunnel.subprocess, "Popen", lambda *a, **k: _FakeProcess())
    monkeypatch.setattr(qemu_tunnel, "_can_connect", lambda port: False)

    tunnel = QemuTunnel("qemu+ssh://alice@lab-host/system", remote_port=5900)

    with pytest.raises(QemuTunnelError, match="timed out"):
        tunnel.start(ready_timeout=0.3)


def test_start_returns_local_port_once_reachable(monkeypatch):
    fake_process = _FakeProcess()
    monkeypatch.setattr(qemu_tunnel.subprocess, "Popen", lambda *a, **k: fake_process)
    monkeypatch.setattr(qemu_tunnel, "_can_connect", lambda port: True)

    tunnel = QemuTunnel("qemu+ssh://alice@lab-host/system", remote_port=5900)
    port = tunnel.start(ready_timeout=1)

    assert port == tunnel.port
    assert isinstance(port, int)


def test_stop_is_safe_before_start():
    tunnel = QemuTunnel("qemu+ssh://alice@lab-host/system", remote_port=5900)
    tunnel.stop()  # must not raise


def test_stop_kills_process_that_ignores_terminate(monkeypatch):
    class _StubbornProcess(_FakeProcess):
        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired(cmd="ssh", timeout=timeout)
            return 0

    fake_process = _StubbornProcess()
    monkeypatch.setattr(qemu_tunnel.subprocess, "Popen", lambda *a, **k: fake_process)
    monkeypatch.setattr(qemu_tunnel, "_can_connect", lambda port: True)

    tunnel = QemuTunnel("qemu+ssh://alice@lab-host/system", remote_port=5900)
    tunnel.start(ready_timeout=1)
    tunnel.stop(timeout=0.1)

    assert fake_process.terminate_called
    assert fake_process.killed


def test_free_local_port_returns_a_bindable_port():
    port = qemu_tunnel._free_local_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # would raise OSError if not actually free

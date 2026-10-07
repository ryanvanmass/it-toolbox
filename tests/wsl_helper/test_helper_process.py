"""Spawns the real helper (python -m it_toolbox.wsl_helper) natively --
the same code path Windows takes through wsl.exe, minus wsl.exe."""

import json
import subprocess
import sys
import time

import pytest

from it_toolbox.core import linux_backend
from it_toolbox.core.wsl import helper_process, transport
from it_toolbox.wsl_helper import selftest_service


class _ThisPythonBackend(linux_backend.NativeBackend):
    """Runs the helper with the test interpreter, not whatever `python3`
    is on PATH."""

    def popen_argv(self, argv):
        return [sys.executable if a == "python3" else a for a in argv]


def test_helper_argv_sets_pythonpath_via_env():
    argv = helper_process.helper_argv(linux_backend.NativeBackend(), "spice")
    assert argv[0] == "env"
    assert argv[1] == f"PYTHONPATH={helper_process.package_root()}"
    assert argv[2:] == ["PYTHONDONTWRITEBYTECODE=1", "python3", "-m", "it_toolbox.wsl_helper", "spice"]


def test_helper_argv_translates_pythonpath_for_wsl(monkeypatch):
    monkeypatch.setattr(helper_process, "package_root", lambda: r"C:\Program Files\IT Toolbox\Lib\site-packages")
    monkeypatch.setattr(linux_backend.wsl_distro, "wsl_exe", lambda: "wsl.exe")
    argv = helper_process.helper_argv(linux_backend.WslBackend(), "spice")
    assert argv[:5] == ["wsl.exe", "-d", "it-toolbox", "--exec", "env"]
    assert argv[5] == "PYTHONPATH=/mnt/c/Program Files/IT Toolbox/Lib/site-packages"


def test_selftest_service_end_to_end():
    helper = helper_process.HelperProcess("selftest", {}, backend=_ThisPythonBackend())
    conn = helper.start(handshake_timeout=20)
    try:
        msg_type, payload = conn.recv()
        assert msg_type == selftest_service.READY
        assert json.loads(payload)["python"]
        conn.send(transport.MSG_SERVICE_BASE + 5, b"ping")
        assert conn.recv() == (transport.MSG_SERVICE_BASE + 5, b"ping")
    finally:
        helper.stop()
    assert helper._process.returncode == 0


def test_unknown_service_fails_with_stderr_detail():
    helper = helper_process.HelperProcess("nope", {}, backend=_ThisPythonBackend())
    with pytest.raises(transport.TransportError, match="usage"):
        helper.start(handshake_timeout=20)


def test_helper_exits_when_its_stdin_closes():
    """A crashed app closes the helper's stdin -- the helper must not
    outlive it, even mid-session."""
    argv = helper_process.helper_argv(_ThisPythonBackend(), "selftest")
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    port, token = transport.parse_handshake_line(process.stdout.readline().decode())
    conn = transport.connect(port, token, {})
    assert conn.recv()[0] == selftest_service.READY

    process.stdin.close()
    deadline = time.monotonic() + 10
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None
    conn.close()


def test_helper_modules_never_import_pyside6():
    """The distro has no PySide6: everything the helper imports must work
    without it."""
    script = """
import builtins
real_import = builtins.__import__
def fake_import(name, *args, **kwargs):
    if name == "PySide6" or name.startswith("PySide6."):
        raise ImportError("PySide6 is not installed in the WSL distro")
    return real_import(name, *args, **kwargs)
builtins.__import__ = fake_import
import it_toolbox.wsl_helper.__main__
import it_toolbox.wsl_helper.selftest_service
import it_toolbox.wsl_helper.spice_service
import it_toolbox.core.linux_tools
print("OK")
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout

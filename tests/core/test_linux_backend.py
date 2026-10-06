import subprocess

import pytest

from it_toolbox.core import linux_backend, linux_tools, wsl_distro


@pytest.fixture(autouse=True)
def _fresh_backend_cache():
    linux_backend.reset_backend()
    yield
    linux_backend.reset_backend()


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_linux_gets_native_backend(monkeypatch):
    monkeypatch.setattr(linux_backend.sys, "platform", "linux")
    assert linux_backend.get_backend().kind == "native"


def test_windows_without_ready_distro_gets_no_backend(monkeypatch):
    monkeypatch.setattr(linux_backend.sys, "platform", "win32")
    monkeypatch.setattr(
        wsl_distro, "status", lambda: wsl_distro.DistroStatus(wsl_distro.DistroState.NOT_INSTALLED)
    )
    assert linux_backend.get_backend() is None
    assert linux_backend.is_tool_available("virsh") is False


def test_windows_with_outdated_distro_gets_no_backend(monkeypatch):
    monkeypatch.setattr(linux_backend.sys, "platform", "win32")
    monkeypatch.setattr(
        wsl_distro, "status", lambda: wsl_distro.DistroStatus(wsl_distro.DistroState.OUTDATED, 0)
    )
    assert linux_backend.get_backend() is None


def test_windows_with_ready_distro_gets_wsl_backend(monkeypatch):
    monkeypatch.setattr(linux_backend.sys, "platform", "win32")
    monkeypatch.setattr(
        wsl_distro, "status", lambda: wsl_distro.DistroStatus(wsl_distro.DistroState.READY, 1)
    )
    backend = linux_backend.get_backend()
    assert backend.kind == "wsl"
    assert linux_backend.is_wsl() is True
    # Every registry tool is baked into a current rootfs -- no process spawned.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned a process"))
    assert all(linux_backend.is_tool_available(t.id) for t in linux_tools.TOOLS)


def test_backend_is_cached_until_reset(monkeypatch):
    calls = []
    monkeypatch.setattr(linux_backend.sys, "platform", "win32")

    def fake_status():
        calls.append(1)
        return wsl_distro.DistroStatus(wsl_distro.DistroState.NOT_INSTALLED)

    monkeypatch.setattr(wsl_distro, "status", fake_status)
    linux_backend.get_backend()
    linux_backend.get_backend()
    assert len(calls) == 1
    linux_backend.reset_backend()
    linux_backend.get_backend()
    assert len(calls) == 2


def test_native_run_keeps_plain_subprocess_shape(monkeypatch):
    seen = {}

    def fake_run(cmd, capture_output, text, timeout):
        seen.update(cmd=cmd, timeout=timeout)
        return _completed(stdout="ok")

    monkeypatch.setattr(linux_backend.subprocess, "run", fake_run)
    result = linux_backend.NativeBackend().run(("virsh", "list"), timeout=8)
    assert result.stdout == "ok"
    assert seen == {"cmd": ["virsh", "list"], "timeout": 8}


def test_wsl_run_wraps_argv_with_exec_and_boot_timeout_first(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _completed(stdout="out")

    monkeypatch.setattr(linux_backend.subprocess, "run", fake_run)
    monkeypatch.setattr(wsl_distro, "wsl_exe", lambda: "wsl.exe")
    backend = linux_backend.WslBackend()

    backend.run(["virsh", "-c", "qemu+ssh://a@b/system", "list"], timeout=8)
    backend.run(["virsh", "list"], timeout=8)

    first_cmd, first_kwargs = calls[0]
    assert first_cmd == ["wsl.exe", "-d", "it-toolbox", "--exec", "virsh", "-c", "qemu+ssh://a@b/system", "list"]
    assert first_kwargs["timeout"] == linux_backend._WSL_BOOT_TIMEOUT_SEC
    assert first_kwargs["encoding"] == "utf-8"
    assert first_kwargs["env"]["WSL_UTF8"] == "1"
    # Once the distro has answered once, callers' own timeouts apply again.
    assert calls[1][1]["timeout"] == 8


def test_wsl_run_cleans_utf16_stderr_from_wsl_exe(monkeypatch):
    monkeypatch.setattr(
        linux_backend.subprocess, "run", lambda *a, **k: _completed(stderr="n\x00o\x00p\x00e\x00", returncode=1)
    )
    result = linux_backend.WslBackend().run(["virsh"], timeout=8)
    assert result.stderr == "nope"


def test_wsl_probe_tool_uses_probe_or_command_v(monkeypatch):
    calls = []
    monkeypatch.setattr(
        linux_backend.subprocess, "run", lambda cmd, **k: calls.append(cmd) or _completed()
    )
    backend = linux_backend.WslBackend()
    assert backend.probe_tool(linux_tools.get("virsh")) is True
    assert backend.probe_tool(linux_tools.get("spice")) is True
    assert calls[0][-5:] == ["sh", "-c", 'command -v "$1" >/dev/null', "sh", "virsh"]
    assert calls[1][4:] == list(linux_tools.get("spice").probe)


def test_wsl_probe_tool_false_on_failure(monkeypatch):
    monkeypatch.setattr(linux_backend.subprocess, "run", lambda *a, **k: _completed(returncode=1))
    assert linux_backend.WslBackend().probe_tool(linux_tools.get("virsh")) is False


@pytest.mark.parametrize(
    ("windows", "linux"),
    [
        (r"C:\Users\me\AppData\Local\Temp\tmp1.xml", "/mnt/c/Users/me/AppData/Local/Temp/tmp1.xml"),
        (r"D:\a b\c", "/mnt/d/a b/c"),
        ("C:\\", "/mnt/c"),
    ],
)
def test_windows_to_wsl_path(windows, linux):
    assert linux_backend.windows_to_wsl_path(windows) == linux


def test_windows_to_wsl_path_rejects_unc():
    with pytest.raises(ValueError):
        linux_backend.windows_to_wsl_path(r"\\server\share\x")

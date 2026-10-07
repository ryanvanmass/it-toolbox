import subprocess
from pathlib import Path

import pytest

from it_toolbox.core import rclone_mount


class _FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def linux(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_mount.sys, "platform", "linux")
    monkeypatch.setattr(rclone_mount.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(rclone_mount.rclone_client, "is_available", lambda: True)
    monkeypatch.setattr(rclone_mount, "mount_support_problem", lambda: None)
    monkeypatch.setattr(rclone_mount, "_POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(rclone_mount.Mount, "pending_transfers", lambda self: 0)
    return tmp_path


def test_linux_support_ok_when_fusermount_on_path(monkeypatch):
    monkeypatch.setattr(rclone_mount.sys, "platform", "linux")
    monkeypatch.setattr(
        rclone_mount.shutil,
        "which",
        lambda cmd: "/usr/bin/fusermount3" if cmd == "fusermount3" else None,
    )
    assert rclone_mount.mount_support_problem() is None


def test_linux_support_problem_when_fuse_missing(monkeypatch):
    monkeypatch.setattr(rclone_mount.sys, "platform", "linux")
    monkeypatch.setattr(rclone_mount.shutil, "which", lambda cmd: None)
    assert "FUSE" in rclone_mount.mount_support_problem()


def test_macos_support_problem_when_no_fuse_layer(monkeypatch):
    monkeypatch.setattr(rclone_mount.sys, "platform", "darwin")
    monkeypatch.setattr(rclone_mount, "_MACOS_FUSE_PATHS", ("/definitely/not/here",))
    assert "macFUSE" in rclone_mount.mount_support_problem()


def test_macos_support_ok_with_fuse_layer(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_mount.sys, "platform", "darwin")
    monkeypatch.setattr(rclone_mount, "_MACOS_FUSE_PATHS", (str(tmp_path),))
    assert rclone_mount.mount_support_problem() is None


def test_windows_support_problem_when_winfsp_missing(monkeypatch):
    monkeypatch.setattr(rclone_mount.sys, "platform", "win32")
    monkeypatch.setattr(rclone_mount, "_windows_has_winfsp", lambda: False)
    assert "WinFsp" in rclone_mount.mount_support_problem()


def test_windows_winfsp_found_under_program_files(monkeypatch, tmp_path):
    (tmp_path / "WinFsp" / "bin").mkdir(parents=True)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    assert rclone_mount._windows_has_winfsp() is True


def test_free_drive_letter_starts_at_z_and_skips_used(monkeypatch):
    used = {"Z:\\", "Y:\\"}
    monkeypatch.setattr(rclone_mount.os.path, "exists", lambda p: p in used)
    assert rclone_mount.free_drive_letter() == "X:"


def test_free_drive_letter_none_when_all_taken(monkeypatch):
    monkeypatch.setattr(rclone_mount.os.path, "exists", lambda p: True)
    assert rclone_mount.free_drive_letter() is None


def test_default_mount_point_on_windows_is_a_drive_letter(monkeypatch):
    monkeypatch.setattr(rclone_mount.sys, "platform", "win32")
    monkeypatch.setattr(rclone_mount, "free_drive_letter", lambda: "Z:")
    assert rclone_mount.default_mount_point("gdrive") == "Z:"


def test_default_mount_point_on_linux_is_under_home(linux):
    assert rclone_mount.default_mount_point("gdrive") == str(linux / "CloudMounts" / "gdrive")


def test_mount_starts_rclone_and_tracks_it(linux, monkeypatch):
    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProcess()

    monkeypatch.setattr(rclone_mount.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rclone_mount, "_is_mounted", lambda p: bool(calls))
    manager = rclone_mount.MountManager()

    target = manager.mount("gdrive")

    expected = str(linux / "CloudMounts" / "gdrive")
    assert target == expected
    assert Path(expected).is_dir()
    assert calls[0][1:4] == ["mount", "gdrive:", expected]
    assert manager.mount_point("gdrive") == expected
    assert manager.mounted_remotes() == ["gdrive"]


def test_mount_raises_rclone_error_when_process_exits(linux, monkeypatch):
    def fake_popen(cmd, stderr, **kwargs):
        stderr.write("mount helper error: fusermount3: not permitted\n")
        stderr.flush()
        return _FakeProcess(returncode=1)

    monkeypatch.setattr(rclone_mount.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rclone_mount, "_is_mounted", lambda p: False)
    manager = rclone_mount.MountManager()

    with pytest.raises(rclone_mount.MountError, match="not permitted"):
        manager.mount("gdrive")
    assert not manager.is_mounted("gdrive")


def test_mount_refuses_non_empty_folder(linux, monkeypatch):
    target = linux / "CloudMounts" / "gdrive"
    target.mkdir(parents=True)
    (target / "stray.txt").write_text("x")
    monkeypatch.setattr(rclone_mount, "_is_mounted", lambda p: False)

    with pytest.raises(rclone_mount.MountError, match="isn't empty"):
        rclone_mount.MountManager().mount("gdrive")


def test_mount_reports_missing_fuse(linux, monkeypatch):
    monkeypatch.setattr(rclone_mount, "mount_support_problem", lambda: "need FUSE")
    with pytest.raises(rclone_mount.MountError, match="need FUSE"):
        rclone_mount.MountManager().mount("gdrive")


def test_unmount_stops_the_process(linux, monkeypatch):
    process = _FakeProcess()
    mounted = {"value": False}

    def fake_popen(cmd, **kwargs):
        mounted["value"] = True
        return process

    monkeypatch.setattr(rclone_mount.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rclone_mount, "_is_mounted", lambda p: mounted["value"])
    manager = rclone_mount.MountManager()
    manager.mount("gdrive")

    def terminate():
        process.returncode = 0
        mounted["value"] = False

    process.terminate = terminate
    manager.unmount("gdrive")

    assert process.returncode == 0
    assert not manager.is_mounted("gdrive")


def test_mount_forgotten_when_rclone_dies_on_its_own(linux, monkeypatch):
    process = _FakeProcess()
    started = []
    monkeypatch.setattr(
        rclone_mount.subprocess, "Popen", lambda cmd, **k: started.append(cmd) or process
    )
    monkeypatch.setattr(rclone_mount, "_is_mounted", lambda p: bool(started))
    manager = rclone_mount.MountManager()
    manager.mount("gdrive")

    process.returncode = 1

    assert manager.mount_point("gdrive") is None


def test_mount_passes_no_window_kwargs(linux, monkeypatch):
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(rclone_mount.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rclone_mount, "_is_mounted", lambda p: bool(seen))
    monkeypatch.setattr(rclone_mount, "no_window_kwargs", lambda: {"creationflags": 0x08000000})

    rclone_mount.MountManager().mount("gdrive")

    assert seen["creationflags"] == 0x08000000
    assert seen["stdin"] is subprocess.DEVNULL


def test_unmount_waits_for_pending_uploads_before_stopping(linux, monkeypatch):
    process = _FakeProcess()
    started = []
    monkeypatch.setattr(
        rclone_mount.subprocess, "Popen", lambda cmd, **k: started.append(k) or process
    )
    monkeypatch.setattr(
        rclone_mount, "_is_mounted", lambda p: bool(started) and not process.terminated
    )
    monkeypatch.setattr(rclone_mount.time, "sleep", lambda s: None)
    pending = [2, 1, 0]
    checks = []

    def fake_pending(self):
        checks.append(process.terminated)
        return pending.pop(0)

    monkeypatch.setattr(rclone_mount.Mount, "pending_transfers", fake_pending)
    manager = rclone_mount.MountManager()
    manager.mount("gdrive")

    manager.unmount("gdrive")

    assert checks == [False, False, False]
    assert process.terminated
    # The rc password goes via environment, never argv.
    assert started[0]["env"]["RCLONE_RC_PASS"]


def test_pending_transfers_sums_rc_stats(monkeypatch):
    class _Response:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_post(url, auth, timeout):
        assert auth == ("it-toolbox", "secret")
        if url.endswith("/core/stats"):
            return _Response({"transferring": [{"name": "a"}]})
        return _Response({"diskCache": {"uploadsInProgress": 1, "uploadsQueued": 2}})

    monkeypatch.setattr(rclone_mount.requests, "post", fake_post)
    mount = rclone_mount.Mount("gdrive", "/m", _FakeProcess(), "/log", 1234, "secret")

    assert mount.pending_transfers() == 4


def test_pending_transfers_zero_when_rc_unreachable(monkeypatch):
    def fake_post(*a, **k):
        raise rclone_mount.requests.ConnectionError("refused")

    monkeypatch.setattr(rclone_mount.requests, "post", fake_post)
    mount = rclone_mount.Mount("gdrive", "/m", _FakeProcess(), "/log", 1234, "secret")

    assert mount.pending_transfers() == 0

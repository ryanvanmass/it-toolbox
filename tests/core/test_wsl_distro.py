import hashlib
import subprocess

import pytest

from it_toolbox.core import wsl_distro


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(wsl_distro.sys, "platform", "win32")
    monkeypatch.setattr(wsl_distro, "install_dir", lambda: tmp_path / "wsl")
    monkeypatch.setattr(wsl_distro, "is_wsl_installed", lambda: True)
    return tmp_path


def test_status_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(wsl_distro.sys, "platform", "linux")
    assert wsl_distro.status().state is wsl_distro.DistroState.UNSUPPORTED


def test_status_no_wsl(windows, monkeypatch):
    monkeypatch.setattr(wsl_distro, "is_wsl_installed", lambda: False)
    assert wsl_distro.status().state is wsl_distro.DistroState.NO_WSL


def test_status_not_installed(windows, monkeypatch):
    monkeypatch.setattr(wsl_distro, "_registered_distro_names", lambda: ["Ubuntu"])
    assert wsl_distro.status().state is wsl_distro.DistroState.NOT_INSTALLED


def test_status_outdated_without_marker(windows, monkeypatch):
    monkeypatch.setattr(wsl_distro, "_registered_distro_names", lambda: ["it-toolbox"])
    status = wsl_distro.status()
    assert status.state is wsl_distro.DistroState.OUTDATED
    assert status.installed_version is None


def test_status_outdated_with_older_marker(windows, monkeypatch):
    monkeypatch.setattr(wsl_distro, "_registered_distro_names", lambda: ["it-toolbox"])
    monkeypatch.setattr(wsl_distro, "ROOTFS_VERSION", 3)
    (windows / "wsl").mkdir()
    (windows / "wsl" / "rootfs-version").write_text("2")
    assert wsl_distro.status() == wsl_distro.DistroStatus(wsl_distro.DistroState.OUTDATED, 2)


def test_status_ready(windows, monkeypatch):
    monkeypatch.setattr(wsl_distro, "_registered_distro_names", lambda: ["it-toolbox"])
    (windows / "wsl").mkdir()
    (windows / "wsl" / "rootfs-version").write_text(str(wsl_distro.ROOTFS_VERSION))
    status = wsl_distro.status()
    assert status.ready
    assert status.installed_version == wsl_distro.ROOTFS_VERSION


def test_status_never_spawns_wsl_exe(windows, monkeypatch):
    monkeypatch.setattr(wsl_distro, "_registered_distro_names", lambda: ["it-toolbox"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned wsl.exe"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("spawned wsl.exe"))
    wsl_distro.status()


def test_clean_wsl_output_strips_utf16_artifacts():
    assert wsl_distro.clean_wsl_output("\ufeffU\x00b\x00u\x00n\x00t\x00u\x00\n") == "Ubuntu"


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body
        self.text = body.decode(errors="replace")
        self.headers = {"Content-Length": str(len(body))}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_requests(monkeypatch, tarball: bytes, digest: str):
    def fake_get(url, timeout, stream=False):
        if url == wsl_distro.ROOTFS_SHA256_URL:
            return _FakeResponse(f"{digest}  {wsl_distro.ROOTFS_ASSET_NAME}\n".encode())
        assert url == wsl_distro.ROOTFS_URL
        return _FakeResponse(tarball)

    monkeypatch.setattr(wsl_distro.requests, "get", fake_get)


def test_install_verifies_imports_and_writes_marker(windows, monkeypatch):
    tarball = b"rootfs bytes"
    _fake_requests(monkeypatch, tarball, hashlib.sha256(tarball).hexdigest())
    monkeypatch.setattr(wsl_distro, "is_distro_registered", lambda: True)
    wsl_calls = []
    monkeypatch.setattr(wsl_distro, "_run_wsl", lambda *args, **k: wsl_calls.append(args) or "")
    progress = []

    wsl_distro.install(on_progress=lambda done, total: progress.append((done, total)))

    assert wsl_calls[0] == ("--unregister", "it-toolbox")
    assert wsl_calls[1][:3] == ("--import", "it-toolbox", str(windows / "wsl"))
    assert wsl_calls[1][-2:] == ("--version", "2")
    assert (windows / "wsl" / "rootfs-version").read_text() == str(wsl_distro.ROOTFS_VERSION)
    assert progress[-1] == (len(tarball), len(tarball))
    # The downloaded tarball is cleaned up afterwards.
    assert not list(windows.glob("*.tar.gz"))


def test_install_refuses_checksum_mismatch(windows, monkeypatch):
    _fake_requests(monkeypatch, b"tampered", "0" * 64)
    monkeypatch.setattr(wsl_distro, "_run_wsl", lambda *a, **k: pytest.fail("imported a bad rootfs"))

    with pytest.raises(wsl_distro.WslDistroError, match="checksum"):
        wsl_distro.install()
    assert not list(windows.glob("*.tar.gz"))


def test_install_rejects_malformed_checksum_file(windows, monkeypatch):
    _fake_requests(monkeypatch, b"x", "not-a-digest")
    with pytest.raises(wsl_distro.WslDistroError, match="malformed"):
        wsl_distro.install()


def test_remove_unregisters_and_deletes(windows, monkeypatch):
    (windows / "wsl").mkdir()
    (windows / "wsl" / "rootfs-version").write_text("1")
    monkeypatch.setattr(wsl_distro, "is_distro_registered", lambda: True)
    calls = []
    monkeypatch.setattr(wsl_distro, "_run_wsl", lambda *args, **k: calls.append(args) or "")

    wsl_distro.remove()

    assert calls == [("--unregister", "it-toolbox")]
    assert not (windows / "wsl").exists()


def test_run_wsl_raises_cleaned_error(monkeypatch):
    monkeypatch.setattr(
        wsl_distro.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 1, stdout="", stderr="b\x00a\x00d\x00"),
    )
    with pytest.raises(wsl_distro.WslDistroError, match="^bad$"):
        wsl_distro._run_wsl("--import")


class _FakeBackend:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def run(self, argv, *, timeout, input=None):
        self.calls.append((argv, input))
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr="denied")


def test_sync_ssh_credentials_copies_keys_and_known_hosts_only(tmp_path):
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("PRIVATE")
    (ssh / "id_ed25519.pub").write_text("PUBLIC")
    (ssh / "known_hosts").write_text("lab ssh-ed25519 AAAA")
    (ssh / "config").write_text("IdentityFile C:\\Users\\me\\.ssh\\id_ed25519")
    backend = _FakeBackend()

    copied = wsl_distro.sync_ssh_credentials(backend, ssh)

    assert copied == 3
    names = [argv[-1] for argv, _ in backend.calls]
    assert names == ["id_ed25519", "id_ed25519.pub", "known_hosts"]
    assert backend.calls[0][1] == "PRIVATE"
    assert "chmod 600" in backend.calls[0][0][2]


def test_sync_ssh_credentials_without_ssh_dir_is_a_noop(tmp_path):
    assert wsl_distro.sync_ssh_credentials(_FakeBackend(), tmp_path / "missing") == 0


def test_sync_ssh_credentials_raises_on_failure(tmp_path):
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "id_rsa").write_text("K")
    with pytest.raises(wsl_distro.WslDistroError, match="id_rsa"):
        wsl_distro.sync_ssh_credentials(_FakeBackend(returncode=1), ssh)

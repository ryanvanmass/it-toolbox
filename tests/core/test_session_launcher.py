import pytest

from it_toolbox.core import session_launcher


class _PopenRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, *a, **kw):
        self.calls.append(args)


@pytest.fixture
def popen(monkeypatch, tmp_path):
    # .rdp files land in tmp_path rather than the real temp dir.
    monkeypatch.setattr(session_launcher.tempfile, "tempdir", str(tmp_path))
    recorder = _PopenRecorder()
    monkeypatch.setattr(session_launcher.subprocess, "Popen", recorder)
    # Don't leave real 15s timers running behind the test.
    monkeypatch.setattr(session_launcher.threading, "Timer", lambda *a, **kw: _NoopTimer())
    return recorder


class _NoopTimer:
    def start(self):
        pass


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(session_launcher.platform, "system", lambda: "Darwin")


def test_macos_rdp_opens_an_rdp_file_in_windows_app(popen, darwin, monkeypatch, tmp_path):
    (tmp_path / "Windows App.app").mkdir()
    monkeypatch.setattr(session_launcher, "_MACOS_APP_DIRS", (str(tmp_path),))

    session_launcher.launch_rdp("localhost", 50123, "alice")

    [args] = popen.calls
    assert args[:3] == ["open", "-a", "Windows App"]
    content = open(args[3]).read()
    assert "full address:s:localhost:50123" in content
    assert "username:s:alice" in content


def test_macos_rdp_falls_back_to_homebrew_sdl_freerdp(popen, darwin, monkeypatch, tmp_path):
    monkeypatch.setattr(session_launcher, "_MACOS_APP_DIRS", (str(tmp_path),))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sdl_freerdp = bin_dir / "sdl-freerdp"
    sdl_freerdp.write_text("#!/bin/sh\n")
    sdl_freerdp.chmod(0o755)
    monkeypatch.setattr(session_launcher, "_HOMEBREW_BIN_DIRS", (str(bin_dir),))
    monkeypatch.setenv("PATH", "")

    session_launcher.launch_rdp("localhost", 50123)

    assert popen.calls == [[str(sdl_freerdp), "/v:localhost:50123", "/cert:ignore", "/dynamic-resolution"]]


def test_macos_rdp_without_any_client_raises_with_install_hint(popen, darwin, monkeypatch, tmp_path):
    monkeypatch.setattr(session_launcher, "_MACOS_APP_DIRS", (str(tmp_path),))
    monkeypatch.setattr(session_launcher, "_HOMEBREW_BIN_DIRS", (str(tmp_path),))
    monkeypatch.setenv("PATH", "")

    with pytest.raises(session_launcher.SessionLaunchError, match="brew install freerdp"):
        session_launcher.launch_rdp("localhost", 50123)
    assert popen.calls == []


def test_macos_ssh_opens_terminal_app_via_osascript(popen, darwin):
    session_launcher.launch_ssh("localhost", 2222, "bob")

    [args] = popen.calls
    assert args[0] == "osascript"
    assert 'tell application "Terminal" to do script "ssh -p 2222 bob@localhost"' in args


def test_macos_ssh_escapes_quotes_for_applescript(popen, darwin):
    session_launcher._spawn_in_macos_terminal(["echo", 'say "hi"'])

    [args] = popen.calls
    # shlex.join single-quotes the argument; its inner double quotes must
    # then be backslash-escaped inside the AppleScript string literal.
    assert args[2] == 'tell application "Terminal" to do script "echo \'say \\"hi\\"\'"'


def test_windows_rdp_still_launches_mstsc_with_an_rdp_file(popen, monkeypatch):
    monkeypatch.setattr(session_launcher.platform, "system", lambda: "Windows")

    session_launcher.launch_rdp("localhost", 50123)

    [args] = popen.calls
    assert args[0] == "mstsc.exe"
    assert args[1].endswith(".rdp")

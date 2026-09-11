import subprocess
from pathlib import Path

import pytest

from it_toolbox.core import update_checker


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_get_latest_release_returns_none_when_no_release_exists(monkeypatch):
    monkeypatch.setattr(
        update_checker.requests, "get", lambda url, timeout: _FakeResponse(status_code=404)
    )

    assert update_checker.get_latest_release() is None


def test_get_latest_release_parses_tag_and_url(monkeypatch):
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout: _FakeResponse(
            json_data={
                "tag_name": "v1.2.3",
                "html_url": "https://github.com/ryanvanmass/it-toolbox/releases/tag/v1.2.3",
            }
        ),
    )

    release = update_checker.get_latest_release()

    assert release.version == "1.2.3"
    assert release.html_url == "https://github.com/ryanvanmass/it-toolbox/releases/tag/v1.2.3"


@pytest.mark.parametrize(
    ("installed", "latest", "expected"),
    [
        ("1.0.0", "1.0.1", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.1", "1.0.0", False),
        ("1.0.0", "not-a-version", False),
    ],
)
def test_is_update_available(installed, latest, expected):
    assert update_checker.is_update_available(installed, latest) is expected


def test_get_latest_release_finds_the_windows_exe_asset(monkeypatch):
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout: _FakeResponse(
            json_data={
                "tag_name": "v1.2.3",
                "html_url": "https://example.com/v1.2.3",
                "assets": [
                    {
                        "name": "it-toolbox_1.2.3_amd64.deb",
                        "browser_download_url": "https://example.com/deb",
                    },
                    {
                        "name": "it-toolbox-1.2.3-setup.exe",
                        "browser_download_url": "https://example.com/setup.exe",
                    },
                ],
            }
        ),
    )

    release = update_checker.get_latest_release()

    assert release.windows_installer_url == "https://example.com/setup.exe"


def test_get_latest_release_include_prerelease_hits_the_list_endpoint(monkeypatch):
    captured_urls = []

    def _fake_get(url, timeout):
        captured_urls.append(url)
        return _FakeResponse(
            json_data=[
                {"tag_name": "v2.0.0-beta.1", "html_url": "https://example.com/beta"},
                {"tag_name": "v1.0.0", "html_url": "https://example.com/stable"},
            ]
        )

    monkeypatch.setattr(update_checker.requests, "get", _fake_get)

    release = update_checker.get_latest_release(include_prerelease=True)

    assert captured_urls == [update_checker._RELEASES_LIST_URL]
    assert release.version == "2.0.0-beta.1"
    assert release.html_url == "https://example.com/beta"


def test_get_latest_release_include_prerelease_returns_none_when_list_is_empty(monkeypatch):
    monkeypatch.setattr(
        update_checker.requests, "get", lambda url, timeout: _FakeResponse(json_data=[])
    )

    assert update_checker.get_latest_release(include_prerelease=True) is None


@pytest.mark.parametrize("json_data", [{"tag_name": "v1.2.3", "html_url": "https://example.com"}])
def test_get_latest_release_windows_installer_url_is_none_without_an_exe_asset(
    monkeypatch, json_data
):
    monkeypatch.setattr(update_checker.requests, "get", lambda url, timeout: _FakeResponse(json_data=json_data))

    release = update_checker.get_latest_release()

    assert release.windows_installer_url is None


class _FakeDownloadResponse:
    def __init__(self, content: bytes = b"fake-installer-bytes", status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakePopen:
    """Records every subprocess.Popen(...) call this test made, and lets
    the test script what proc.wait() should do for each one in order."""

    calls: list[list[str]] = []
    wait_results: list[object] = []  # int returncode, or an Exception instance to raise

    def __init__(self, args, **kwargs):
        _FakePopen.calls.append(args)

    def wait(self, timeout=None):
        result = _FakePopen.wait_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _reset_fake_popen():
    _FakePopen.calls = []
    _FakePopen.wait_results = []
    yield


def test_download_and_install_windows_update_launches_the_silent_installer_then_relaunches(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(update_checker.requests, "get", lambda url, timeout: _FakeDownloadResponse())
    monkeypatch.setattr(update_checker.subprocess, "Popen", _FakePopen)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    _FakePopen.wait_results = [0]

    update_checker.download_and_install_windows_update("https://example.com/setup.exe")

    assert len(_FakePopen.calls) == 2
    installer_call, relaunch_call = _FakePopen.calls
    assert installer_call[1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    assert installer_call[0].endswith(".exe")
    assert relaunch_call == [str(tmp_path / "IT Toolbox" / "pythonw.exe"), "-m", "it_toolbox"]


def test_download_and_install_windows_update_raises_on_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(update_checker.requests, "get", lambda url, timeout: _FakeDownloadResponse())
    monkeypatch.setattr(update_checker.subprocess, "Popen", _FakePopen)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    _FakePopen.wait_results = [1]

    with pytest.raises(update_checker.UpdateInstallError, match="exited with code 1"):
        update_checker.download_and_install_windows_update("https://example.com/setup.exe")

    # No relaunch attempted after a failed install.
    assert len(_FakePopen.calls) == 1


def test_download_and_install_windows_update_raises_on_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(update_checker.requests, "get", lambda url, timeout: _FakeDownloadResponse())
    monkeypatch.setattr(update_checker.subprocess, "Popen", _FakePopen)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    _FakePopen.wait_results = [subprocess.TimeoutExpired(cmd="setup.exe", timeout=300)]

    try:
        with pytest.raises(update_checker.UpdateInstallError, match="did not finish"):
            update_checker.download_and_install_windows_update("https://example.com/setup.exe")
    finally:
        # Production code deliberately leaves this file in place on a
        # real timeout (see its own comment) since the process might
        # still hold it open -- our fake process never actually runs, so
        # nothing stops the test itself from cleaning it up.
        Path(_FakePopen.calls[0][0]).unlink(missing_ok=True)

    assert len(_FakePopen.calls) == 1


def test_get_installed_version_reads_real_package_metadata():
    # Not mocked deliberately — the installed dev copy of it-toolbox is
    # real, so this is a genuine end-to-end check of the importlib.metadata
    # lookup rather than a re-statement of a mock.
    version = update_checker.get_installed_version()
    assert isinstance(version, str)
    assert version

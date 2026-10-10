import shutil
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


def test_get_latest_release_include_prerelease_picks_highest_version_not_first_entry(
    monkeypatch,
):
    # Reproduces a real, confirmed GitHub API quirk: /releases isn't
    # reliably newest-first right after a publish -- the actual newest
    # release (beta.10 here) can sit several entries deep.
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout: _FakeResponse(
            json_data=[
                {"tag_name": "v0.3.0-beta.9", "html_url": "https://example.com/beta.9"},
                {"tag_name": "v0.3.0-beta.8", "html_url": "https://example.com/beta.8"},
                {"tag_name": "v0.3.0-beta.7", "html_url": "https://example.com/beta.7"},
                {"tag_name": "v0.3.0-beta.10", "html_url": "https://example.com/beta.10"},
            ]
        ),
    )

    release = update_checker.get_latest_release(include_prerelease=True)

    assert release.version == "0.3.0-beta.10"
    assert release.html_url == "https://example.com/beta.10"


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
    def __init__(
        self,
        content: bytes = b"fake-installer-bytes",
        status_code: int = 200,
        content_length: int | None = None,
    ) -> None:
        self._content = content
        self.status_code = status_code
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakePopen:
    """Records every subprocess.Popen(...) call this test made."""

    calls: list[list[str]] = []

    def __init__(self, args, **kwargs):
        _FakePopen.calls.append(args)


@pytest.fixture(autouse=True)
def _reset_fake_popen():
    _FakePopen.calls = []
    yield


def test_download_and_install_windows_update_launches_the_silent_installer_detached(
    monkeypatch,
):
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout, stream=True: _FakeDownloadResponse(
            content_length=len(b"fake-installer-bytes")
        ),
    )
    monkeypatch.setattr(update_checker.subprocess, "Popen", _FakePopen)

    update_checker.download_and_install_windows_update("https://example.com/setup.exe")

    # Launched and left to run on its own -- this process doesn't wait
    # for it, and doesn't relaunch the app itself either (Inno Setup's
    # own postinstall [Run] entry does that now; see the docstring for
    # why this process can't safely stick around to do it).
    assert len(_FakePopen.calls) == 1
    installer_call = _FakePopen.calls[0]
    assert installer_call[1:] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    assert installer_call[0].endswith(".exe")


def test_download_and_install_windows_update_reports_progress(monkeypatch):
    content = b"x" * 30  # 3 chunks at chunk_size=10, to exercise multiple progress calls
    monkeypatch.setattr(update_checker, "_DOWNLOAD_CHUNK_SIZE", 10)
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout, stream=True: _FakeDownloadResponse(
            content=content, content_length=len(content)
        ),
    )
    monkeypatch.setattr(update_checker.subprocess, "Popen", _FakePopen)
    progress_calls = []

    update_checker.download_and_install_windows_update(
        "https://example.com/setup.exe", on_progress=lambda d, t: progress_calls.append((d, t))
    )

    assert progress_calls == [(10, 30), (20, 30), (30, 30)]


def test_download_and_install_windows_update_progress_total_is_zero_without_content_length(
    monkeypatch,
):
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout, stream=True: _FakeDownloadResponse(),  # no content_length
    )
    monkeypatch.setattr(update_checker.subprocess, "Popen", _FakePopen)
    progress_calls = []

    update_checker.download_and_install_windows_update(
        "https://example.com/setup.exe", on_progress=lambda d, t: progress_calls.append((d, t))
    )

    assert progress_calls
    assert all(total == 0 for _downloaded, total in progress_calls)


def test_download_and_install_windows_update_raises_if_installer_fails_to_start(monkeypatch):
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout, stream=True: _FakeDownloadResponse(
            content_length=len(b"fake-installer-bytes")
        ),
    )

    def _raise(args, **kwargs):
        raise OSError("access denied")

    monkeypatch.setattr(update_checker.subprocess, "Popen", _raise)

    with pytest.raises(update_checker.UpdateInstallError, match="Failed to launch installer"):
        update_checker.download_and_install_windows_update("https://example.com/setup.exe")


def test_get_installed_version_reads_real_package_metadata():
    # Not mocked deliberately — the installed dev copy of it-toolbox is
    # real, so this is a genuine end-to-end check of the importlib.metadata
    # lookup rather than a re-statement of a mock.
    version = update_checker.get_installed_version()
    assert isinstance(version, str)
    assert version


def _release_with_assets(monkeypatch, names):
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout: _FakeResponse(
            json_data={
                "tag_name": "v1.2.3",
                "html_url": "https://example.com/v1.2.3",
                "assets": [
                    {"name": name, "browser_download_url": f"https://example.com/{name}"} for name in names
                ],
            }
        ),
    )
    return update_checker.get_latest_release()


def test_get_latest_release_finds_the_macos_dmg_asset(monkeypatch):
    release = _release_with_assets(
        monkeypatch, ["it-toolbox-1.2.3-setup.exe", "IT-Toolbox-1.2.3-arm64.dmg"]
    )

    assert release.macos_dmg_url == "https://example.com/IT-Toolbox-1.2.3-arm64.dmg"
    assert release.windows_installer_url == "https://example.com/it-toolbox-1.2.3-setup.exe"


def test_get_latest_release_prefers_the_arm64_dmg(monkeypatch):
    release = _release_with_assets(monkeypatch, ["IT-Toolbox-1.2.3-x86_64.dmg", "IT-Toolbox-1.2.3-arm64.dmg"])

    assert release.macos_dmg_url == "https://example.com/IT-Toolbox-1.2.3-arm64.dmg"


def test_get_latest_release_macos_dmg_url_is_none_without_a_dmg_asset(monkeypatch):
    release = _release_with_assets(monkeypatch, ["it-toolbox-1.2.3-setup.exe"])

    assert release.macos_dmg_url is None


def test_running_app_bundle_finds_the_enclosing_app(monkeypatch):
    monkeypatch.setattr(update_checker.sys, "executable", "/Applications/IT Toolbox.app/Contents/MacOS/python")

    assert str(update_checker.running_app_bundle()) == "/Applications/IT Toolbox.app"


def test_running_app_bundle_is_none_outside_a_bundle(monkeypatch):
    monkeypatch.setattr(update_checker.sys, "executable", "/usr/local/bin/python3")

    assert update_checker.running_app_bundle() is None


def test_macos_install_target_replaces_a_writable_bundle_in_place(tmp_path):
    bundle = tmp_path / "IT Toolbox.app"

    assert update_checker._macos_install_target(bundle) == bundle


class _FakeMacosTools:
    """Stands in for hdiutil/ditto: `attach` populates the mountpoint with
    an app bundle (unless with_app=False), `ditto` copies it."""

    def __init__(self, with_app=True, attach_fails=False):
        self.with_app = with_app
        self.attach_fails = attach_fails
        self.commands: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.commands.append(args)
        if args[:2] == ["hdiutil", "attach"]:
            if self.attach_fails:
                raise subprocess.CalledProcessError(1, args, stderr=b"image not recognized")
            mountpoint = Path(args[args.index("-mountpoint") + 1])
            mountpoint.mkdir(parents=True)
            if self.with_app:
                (mountpoint / "IT Toolbox.app" / "Contents").mkdir(parents=True)
        elif args[0] == "ditto":
            shutil.copytree(args[1], args[2])
        return subprocess.CompletedProcess(args, 0)


@pytest.fixture
def macos_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "apps" / "IT Toolbox.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    monkeypatch.setattr(update_checker.sys, "executable", str(bundle / "Contents" / "MacOS" / "python"))
    monkeypatch.setattr(update_checker.tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout, stream=True: _FakeDownloadResponse(content_length=len(b"fake-installer-bytes")),
    )
    monkeypatch.setattr(update_checker.subprocess, "Popen", _FakePopen)
    return bundle


def test_download_and_install_macos_update_stages_the_app_and_starts_the_swap_helper(monkeypatch, macos_bundle):
    tools = _FakeMacosTools()
    monkeypatch.setattr(update_checker.subprocess, "run", tools)
    progress = []

    update_checker.download_and_install_macos_update(
        "https://example.com/x.dmg", on_progress=lambda d, t: progress.append((d, t))
    )

    assert progress[-1] == (len(b"fake-installer-bytes"), len(b"fake-installer-bytes"))
    assert [c[:2] for c in tools.commands] == [["hdiutil", "attach"], ["ditto", tools.commands[1][1]], ["hdiutil", "detach"]]
    [helper] = _FakePopen.calls
    pid, staged, target, workdir = helper[-4:]
    assert pid == str(update_checker.os.getpid())
    assert Path(staged).is_dir() and Path(staged).name == "IT Toolbox.app"
    assert target == str(macos_bundle)
    assert Path(staged).parent == Path(workdir)
    # The downloaded .dmg itself is cleaned up once unpacked.
    assert not list(Path(update_checker.tempfile.tempdir).glob("*.dmg"))


def test_download_and_install_macos_update_raises_when_the_dmg_has_no_app(monkeypatch, macos_bundle):
    monkeypatch.setattr(update_checker.subprocess, "run", _FakeMacosTools(with_app=False))

    with pytest.raises(update_checker.UpdateInstallError, match="doesn't contain an app"):
        update_checker.download_and_install_macos_update("https://example.com/x.dmg")
    assert _FakePopen.calls == []
    assert not list(Path(update_checker.tempfile.tempdir).iterdir())


def test_download_and_install_macos_update_raises_when_the_dmg_wont_mount(monkeypatch, macos_bundle):
    monkeypatch.setattr(update_checker.subprocess, "run", _FakeMacosTools(attach_fails=True))

    with pytest.raises(update_checker.UpdateInstallError, match="image not recognized"):
        update_checker.download_and_install_macos_update("https://example.com/x.dmg")
    assert _FakePopen.calls == []


def test_download_and_install_macos_update_refuses_outside_a_bundle(monkeypatch):
    monkeypatch.setattr(update_checker.sys, "executable", "/usr/local/bin/python3")

    with pytest.raises(update_checker.UpdateInstallError, match="only available"):
        update_checker.download_and_install_macos_update("https://example.com/x.dmg")


def _run_swap_script(tmp_path, staged, target, workdir):
    # A fake `open` that records what it was asked to launch.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "open").write_text(f'#!/bin/sh\necho "$1" >> "{tmp_path}/opened"\n')
    (bin_dir / "open").chmod(0o755)
    # The PID of a process that has already exited, so the script's
    # wait-for-the-app-to-quit loop falls straight through.
    finished = subprocess.Popen(["true"])
    finished.wait()
    subprocess.run(
        ["/bin/sh", "-c", update_checker._MACOS_SWAP_SCRIPT, "it-toolbox-update",
         str(finished.pid), str(staged), str(target), str(workdir)],
        check=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    return (tmp_path / "opened").read_text().splitlines()


def test_macos_swap_script_replaces_the_bundle_and_relaunches_it(tmp_path):
    workdir = tmp_path / "work"
    staged = workdir / "IT Toolbox.app"
    staged.mkdir(parents=True)
    (staged / "new").write_text("")
    target = tmp_path / "apps" / "IT Toolbox.app"
    target.mkdir(parents=True)
    (target / "old").write_text("")

    opened = _run_swap_script(tmp_path, staged, target, workdir)

    assert (target / "new").exists() and not (target / "old").exists()
    assert not Path(f"{target}.old").exists()
    assert not workdir.exists()
    assert opened == [str(target)]


def test_macos_swap_script_restores_the_old_bundle_if_the_move_fails(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    staged = workdir / "IT Toolbox.app"  # never created, so the move fails
    target = tmp_path / "apps" / "IT Toolbox.app"
    target.mkdir(parents=True)
    (target / "old").write_text("")

    opened = _run_swap_script(tmp_path, staged, target, workdir)

    assert (target / "old").exists()
    assert not Path(f"{target}.old").exists()
    assert opened == [str(target)]


def test_newest_release_ignores_wsl_rootfs_releases():
    # package-wsl.yml publishes `wsl-rootfs-<N>` releases to the same repo
    # (as pre-releases) -- the beta channel must never offer one as an app
    # update.
    releases = [
        {"tag_name": "wsl-rootfs-7"},
        {"tag_name": "v0.3.9-beta.2"},
    ]
    assert update_checker._newest_release(releases)["tag_name"] == "v0.3.9-beta.2"

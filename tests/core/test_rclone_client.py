import json
import subprocess

import pytest

from it_toolbox.core import rclone_client
from it_toolbox.modules.cloud_storage.models import ProviderOption


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(["rclone"], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _rclone_on_path(monkeypatch):
    monkeypatch.setattr(rclone_client.shutil, "which", lambda name: "/usr/bin/rclone")
    # Hermetic by default — a real rclone_path.txt on the machine running
    # this suite (from actually using the app) must not leak into tests.
    monkeypatch.setattr(rclone_client.settings, "load_rclone_path", lambda: None)


# -- Availability ---------------------------------------------------------


def test_is_available_false_when_not_on_path(monkeypatch):
    monkeypatch.setattr(rclone_client.shutil, "which", lambda name: None)
    assert rclone_client.is_available() is False


def test_run_raises_when_not_available(monkeypatch):
    monkeypatch.setattr(rclone_client.shutil, "which", lambda name: None)
    with pytest.raises(rclone_client.RcloneApiError, match="not found"):
        rclone_client.list_remotes()


def test_run_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        rclone_client.subprocess,
        "run",
        lambda *a, **k: _completed(returncode=1, stderr="boom"),
    )
    with pytest.raises(rclone_client.RcloneApiError, match="boom"):
        rclone_client.list_remotes()


def test_is_available_true_when_override_path_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_client.shutil, "which", lambda name: None)
    fake_exe = tmp_path / "rclone.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(rclone_client.settings, "load_rclone_path", lambda: str(fake_exe))

    assert rclone_client.is_available() is True


def test_is_available_false_when_override_path_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_client.shutil, "which", lambda name: "/usr/bin/rclone")
    monkeypatch.setattr(
        rclone_client.settings, "load_rclone_path", lambda: str(tmp_path / "missing.exe")
    )

    assert rclone_client.is_available() is False


def test_run_uses_override_path_as_the_executable(monkeypatch, tmp_path):
    fake_exe = tmp_path / "rclone.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(rclone_client.settings, "load_rclone_path", lambda: str(fake_exe))
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout="{}")

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    rclone_client.list_remotes()

    assert captured["cmd"][0] == str(fake_exe)


def test_run_raises_on_timeout(monkeypatch):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="rclone", timeout=15)

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)
    with pytest.raises(rclone_client.RcloneApiError, match="timed out"):
        rclone_client.list_remotes()


# -- list_remotes -----------------------------------------------------------


def test_list_remotes_parses_config_dump_sorted_case_insensitively(monkeypatch):
    dump = {
        "zBucket": {"type": "s3"},
        "aBucket": {"type": "local"},
    }
    monkeypatch.setattr(
        rclone_client.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(dump))
    )

    remotes = rclone_client.list_remotes()

    assert [r.name for r in remotes] == ["aBucket", "zBucket"]
    assert remotes[0].type == "local"
    assert remotes[1].type == "s3"


def test_list_remotes_empty_dump_returns_empty_list(monkeypatch):
    monkeypatch.setattr(rclone_client.subprocess, "run", lambda *a, **k: _completed(stdout="{}"))
    assert rclone_client.list_remotes() == []


# -- list_providers -----------------------------------------------------------


def test_list_providers_parses_options_and_examples(monkeypatch):
    raw = [
        {
            "Name": "local",
            "Description": "Local Disk",
            "Options": [],
        },
        {
            "Name": "s3",
            "Description": "Amazon S3",
            "Options": [
                {
                    "Name": "provider",
                    "Help": "Choose your S3 provider.",
                    "Type": "string",
                    "Default": "",
                    "Required": False,
                    "IsPassword": False,
                    "Advanced": False,
                    "Exclusive": True,
                    "Examples": [{"Value": "AWS", "Help": "Amazon Web Services"}],
                },
                {
                    "Name": "secret_access_key",
                    "Help": "AWS Secret Access Key.",
                    "Type": "string",
                    "Default": "",
                    "Required": True,
                    "IsPassword": True,
                    "Advanced": False,
                    "Exclusive": False,
                },
            ],
        },
    ]
    monkeypatch.setattr(
        rclone_client.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(raw))
    )

    providers = rclone_client.list_providers()

    assert [p.name for p in providers] == ["local", "s3"]
    s3 = providers[1]
    assert s3.description == "Amazon S3"
    provider_opt, secret_opt = s3.options
    assert provider_opt == ProviderOption(
        name="provider",
        help="Choose your S3 provider.",
        type="string",
        default="",
        required=False,
        is_password=False,
        advanced=False,
        exclusive=True,
        examples=(("AWS", "Amazon Web Services"),),
    )
    assert secret_opt.required is True
    assert secret_opt.is_password is True


# -- Remote creation (non-interactive protocol) ------------------------------


def test_start_create_remote_passes_fields_as_key_value_args(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout=json.dumps({"State": "", "Option": None, "Error": ""}))

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    step = rclone_client.start_create_remote(
        "myRemote", "webdav", {"url": "https://example.com", "user": "bob"}
    )

    assert step.done is True
    assert captured["cmd"] == [
        "rclone",
        "config",
        "create",
        "myRemote",
        "webdav",
        "--non-interactive",
        "url=https://example.com",
        "user=bob",
    ]


def test_start_create_remote_with_no_fields_still_finishes(monkeypatch):
    monkeypatch.setattr(
        rclone_client.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps({"State": "", "Option": None})),
    )

    step = rclone_client.start_create_remote("myLocal", "local")

    assert step.done is True


def test_start_create_remote_returns_next_question_when_backend_needs_one(monkeypatch):
    response = {
        "State": "client_id_warning",
        "Option": {
            "Name": "config_shared_client_id",
            "Help": "Continue using the shared client_id anyway?",
            "Type": "bool",
            "Default": False,
            "Required": False,
            "IsPassword": False,
            "Advanced": False,
            "Exclusive": True,
            "Examples": [{"Value": "true", "Help": "Yes"}, {"Value": "false", "Help": "No"}],
        },
        "Error": "",
    }
    monkeypatch.setattr(
        rclone_client.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(response))
    )

    step = rclone_client.start_create_remote("testDrive", "drive")

    assert step.done is False
    assert step.state == "client_id_warning"
    assert step.option.name == "config_shared_client_id"
    assert step.option.examples == (("true", "Yes"), ("false", "No"))


def test_continue_config_step_passes_state_and_result(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout=json.dumps({"State": "", "Option": None}))

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    step = rclone_client.continue_config_step("testDrive", "client_id_warning", "false")

    assert step.done is True
    assert captured["cmd"] == [
        "rclone",
        "config",
        "update",
        "testDrive",
        "--non-interactive",
        "--continue",
        "--state=client_id_warning",
        "--result=false",
    ]


def test_config_step_error_raises(monkeypatch):
    monkeypatch.setattr(
        rclone_client.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps({"State": "", "Option": None, "Error": "bad type"})),
    )

    with pytest.raises(rclone_client.RcloneApiError, match="bad type"):
        rclone_client.start_create_remote("x", "nope")


def test_delete_remote_invokes_config_delete(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout="")

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    rclone_client.delete_remote("myRemote")

    assert captured["cmd"] == ["rclone", "config", "delete", "myRemote"]


# -- Browsing ---------------------------------------------------------------


def test_list_directory_parses_lsjson_entries(monkeypatch):
    raw = [
        {"Name": "file1.txt", "Path": "file1.txt", "Size": 6, "ModTime": "2026-01-01T00:00:00Z", "IsDir": False},
        {"Name": "subdir", "Path": "subdir", "Size": 60, "ModTime": "2026-01-01T00:00:00Z", "IsDir": True},
    ]
    monkeypatch.setattr(
        rclone_client.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(raw))
    )

    entries = rclone_client.list_directory("myRemote", "some/path")

    assert len(entries) == 2
    assert entries[0].name == "file1.txt"
    assert entries[0].is_dir is False
    assert entries[0].size == 6
    assert entries[1].is_dir is True


def test_list_directory_clamps_unknown_negative_size(monkeypatch):
    raw = [{"Name": "f", "Path": "f", "Size": -1, "ModTime": "", "IsDir": False}]
    monkeypatch.setattr(
        rclone_client.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(raw))
    )

    entries = rclone_client.list_directory("myRemote")

    assert entries[0].size == 0


def test_list_directory_empty_returns_empty_list(monkeypatch):
    monkeypatch.setattr(rclone_client.subprocess, "run", lambda *a, **k: _completed(stdout=""))
    assert rclone_client.list_directory("myRemote") == []


def test_download_invokes_copyto(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout="")

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    rclone_client.download("myRemote", "path/to/file.txt", "/tmp/dest.txt")

    assert captured["cmd"] == ["rclone", "copyto", "myRemote:path/to/file.txt", "/tmp/dest.txt"]


def test_upload_invokes_copyto_local_to_remote(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout="")

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    rclone_client.upload("myRemote", "/tmp/local.txt", "path/to/dest.txt")

    assert captured["cmd"] == ["rclone", "copyto", "/tmp/local.txt", "myRemote:path/to/dest.txt"]


def test_upload_directory_invokes_copy_local_dir_to_remote(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout="")

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    rclone_client.upload_directory("myRemote", "/tmp/local_dir", "path/to/local_dir")

    assert captured["cmd"] == ["rclone", "copy", "/tmp/local_dir", "myRemote:path/to/local_dir"]


def test_delete_file_invokes_deletefile(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout="")

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    rclone_client.delete_file("myRemote", "path/to/file.txt")

    assert captured["cmd"] == ["rclone", "deletefile", "myRemote:path/to/file.txt"]


def test_delete_directory_invokes_purge(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return _completed(stdout="")

    monkeypatch.setattr(rclone_client.subprocess, "run", fake_run)

    rclone_client.delete_directory("myRemote", "some/dir")

    assert captured["cmd"] == ["rclone", "purge", "myRemote:some/dir"]


# -- download_latest -------------------------------------------------------


def _fake_rclone_zip(exe_name="rclone", contents=b"#!/bin/sh\necho fake-rclone\n"):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"rclone-v1.99.0-linux-amd64/{exe_name}", contents)
        z.writestr("rclone-v1.99.0-linux-amd64/README.txt", "readme")
    return buf.getvalue()


class _FakeDownloadResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_download_latest_extracts_executable_and_saves_path(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_client.platform, "system", lambda: "Linux")
    monkeypatch.setattr(rclone_client.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        rclone_client.requests,
        "get",
        lambda url, timeout: _FakeDownloadResponse(_fake_rclone_zip()),
    )
    saved = []
    monkeypatch.setattr(rclone_client.settings, "save_rclone_path", lambda path: saved.append(path))

    dest_dir = tmp_path / "rclone"
    result = rclone_client.download_latest(dest_dir)

    assert result == dest_dir / "rclone"
    assert result.read_bytes() == b"#!/bin/sh\necho fake-rclone\n"
    assert result.stat().st_mode & 0o111  # executable bit set
    assert saved == [str(result)]


def test_download_latest_uses_exe_suffix_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_client.platform, "system", lambda: "Windows")
    monkeypatch.setattr(rclone_client.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(
        rclone_client.requests,
        "get",
        lambda url, timeout: _FakeDownloadResponse(_fake_rclone_zip(exe_name="rclone.exe")),
    )
    monkeypatch.setattr(rclone_client.settings, "save_rclone_path", lambda path: None)

    dest_dir = tmp_path / "rclone"
    result = rclone_client.download_latest(dest_dir)

    assert result == dest_dir / "rclone.exe"


def test_download_latest_raises_on_unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_client.platform, "system", lambda: "Plan9")
    monkeypatch.setattr(rclone_client.platform, "machine", lambda: "x86_64")

    with pytest.raises(rclone_client.UnsupportedPlatformError):
        rclone_client.download_latest(tmp_path / "rclone")


def test_download_latest_raises_when_archive_missing_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone_client.platform, "system", lambda: "Linux")
    monkeypatch.setattr(rclone_client.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        rclone_client.requests,
        "get",
        lambda url, timeout: _FakeDownloadResponse(_fake_rclone_zip(exe_name="not-rclone")),
    )

    with pytest.raises(rclone_client.RcloneApiError, match="didn't contain"):
        rclone_client.download_latest(tmp_path / "rclone")

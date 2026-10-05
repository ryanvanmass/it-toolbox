import json
import zipfile

import pytest

from it_toolbox.core import config_backup, settings, update_checker


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    monkeypatch.setattr(update_checker, "get_installed_version", lambda: "1.2.3")
    return d


def test_export_includes_config_files_only(data_dir, tmp_path):
    (data_dir / "qemu_hosts.json").write_text("[1]")
    (data_dir / "jumpcloud_api_key.age").write_bytes(b"\x00enc")
    (data_dir / "rclone").mkdir()
    (data_dir / "rclone" / "rclone.json").write_text("binary-ish")
    (data_dir / "other.bin").write_text("x")
    out = tmp_path / "b.zip"
    assert config_backup.export_config(out) == 2
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == [
            "jumpcloud_api_key.age",
            "manifest.json",
            "qemu_hosts.json",
        ]
        assert json.loads(zf.read("manifest.json"))["app_version"] == "1.2.3"


def test_restore_replaces_config_and_saves_safety_copy(data_dir, tmp_path):
    (data_dir / "qemu_hosts.json").write_text("old")
    (data_dir / "default_username.txt").write_text("alice")
    out = tmp_path / "b.zip"
    config_backup.export_config(out)

    (data_dir / "qemu_hosts.json").write_text("changed")
    (data_dir / "glinet_hosts.json").write_text("[]")
    count, safety = config_backup.restore_config(out)

    assert count == 2
    assert (data_dir / "qemu_hosts.json").read_text() == "old"
    assert not (data_dir / "glinet_hosts.json").exists()
    with zipfile.ZipFile(safety) as zf:
        assert zf.read("qemu_hosts.json") == b"changed"


def test_restore_rejects_non_backup_without_touching_config(data_dir, tmp_path):
    (data_dir / "qemu_hosts.json").write_text("keep")
    bad = tmp_path / "bad.zip"
    bad.write_text("not a zip")
    with pytest.raises(config_backup.BackupError):
        config_backup.restore_config(bad)
    assert (data_dir / "qemu_hosts.json").read_text() == "keep"


def test_restore_rejects_path_traversal(data_dir, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": 1}))
        zf.writestr("../escape.json", "x")
    (data_dir / "qemu_hosts.json").write_text("keep")
    with pytest.raises(config_backup.BackupError):
        config_backup.restore_config(evil)
    assert not (tmp_path / "escape.json").exists()
    assert (data_dir / "qemu_hosts.json").read_text() == "keep"


def test_restore_rejects_unknown_format(data_dir, tmp_path):
    f = tmp_path / "f.zip"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": 99}))
    with pytest.raises(config_backup.BackupError, match="Unsupported"):
        config_backup.read_backup(f)

"""Export/import the app's configuration as a single zip.

The config is just the flat files in settings.data_dir() (connections,
hosts, overrides, preferences, and the already-encrypted secrets). Which
files count is derived from a fixed allowlist of suffixes rather than a
hand-kept filename list, so a new setting file is picked up automatically
-- while downloaded binaries (data_dir()/rclone, /freerdp) are
subdirectories and so never included.

Secrets (`*.age`) stay encrypted to the user's SSH key exactly as they are
on disk; the backup never contains a plaintext secret, but restoring on
another machine only yields usable secrets if the same SSH key is there.
"""

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from it_toolbox.core import settings, update_checker

MANIFEST_NAME = "manifest.json"
FORMAT_VERSION = 1
_CONFIG_SUFFIXES = {".json", ".txt", ".age"}
# A hand-crafted/corrupt zip shouldn't be able to balloon in memory.
_MAX_MEMBER_BYTES = 10 * 1024 * 1024


class BackupError(Exception):
    """The file isn't a usable IT Toolbox config backup."""


def _config_files() -> list[Path]:
    return sorted(
        p
        for p in settings.data_dir().iterdir()
        if p.is_file() and p.suffix in _CONFIG_SUFFIXES
    )


def default_backup_filename() -> str:
    return f"it-toolbox-config-{datetime.now():%Y-%m-%d}.zip"


def export_config(dest: Path) -> int:
    """Write every config file to a zip at `dest`; returns the file count."""
    files = _config_files()
    manifest = {
        "format": FORMAT_VERSION,
        "app_version": update_checker.get_installed_version(),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": [p.name for p in files],
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for path in files:
            zf.write(path, path.name)
    return len(files)


def _is_config_name(name: str) -> bool:
    # Flat, plain filenames only -- rejects path separators / "..".
    return name == Path(name).name and name not in ("", ".", "..") and (
        Path(name).suffix in _CONFIG_SUFFIXES
    )


def read_backup(source: Path) -> dict[str, bytes]:
    """Validate `source` and return {filename: contents}, touching nothing
    on disk. Raises BackupError if it isn't a backup this app produced."""
    try:
        with zipfile.ZipFile(source) as zf:
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME))
            except KeyError:
                raise BackupError("Not an IT Toolbox backup (no manifest).") from None
            if manifest.get("format") != FORMAT_VERSION:
                raise BackupError(
                    f"Unsupported backup format {manifest.get('format')!r} "
                    "— it may come from a newer version of IT Toolbox."
                )
            contents: dict[str, bytes] = {}
            for info in zf.infolist():
                if info.filename == MANIFEST_NAME:
                    continue
                if not _is_config_name(info.filename):
                    raise BackupError(f"Unexpected entry in backup: {info.filename!r}")
                if info.file_size > _MAX_MEMBER_BYTES:
                    raise BackupError(f"Entry too large: {info.filename!r}")
                contents[info.filename] = zf.read(info)
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
        raise BackupError(f"Couldn't read backup: {exc}") from exc
    return contents


def restore_config(source: Path) -> tuple[int, Path]:
    """Replace the current config with the backup's.

    Files in the backup overwrite; config files *not* in the backup are
    removed, so the result matches the backup rather than a blend (a
    setting that was unset at backup time must be unset after). Before
    anything changes, the current config is exported to a safety zip (under
    data_dir()/pre-restore-backups, outside the config files), whose
    path is returned alongside the restored-file count. The backup is fully
    validated first, so a bad file never leaves a half-restored config.
    """
    contents = read_backup(source)
    data = settings.data_dir()
    safety_dir = data / "pre-restore-backups"
    safety_dir.mkdir(exist_ok=True)
    safety = safety_dir / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}.zip"
    export_config(safety)

    for path in _config_files():
        if path.name not in contents:
            path.unlink()
    for name, blob in contents.items():
        tmp = data / f".{name}.tmp"
        tmp.write_bytes(blob)
        os.replace(tmp, data / name)
    return len(contents), safety

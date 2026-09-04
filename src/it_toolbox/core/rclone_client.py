"""Configures and browses rclone remotes via the `rclone` CLI — this
project's third connection family after gcloud (Connection Manager) and
local shells (Shell Launcher). Shells out rather than embedding rclone's
Go librclone bindings, matching the qemu_client.py/gcp_auth.py convention
of wrapping a CLI rather than vendoring a client library.

Remote creation uses rclone's documented non-interactive GUI-wrapper
protocol (`rclone config create --help` describes it in full): supply
every known field as `key=value` up front, and if the chosen backend has
extra interactive logic beyond plain fields (OAuth token backends,
mainly — plain field-based backends like s3/sftp/webdav/local finish
immediately even with zero fields supplied), rclone responds with one
more question (a State + Option) that continue_config_step answers,
possibly several times in a row, until done.
"""

import json
import shutil
import subprocess
from pathlib import Path

from it_toolbox.core import settings
from it_toolbox.modules.cloud_storage.models import (
    ConfigStep,
    Provider,
    ProviderOption,
    RcloneEntry,
    RemoteConfig,
)

RCLONE_CMD = "rclone"
INSTALL_URL = "https://rclone.org/downloads/"
RCLONE_TIMEOUT_SEC = 15
# Config-create/continue calls can block on a real browser-based OAuth
# step, which plain listing/download calls never do.
RCLONE_CONFIG_TIMEOUT_SEC = 120
RCLONE_TRANSFER_TIMEOUT_SEC = 300


class RcloneApiError(Exception):
    pass


def _rclone_executable() -> str:
    """The rclone binary to invoke — an explicit override path if one's
    been configured (settings.save_rclone_path; needed on machines where
    rclone isn't on PATH, e.g. a portable rclone.exe on Windows), else
    just "rclone", relying on PATH.
    """
    return settings.load_rclone_path() or RCLONE_CMD


def is_available() -> bool:
    exe = _rclone_executable()
    if exe == RCLONE_CMD:
        return shutil.which(RCLONE_CMD) is not None
    return Path(exe).is_file()


def _run(*args: str, timeout: int = RCLONE_TIMEOUT_SEC) -> str:
    if not is_available():
        raise RcloneApiError(
            f"rclone CLI not found. Install it from {INSTALL_URL}, or set its location "
            "from the Cloud Storage sidebar entry's right-click menu, and relaunch."
        )
    try:
        result = subprocess.run(
            [_rclone_executable(), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RcloneApiError(f"rclone {' '.join(args)} timed out") from e

    if result.returncode != 0:
        raise RcloneApiError(result.stderr.strip() or f"rclone {' '.join(args)} failed")
    return result.stdout


def _parse_option(raw: dict) -> ProviderOption:
    return ProviderOption(
        name=raw.get("Name", ""),
        help=raw.get("Help", ""),
        type=raw.get("Type", "string"),
        default=str(raw.get("Default", "")),
        required=bool(raw.get("Required", False)),
        is_password=bool(raw.get("IsPassword", False)),
        advanced=bool(raw.get("Advanced", False)),
        exclusive=bool(raw.get("Exclusive", False)),
        examples=tuple(
            (str(ex.get("Value", "")), ex.get("Help", "")) for ex in (raw.get("Examples") or [])
        ),
    )


def list_remotes() -> list[RemoteConfig]:
    dump = json.loads(_run("config", "dump") or "{}")
    return sorted(
        (RemoteConfig(name=name, type=info.get("type", "")) for name, info in dump.items()),
        key=lambda r: r.name.lower(),
    )


def list_providers() -> list[Provider]:
    raw = json.loads(_run("config", "providers"))
    providers = [
        Provider(
            name=entry["Name"],
            description=entry.get("Description", ""),
            options=tuple(_parse_option(opt) for opt in entry.get("Options", [])),
        )
        for entry in raw
    ]
    return sorted(providers, key=lambda p: p.name.lower())


def _parse_config_step(raw_stdout: str) -> ConfigStep:
    data = json.loads(raw_stdout.strip() or "{}")
    error = data.get("Error") or ""
    if error:
        raise RcloneApiError(error)
    option = data.get("Option")
    if not data.get("State") and not option:
        return ConfigStep(done=True)
    return ConfigStep(done=False, state=data.get("State", ""), option=_parse_option(option or {}))


def start_create_remote(
    name: str, provider_type: str, fields: dict[str, str] | None = None
) -> ConfigStep:
    args = ["config", "create", name, provider_type, "--non-interactive"]
    for key, value in (fields or {}).items():
        args.append(f"{key}={value}")
    return _parse_config_step(_run(*args, timeout=RCLONE_CONFIG_TIMEOUT_SEC))


def continue_config_step(name: str, state: str, result: str) -> ConfigStep:
    return _parse_config_step(
        _run(
            "config",
            "update",
            name,
            "--non-interactive",
            "--continue",
            f"--state={state}",
            f"--result={result}",
            timeout=RCLONE_CONFIG_TIMEOUT_SEC,
        )
    )


def delete_remote(name: str) -> None:
    _run("config", "delete", name)


def list_directory(remote_name: str, path: str = "") -> list[RcloneEntry]:
    raw = _run("lsjson", f"{remote_name}:{path}")
    entries = json.loads(raw or "[]")
    return [
        RcloneEntry(
            name=entry["Name"],
            path=entry["Path"],
            is_dir=bool(entry.get("IsDir", False)),
            size=max(entry.get("Size", 0), 0),
            modified=entry.get("ModTime", ""),
        )
        for entry in entries
    ]


def download(remote_name: str, path: str, dest: str) -> None:
    _run("copyto", f"{remote_name}:{path}", dest, timeout=RCLONE_TRANSFER_TIMEOUT_SEC)

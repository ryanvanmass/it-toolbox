import json
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "it-toolbox"


def data_dir() -> Path:
    """Cross-platform app-data directory for local storage (DB, cached state)."""
    path = Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def selected_projects_path() -> Path:
    return data_dir() / "selected_projects.json"


def load_selected_project_ids() -> set[str] | None:
    """Which GCP project IDs the user has chosen to show in the tree.

    Returns None if never configured (the caller should prompt the user to
    pick), as distinct from an empty set (explicitly chose to show none).
    """
    path = selected_projects_path()
    if not path.is_file():
        return None
    try:
        return set(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def save_selected_project_ids(project_ids: set[str]) -> None:
    selected_projects_path().write_text(json.dumps(sorted(project_ids)))


def qemu_hosts_path() -> Path:
    return data_dir() / "qemu_hosts.json"


def load_qemu_hosts() -> list[dict[str, str]]:
    """Registered QEMU/libvirt hosts, as raw {"name": ..., "uri": ...}
    dicts — kept free of any dependency on
    modules/connection_manager.models.QemuHost (core/ doesn't import from
    modules/ anywhere else); the caller wraps these into QemuHost objects.
    """
    path = qemu_hosts_path()
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_qemu_hosts(hosts: list[dict[str, str]]) -> None:
    qemu_hosts_path().write_text(json.dumps(hosts))


def manual_connections_path() -> Path:
    return data_dir() / "manual_connections.json"


def load_manual_connections() -> list[dict]:
    """Manually-configured RDP/SSH connections, as raw dicts — kept free
    of any dependency on modules/connection_manager.models.ManualConnection
    (core/ doesn't import from modules/ anywhere else); the caller wraps
    these into ManualConnection objects.
    """
    path = manual_connections_path()
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_manual_connections(connections: list[dict]) -> None:
    manual_connections_path().write_text(json.dumps(connections))


def default_username_path() -> Path:
    return data_dir() / "default_username.txt"


def load_default_username() -> str | None:
    """The username to connect with when a connection doesn't specify its
    own — the common case being the same account name everywhere.
    """
    path = default_username_path()
    if not path.is_file():
        return None
    return path.read_text().strip() or None


def save_default_username(username: str | None) -> None:
    path = default_username_path()
    if username and username.strip():
        path.write_text(username.strip())
    else:
        path.unlink(missing_ok=True)


def default_rdp_resolution_path() -> Path:
    return data_dir() / "default_rdp_resolution.txt"


def load_default_rdp_resolution() -> tuple[int, int] | None:
    """A fixed resolution to request for embedded RDP sessions instead of
    matching the window size. None means "match window size" (the
    default): every resize sends a matching resolution request to the
    server. A fixed value is requested once at connect and never again —
    RdpWidget stretches the received image to fill the widget regardless
    (see its paintEvent), so a window resize doesn't need a server round
    trip to look right. This exists because that round trip is measurably
    slow over a GCP/IAP-tunneled connection specifically (see
    docs/embedded-rdp-status.md's "Post-resize lag is specific to the
    GCP/IAP-tunnel path" section) — picking a fixed resolution sidesteps
    the round trip entirely rather than trying to make it faster.
    """
    path = default_rdp_resolution_path()
    if not path.is_file():
        return None
    text = path.read_text().strip()
    if not text:
        return None
    try:
        width_str, height_str = text.split("x")
        return int(width_str), int(height_str)
    except ValueError:
        return None


def save_default_rdp_resolution(resolution: tuple[int, int] | None) -> None:
    path = default_rdp_resolution_path()
    if resolution is None:
        path.unlink(missing_ok=True)
    else:
        width, height = resolution
        path.write_text(f"{width}x{height}")


def rclone_path_path() -> Path:
    return data_dir() / "rclone_path.txt"


def load_rclone_path() -> str | None:
    """An explicit path to the rclone executable, for machines where it
    isn't on PATH (e.g. a portable rclone.exe on Windows). None means
    fall back to looking it up on PATH.
    """
    path = rclone_path_path()
    if not path.is_file():
        return None
    return path.read_text().strip() or None


def save_rclone_path(rclone_path: str | None) -> None:
    path = rclone_path_path()
    if rclone_path and rclone_path.strip():
        path.write_text(rclone_path.strip())
    else:
        path.unlink(missing_ok=True)

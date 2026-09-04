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

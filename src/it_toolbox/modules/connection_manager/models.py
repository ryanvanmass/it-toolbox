from dataclasses import dataclass

RDP_PORT = 3389
SSH_PORT = 22


@dataclass(frozen=True)
class GcpProject:
    project_id: str
    display_name: str


@dataclass(frozen=True)
class Instance:
    name: str
    zone: str  # short zone name, e.g. "us-central1-a"
    project_id: str
    status: str
    network_interface: str = "nic0"


@dataclass(frozen=True)
class GcsBucket:
    name: str
    project_id: str


@dataclass(frozen=True)
class GcsEntry:
    """One row in a bucket listing — either a "folder" (a common prefix,
    GCS's delimiter-based simulation of folders — buckets don't actually
    have real directories) or a real object.
    """

    name: str  # display name — the last path segment
    full_path: str  # full object key, or full prefix ending in "/" for folders
    is_folder: bool
    size: int = 0
    updated: str = ""

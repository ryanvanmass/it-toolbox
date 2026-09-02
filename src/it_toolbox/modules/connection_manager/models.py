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


@dataclass
class Connection:
    """A saved connection profile — persisted so the user doesn't have to
    re-browse GCP and re-enter a username every time.
    """

    id: int | None
    name: str
    type: str  # "rdp" or "ssh"
    project_id: str
    zone: str
    instance_name: str
    network_interface: str
    remote_port: int
    username: str | None
    folder: str | None
    last_used_at: str | None  # ISO 8601, UTC
    created_at: str | None  # ISO 8601, UTC

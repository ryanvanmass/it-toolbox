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

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


@dataclass(frozen=True)
class QemuHost:
    name: str
    uri: str  # libvirt connection URI, e.g. "qemu+ssh://user@host/system"


@dataclass(frozen=True)
class QemuVm:
    id: str  # libvirt domain id, or "-" when the VM is not running
    name: str
    state: str  # e.g. "running", "shut off", "paused"


@dataclass(frozen=True)
class GlinetHost:
    """A manually-registered GL.iNet router — no account-based discovery,
    same rationale as QemuHost. `url` matches pyglinet's GlInet() constructor
    shape directly (a full "https://<ip>/rpc" URL, not separate host/port/
    https fields). `password_encrypted` is always ciphertext (age-encrypted
    to the user's SSH key, see core/settings.py's encrypt_glinet_password) —
    never plaintext, so printing/logging a GlinetHost can't leak a router
    password. None means no password has been stored yet.
    """

    name: str
    url: str
    username: str = "root"
    verify_ssl: bool = False
    password_encrypted: bytes | None = None


@dataclass(frozen=True)
class GlinetClientInfo:
    """One device connected to a GL.iNet router (pyglinet's "client")."""

    mac: str
    name: str
    ip: str
    online: bool
    vendor: str = ""


@dataclass(frozen=True)
class GlinetWifiRadio:
    device: str  # e.g. "radio0" -- required for device-level set_config params
    iface_name: str  # e.g. "default_radio0" -- required for iface-level set_config params
    band: str  # e.g. "2.4G" / "5G"
    ssid: str
    enabled: bool


@dataclass(frozen=True)
class GlinetOverview:
    """A GL.iNet router's at-a-glance status, from a single system.get_status() call."""

    uptime: str
    lan_ip: str
    memory_used_pct: float | None
    cpu_temp: float | None
    wireless_client_count: int
    cable_client_count: int
    wifi_radios: tuple[GlinetWifiRadio, ...]
    wg_client_up: bool
    wg_server_up: bool
    ovpn_client_up: bool
    ovpn_server_up: bool


@dataclass(frozen=True)
class ManualConnection:
    """A directly user-entered RDP or SSH endpoint — no account, project,
    or host discovery involved, unlike the GCP/QEMU families. Connects
    straight to host:port, with no tunnel in front of it.
    """

    name: str
    host: str
    port: int
    kind: str  # "rdp" or "ssh"
    username: str | None = None

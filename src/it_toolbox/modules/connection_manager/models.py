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
    # "windows", "linux", or None if undetected -- best-effort guess from
    # the boot disk's license URLs, see gcp_client.list_instances. Used to
    # pick a sensible default double-click connection type (RDP/SSH)
    # without asking when it's obvious.
    os_hint: str | None = None


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
    # Per-host defaults for CreateVmDialog -- all optional (None = no
    # override, fall back to the dialog's own hardcoded default). Pool/
    # network/os-variant are matched by name against whatever's actually
    # discovered live on that host at deploy time; a stale/typo'd name
    # that no longer matches anything just silently falls back to the
    # dialog's normal default rather than erroring -- same "safe,
    # non-destructive fallback" principle as the rest of this feature.
    default_memory_mib: int | None = None
    default_vcpus: int | None = None
    default_disk_gib: int | None = None
    default_disk_pool: str | None = None
    default_network: str | None = None
    default_iso_pool: str | None = None
    default_os_variant: str | None = None


@dataclass(frozen=True)
class QemuVm:
    id: str  # libvirt domain id, or "-" when the VM is not running
    name: str
    state: str  # e.g. "running", "shut off", "paused"


@dataclass(frozen=True)
class VmDisk:
    target: str  # device name, e.g. "hda", "vdb" -- whatever the VM's own scheme already uses
    device: str  # "disk" or "cdrom" -- confirmed live via `virsh domblklist --details`
    source: str | None  # None for an empty cdrom slot ("-" in domblklist's own output)


@dataclass(frozen=True)
class VmNetworkInterface:
    mac: str
    network: str
    model: str


@dataclass(frozen=True)
class StoragePool:
    name: str
    state: str  # e.g. "active", "inactive"


@dataclass(frozen=True)
class StorageVolume:
    name: str
    path: str


@dataclass(frozen=True)
class VirtualNetwork:
    name: str
    state: str  # e.g. "active", "inactive"


@dataclass(frozen=True)
class VmCreateSpec:
    """Everything needed to define+start a new VM via virt-install --
    see qemu_provisioning.create_vm. iso_path=None means "boot the
    fresh, empty disk directly" (virt-install --import) rather than
    "install from media" (--cdrom) -- confirmed live that virt-install
    refuses to create a domain at all without one or the other
    ("An install method must be specified").
    """

    name: str
    memory_mib: int
    vcpus: int
    disk_gib: int
    pool: str
    network: str
    os_variant: str
    iso_path: str | None = None


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
    band: str  # e.g. "2G" / "5G"
    ssid: str
    enabled: bool
    guest: bool = False


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


@dataclass(frozen=True)
class GlinetVpnTunnel:
    """One configured VPN tunnel. On routers with GL.iNet's newer
    multi-tunnel "VPN Policy" feature, there can be any number of these,
    each independently named/enabled -- name is then the policy's own
    name (e.g. "Bonkcloud"), not a fixed "WireGuard Client" label."""

    name: str
    type: str  # "wireguard" or "openvpn"
    enabled: bool  # the tunnel/policy's own on/off toggle
    up: bool  # actually connected right now
    # Routing criteria (from vpn-client's separate get_tunnel() policy
    # call) -- empty strings/False for a tunnel from the classic
    # single-tunnel fallback endpoints, which expose no such policy.
    from_summary: str = ""
    to_summary: str = ""
    via_summary: str = ""
    killswitch: bool = False
    # Longer-form detail for from_summary/to_summary (e.g. the actual
    # interface names or address list a count summarizes) -- shown as a
    # tooltip rather than in the table cell itself, since a raw address
    # list is too long to sit in a column. Empty when the criteria is
    # already fully expressed by the summary (e.g. "All clients").
    from_detail: str = ""
    to_detail: str = ""


@dataclass(frozen=True)
class ManualConnection:
    """A directly user-entered RDP or SSH endpoint — no account, project,
    or host discovery involved, unlike the GCP/QEMU families. Connects
    straight to host:port, with no tunnel in front of it -- unless
    gateway_host is set, in which case host:port is reached *through* an
    SSH tunnel to the gateway instead (mirrors mRemoteNG's SSH-tunneling
    feature; see core/ssh_tunnel.py). The gateway defaults to the same
    key/agent-based auth every other SSH connection in this app uses;
    gateway_password is an explicit opt-in for a gateway that only
    accepts password auth (a real, if less secure, need -- confirmed by
    a real gateway that rejected the app's key with a plain "Permission
    denied (publickey,password)"). Stored as plain text in
    manual_connections.json -- this app has no credential-vault story
    anywhere else either, so this isn't a new weaker link, just an
    explicit one worth flagging. gateway_prompt_for_password sidesteps
    that entirely (mirrors the RDP password, which was already always
    prompted, never stored): when set, gateway_password is ignored and
    the connect flow asks for it fresh each time instead.
    """

    name: str
    host: str
    port: int
    kind: str  # "rdp" or "ssh"
    username: str | None = None
    gateway_host: str | None = None
    gateway_port: int = SSH_PORT
    gateway_username: str | None = None
    gateway_password: str | None = None
    gateway_prompt_for_password: bool = False

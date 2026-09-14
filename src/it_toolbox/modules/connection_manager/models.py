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

"""Plain data returned by core/proxmox_client.py -- no Qt, no requests.

Sizes are bytes and CPU is a 0..1 fraction of `maxcpu` cores, exactly as
the Proxmox API reports them; formatting happens in the widgets.
"""

from dataclasses import dataclass, field

QEMU = "qemu"
LXC = "lxc"


@dataclass(frozen=True)
class ProxmoxNode:
    name: str
    status: str  # "online" / "offline" / "unknown"
    cpu: float = 0.0
    maxcpu: int = 0
    mem: int = 0
    maxmem: int = 0
    disk: int = 0
    maxdisk: int = 0
    uptime: int = 0


@dataclass(frozen=True)
class ProxmoxGuest:
    vmid: int
    name: str
    node: str
    type: str  # QEMU or LXC
    status: str  # "running", "stopped", "paused", ...
    template: bool = False
    cpu: float = 0.0
    maxcpu: int = 0
    mem: int = 0
    maxmem: int = 0
    disk: int = 0
    maxdisk: int = 0
    uptime: int = 0
    tags: tuple[str, ...] = ()
    lock: str = ""

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.node, self.type, self.vmid)

    @property
    def is_container(self) -> bool:
        return self.type == LXC

    @property
    def label(self) -> str:
        suffix = " (CT)" if self.is_container else ""
        return f"{self.vmid} {self.name}{suffix}"


@dataclass(frozen=True)
class ProxmoxStorage:
    storage: str
    node: str
    plugin: str  # "dir", "lvmthin", "zfspool", "nfs", ...
    status: str
    used: int = 0
    total: int = 0
    content: tuple[str, ...] = ()
    shared: bool = False


@dataclass(frozen=True)
class ClusterResources:
    """One GET /cluster/resources, split by type."""

    nodes: tuple[ProxmoxNode, ...] = ()
    guests: tuple[ProxmoxGuest, ...] = ()
    storages: tuple[ProxmoxStorage, ...] = ()
    sdn_zones: tuple[str, ...] = ()  # names of SDN zones, as resources list them


@dataclass(frozen=True)
class NodeStatus:
    """GET /nodes/{node}/status -- the host dashboard's node card."""

    node: str
    pve_version: str
    kernel: str
    cpu_model: str
    cpus: int
    cpu: float
    loadavg: tuple[str, ...]
    mem_used: int
    mem_total: int
    swap_used: int
    swap_total: int
    rootfs_used: int
    rootfs_total: int
    uptime: int


@dataclass(frozen=True)
class GuestInterface:
    name: str
    mac: str
    addresses: tuple[str, ...]  # "10.0.0.5/24", "fe80::1/64", ...


@dataclass(frozen=True)
class GuestDetails:
    """Everything the guest summary shows, from config + status/current +
    (when available) the guest agent / container interfaces."""

    guest: ProxmoxGuest
    config: dict
    agent_running: bool | None  # None: no agent configured (or a container)
    interfaces: tuple[GuestInterface, ...] = ()
    interfaces_error: str = ""

    @property
    def ipv4_addresses(self) -> tuple[str, ...]:
        found = []
        for interface in self.interfaces:
            if interface.name == "lo":
                continue
            for address in interface.addresses:
                ip = address.split("/", 1)[0]
                if "." in ip and not ip.startswith("127."):
                    found.append(ip)
        return tuple(found)


@dataclass(frozen=True)
class ProxmoxTask:
    upid: str
    node: str
    type: str  # "qmstart", "vzdump", ...
    id: str  # the guest/storage the task acted on, "" if none
    user: str
    starttime: int
    endtime: int | None
    status: str  # "OK", an error message, or "" while running

    @property
    def running(self) -> bool:
        return self.endtime is None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


@dataclass(frozen=True)
class SdnZone:
    zone: str
    type: str  # "simple", "vlan", "qinq", "vxlan", "evpn"
    bridge: str = ""
    state: str = ""  # pending state: "", "new", "changed", "deleted"
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SdnVnet:
    vnet: str
    zone: str
    tag: int | None = None
    alias: str = ""
    state: str = ""
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SdnSubnet:
    subnet: str  # "10.10.0.0/24"
    vnet: str
    gateway: str = ""
    snat: bool = False
    dhcp_ranges: tuple[str, ...] = ()
    state: str = ""


@dataclass(frozen=True)
class SdnZoneStatus:
    zone: str
    node: str
    status: str  # "available", "pending", "error", ...


@dataclass(frozen=True)
class SdnOverview:
    zones: tuple[SdnZone, ...] = ()
    vnets: tuple[SdnVnet, ...] = ()
    subnets: tuple[SdnSubnet, ...] = ()
    zone_status: tuple[SdnZoneStatus, ...] = ()
    controllers: tuple[dict, ...] = ()
    ipams: tuple[dict, ...] = ()
    dns: tuple[dict, ...] = ()

    @property
    def has_pending(self) -> bool:
        return any(item.state for item in (*self.zones, *self.vnets, *self.subnets))

"""Proxmox VE REST API client (port 8006), authenticated with an API token.

Same shape as glinet_client.py: no Qt, the host passed as the first
argument, one stateless function per operation, one flat error class.
Each call builds its own requests session through core/pinned_tls.py, so
a pinned host is checked on every request.

Auth is a token only (`Authorization: PVEAPIToken=<user@realm!name>=<secret>`)
-- no tickets, so no expiry, CSRF header or 2FA prompt to handle.

Field names follow the PVE 9 API viewer (pve.proxmox.com/pve-docs/api-viewer)
and were checked against a real PVE 9 host; small _parse_* helpers keep any
later correction in this file.
"""

import re
from urllib.parse import quote

import requests

from it_toolbox.core import pinned_tls
from it_toolbox.core.proxmox_models import (
    LXC,
    QEMU,
    ClusterResources,
    GuestDetails,
    GuestInterface,
    NodeStatus,
    ProxmoxGuest,
    ProxmoxNode,
    ProxmoxStorage,
    ProxmoxTask,
    SdnOverview,
    SdnSubnet,
    SdnVnet,
    SdnZone,
    SdnZoneStatus,
)
from it_toolbox.core.infrastructure_hosts import InfrastructureHost

DEFAULT_PORT = 8006
TIMEOUT = 15


class ProxmoxApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# -- Transport ------------------------------------------------------------------


def _auth_header(host: InfrastructureHost, secret: str) -> dict[str, str]:
    return {"Authorization": f"PVEAPIToken={host.token_id}={secret}"}


def _request(host: InfrastructureHost, secret: str, method: str, path: str, **kwargs):
    """`data` of the response (Proxmox wraps every result as {"data": ...})."""
    url = f"{host.url.rstrip('/')}/api2/json{path}"
    try:
        session = pinned_tls.make_session(host.url, host.verify_ssl, host.fingerprint)
    except ValueError as error:
        raise ProxmoxApiError(str(error)) from error
    try:
        with session:
            response = session.request(
                method, url, headers=_auth_header(host, secret), timeout=TIMEOUT, **kwargs
            )
    except requests.exceptions.SSLError as error:
        raise _tls_error(host, error) from error
    except requests.exceptions.ConnectionError as error:
        raise ProxmoxApiError(f"Couldn't connect to {host.url}: {_short(error)}") from error
    except requests.exceptions.Timeout as error:
        raise ProxmoxApiError(f"{host.url} didn't answer within {TIMEOUT} seconds.") from error
    if response.status_code == 401:
        raise ProxmoxApiError(
            "Proxmox rejected the API token (wrong token ID or secret, or the token was removed).", 401
        )
    if response.status_code >= 400:
        raise ProxmoxApiError(_error_message(response), response.status_code)
    try:
        return response.json().get("data")
    except ValueError as error:
        raise ProxmoxApiError(f"{host.url} didn't return JSON — is this a Proxmox VE host?") from error


def _get(host: InfrastructureHost, secret: str, path: str, **params):
    return _request(host, secret, "GET", path, params=params or None)


def _tls_error(host: InfrastructureHost, error: Exception) -> ProxmoxApiError:
    if not host.verify_ssl and host.fingerprint:
        try:
            pinned_tls.check_pinned(host.url, host.fingerprint)
        except pinned_tls.CertificateMismatchError as mismatch:
            return ProxmoxApiError(str(mismatch))
        except OSError:
            pass
    return ProxmoxApiError(f"TLS error talking to {host.url}: {_short(error)}")


def _short(error: Exception) -> str:
    text = str(error)
    # urllib3 nests the useful part deep inside a long repr.
    match = re.search(r"\]\s*([^'\")]+)", text) or re.search(r"Errno -?\d+\]\s*([^'\")]+)", text)
    return (match.group(1) if match else text).strip()[:200]


def _error_message(response: requests.Response) -> str:
    """Proxmox puts the reason in the HTTP status line ("Permission check
    failed (/vms/100, VM.PowerMgmt)") and field errors in "errors"."""
    reason = response.reason or f"HTTP {response.status_code}"
    try:
        errors = response.json().get("errors")
    except ValueError:
        errors = None
    if isinstance(errors, dict) and errors:
        details = "; ".join(f"{k}: {str(v).strip()}" for k, v in errors.items())
        return f"{reason} ({details})"
    return reason


def _path(*parts) -> str:
    return "".join(f"/{quote(str(part), safe='')}" for part in parts)


# -- Parsing --------------------------------------------------------------------


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _split(value, sep: str = ",") -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return tuple(part for part in (p.strip() for p in str(value).replace(";", sep).split(sep)) if part)


def _parse_guest(item: dict) -> ProxmoxGuest:
    vmid = _int(item.get("vmid"))
    return ProxmoxGuest(
        vmid=vmid,
        name=str(item.get("name") or f"VM {vmid}"),
        node=str(item.get("node") or ""),
        type=str(item.get("type") or QEMU),
        status=str(item.get("status") or "unknown"),
        template=bool(_int(item.get("template"))),
        cpu=_float(item.get("cpu")),
        maxcpu=_int(item.get("maxcpu")),
        mem=_int(item.get("mem")),
        maxmem=_int(item.get("maxmem")),
        disk=_int(item.get("disk")),
        maxdisk=_int(item.get("maxdisk")),
        uptime=_int(item.get("uptime")),
        tags=_split(item.get("tags"), ";"),
        lock=str(item.get("lock") or ""),
    )


def parse_resources(items: list[dict]) -> ClusterResources:
    nodes, guests, storages, zones = [], [], [], []
    for item in items or []:
        kind = item.get("type")
        if kind == "node":
            nodes.append(
                ProxmoxNode(
                    name=str(item.get("node") or ""),
                    status=str(item.get("status") or "unknown"),
                    cpu=_float(item.get("cpu")),
                    maxcpu=_int(item.get("maxcpu")),
                    mem=_int(item.get("mem")),
                    maxmem=_int(item.get("maxmem")),
                    disk=_int(item.get("disk")),
                    maxdisk=_int(item.get("maxdisk")),
                    uptime=_int(item.get("uptime")),
                )
            )
        elif kind in (QEMU, LXC):
            guests.append(_parse_guest(item))
        elif kind == "storage":
            storages.append(
                ProxmoxStorage(
                    storage=str(item.get("storage") or ""),
                    node=str(item.get("node") or ""),
                    plugin=str(item.get("plugintype") or ""),
                    status=str(item.get("status") or "unknown"),
                    used=_int(item.get("disk")),
                    total=_int(item.get("maxdisk")),
                    content=_split(item.get("content")),
                    shared=bool(_int(item.get("shared"))),
                )
            )
        elif kind == "sdn":
            zone = item.get("sdn")
            if zone and zone not in zones:
                zones.append(str(zone))
    return ClusterResources(
        nodes=tuple(sorted(nodes, key=lambda n: n.name)),
        guests=tuple(sorted(guests, key=lambda g: g.vmid)),
        storages=tuple(sorted(storages, key=lambda s: (s.node, s.storage))),
        sdn_zones=tuple(sorted(zones)),
    )


def parse_node_status(node: str, data: dict) -> NodeStatus:
    cpuinfo = data.get("cpuinfo") or {}
    memory = data.get("memory") or {}
    swap = data.get("swap") or {}
    rootfs = data.get("rootfs") or {}
    kernel = data.get("current-kernel") or {}
    return NodeStatus(
        node=node,
        pve_version=str(data.get("pveversion") or ""),
        kernel=str(kernel.get("release") or data.get("kversion") or ""),
        cpu_model=str(cpuinfo.get("model") or ""),
        cpus=_int(cpuinfo.get("cpus")),
        cpu=_float(data.get("cpu")),
        loadavg=tuple(str(v) for v in data.get("loadavg") or ()),
        mem_used=_int(memory.get("used")),
        mem_total=_int(memory.get("total")),
        swap_used=_int(swap.get("used")),
        swap_total=_int(swap.get("total")),
        rootfs_used=_int(rootfs.get("used")),
        rootfs_total=_int(rootfs.get("total")),
        uptime=_int(data.get("uptime")),
    )


def parse_agent_interfaces(data) -> tuple[GuestInterface, ...]:
    """QEMU guest agent network-get-interfaces: {"result": [{"name",
    "hardware-address", "ip-addresses": [{"ip-address", "prefix"}]}]}."""
    result = data.get("result") if isinstance(data, dict) else data
    interfaces = []
    for entry in result or []:
        addresses = tuple(
            f"{a.get('ip-address')}/{a.get('prefix')}" if a.get("prefix") is not None else str(a.get("ip-address"))
            for a in entry.get("ip-addresses") or []
            if a.get("ip-address")
        )
        interfaces.append(
            GuestInterface(
                name=str(entry.get("name") or ""),
                mac=str(entry.get("hardware-address") or ""),
                addresses=addresses,
            )
        )
    return tuple(interfaces)


def parse_lxc_interfaces(data) -> tuple[GuestInterface, ...]:
    """GET .../lxc/{vmid}/interfaces: [{"name", "hwaddr", "inet", "inet6"}]
    (PVE 8.1+ also lists "ip-addresses" in the agent's shape)."""
    interfaces = []
    for entry in data or []:
        if entry.get("ip-addresses"):
            addresses = parse_agent_interfaces([entry])[0].addresses
        else:
            addresses = tuple(a for a in (entry.get("inet"), entry.get("inet6")) if a)
        interfaces.append(
            GuestInterface(
                name=str(entry.get("name") or ""),
                mac=str(entry.get("hwaddr") or entry.get("hardware-address") or ""),
                addresses=addresses,
            )
        )
    return tuple(interfaces)


def parse_task(item: dict) -> ProxmoxTask:
    endtime = item.get("endtime")
    return ProxmoxTask(
        upid=str(item.get("upid") or ""),
        node=str(item.get("node") or ""),
        type=str(item.get("type") or ""),
        id=str(item.get("id") or ""),
        user=str(item.get("user") or ""),
        starttime=_int(item.get("starttime")),
        endtime=_int(endtime) if endtime not in (None, "") else None,
        status=str(item.get("status") or ""),
    )


def _state(item: dict) -> str:
    """With pending=1, SDN objects carry "state" ("new"/"changed"/"deleted")
    and their staged values under "pending"."""
    return str(item.get("state") or "")


def _merged(item: dict) -> dict:
    """An SDN object's values as they will be once applied."""
    merged = {k: v for k, v in item.items() if k not in ("pending", "state", "digest")}
    merged.update(item.get("pending") or {})
    return merged


def parse_sdn(
    zones: list[dict], vnets: list[dict], subnets: list[dict], zone_status: list[SdnZoneStatus],
    controllers: list[dict], ipams: list[dict], dns: list[dict],
) -> SdnOverview:
    parsed_zones = []
    for raw in zones or []:
        item = _merged(raw)
        parsed_zones.append(
            SdnZone(
                zone=str(item.get("zone") or ""),
                type=str(item.get("type") or ""),
                bridge=str(item.get("bridge") or ""),
                state=_state(raw),
                options={k: v for k, v in item.items() if k not in ("zone", "type", "bridge")},
            )
        )
    parsed_vnets = []
    for raw in vnets or []:
        item = _merged(raw)
        tag = item.get("tag")
        parsed_vnets.append(
            SdnVnet(
                vnet=str(item.get("vnet") or ""),
                zone=str(item.get("zone") or ""),
                tag=_int(tag) if tag not in (None, "") else None,
                alias=str(item.get("alias") or ""),
                state=_state(raw),
                options={k: v for k, v in item.items() if k not in ("vnet", "zone", "tag", "alias", "type")},
            )
        )
    parsed_subnets = []
    for raw in subnets or []:
        item = _merged(raw)
        ranges = item.get("dhcp-range") or []
        parsed_subnets.append(
            SdnSubnet(
                subnet=str(item.get("cidr") or item.get("subnet") or ""),
                vnet=str(item.get("vnet") or ""),
                gateway=str(item.get("gateway") or ""),
                snat=bool(_int(item.get("snat"))),
                dhcp_ranges=tuple(_format_dhcp_range(r) for r in (ranges if isinstance(ranges, list) else [ranges])),
                state=_state(raw),
            )
        )
    return SdnOverview(
        zones=tuple(sorted(parsed_zones, key=lambda z: z.zone)),
        vnets=tuple(sorted(parsed_vnets, key=lambda v: (v.zone, v.vnet))),
        subnets=tuple(sorted(parsed_subnets, key=lambda s: (s.vnet, s.subnet))),
        zone_status=tuple(zone_status),
        controllers=tuple(controllers or ()),
        ipams=tuple(ipams or ()),
        dns=tuple(dns or ()),
    )


def _format_dhcp_range(value) -> str:
    if isinstance(value, dict):
        return f"{value.get('start-address', '')}–{value.get('end-address', '')}"
    text = str(value)
    parts = dict(p.split("=", 1) for p in text.split(",") if "=" in p)
    if parts:
        return f"{parts.get('start-address', '')}–{parts.get('end-address', '')}"
    return text


# -- Operations -----------------------------------------------------------------


def get_version(host: InfrastructureHost, secret: str) -> dict:
    return _get(host, secret, "/version") or {}


def test_connection(host: InfrastructureHost, secret: str) -> str:
    """One-line summary for the Add host dialog, including whether the
    token can do more than read."""
    version = get_version(host, secret)
    nodes = [n.get("node") for n in _get(host, secret, "/nodes") or [] if n.get("node")]
    summary = f"Proxmox VE {version.get('version', '?')}"
    if nodes:
        summary += f", node{'s' if len(nodes) > 1 else ''} {', '.join(sorted(nodes))}"
    summary += f" — {describe_permissions(get_permissions(host, secret))}"
    major = _int(str(version.get("version", "")).split(".", 1)[0])
    if major and major < 9:
        summary += f". This tool targets PVE 9; {version.get('version')} may not work fully"
    return summary


def get_permissions(host: InfrastructureHost, secret: str) -> dict[str, dict]:
    """{path: {privilege: 1}} for the token itself (privilege separation
    included), from GET /access/permissions."""
    return _get(host, secret, "/access/permissions") or {}


def has_privilege(permissions: dict[str, dict], privilege: str, path: str = "/") -> bool:
    """Whether `privilege` is granted on `path` or any parent of it
    (Proxmox propagates ACLs down, and /access/permissions lists them
    per path they were granted on)."""
    candidate = path.rstrip("/") or "/"
    while True:
        if (permissions.get(candidate) or {}).get(privilege):
            return True
        if candidate == "/":
            return False
        candidate = candidate.rsplit("/", 1)[0] or "/"


def describe_permissions(permissions: dict[str, dict]) -> str:
    can_power = has_privilege(permissions, "VM.PowerMgmt", "/vms")
    can_audit = has_privilege(permissions, "VM.Audit", "/vms") or has_privilege(permissions, "Sys.Audit")
    can_sdn = has_privilege(permissions, "SDN.Allocate", "/sdn")
    if not can_audit:
        return "this token can't see any VMs (give it PVEAuditor or PVEVMAdmin on /)"
    parts = ["can manage VMs" if can_power else "read-only token"]
    if can_sdn:
        parts.append("can edit SDN")
    return ", ".join(parts)


def list_resources(host: InfrastructureHost, secret: str) -> ClusterResources:
    return parse_resources(_get(host, secret, "/cluster/resources") or [])


def get_node_status(host: InfrastructureHost, secret: str, node: str) -> NodeStatus:
    return parse_node_status(node, _get(host, secret, _path("nodes", node, "status")) or {})


def get_guest_details(host: InfrastructureHost, secret: str, guest: ProxmoxGuest) -> GuestDetails:
    base = _path("nodes", guest.node, guest.type, guest.vmid)
    config = _get(host, secret, f"{base}/config") or {}
    current = _get(host, secret, f"{base}/status/current") or {}
    fresh = _parse_guest({**current, "node": guest.node, "type": guest.type, "vmid": guest.vmid,
                          "template": current.get("template", config.get("template"))})
    agent_running = None
    interfaces: tuple[GuestInterface, ...] = ()
    interfaces_error = ""
    if guest.type == QEMU:
        agent_configured = str(config.get("agent", "0")).split(",", 1)[0] in ("1", "enabled=1")
        if agent_configured:
            agent_running = bool(current.get("agent")) and fresh.status == "running"
            if agent_running:
                try:
                    interfaces = parse_agent_interfaces(
                        _get(host, secret, f"{base}/agent/network-get-interfaces")
                    )
                except ProxmoxApiError as error:
                    agent_running = False
                    interfaces_error = str(error)
    elif fresh.status == "running":
        try:
            interfaces = parse_lxc_interfaces(_get(host, secret, f"{base}/interfaces"))
        except ProxmoxApiError as error:
            interfaces_error = str(error)
    return GuestDetails(
        guest=fresh,
        config=config,
        agent_running=agent_running,
        interfaces=interfaces,
        interfaces_error=interfaces_error,
    )


def list_tasks(host: InfrastructureHost, secret: str, limit: int = 50) -> list[ProxmoxTask]:
    tasks = [parse_task(t) for t in _get(host, secret, "/cluster/tasks") or []]
    tasks.sort(key=lambda t: t.starttime, reverse=True)
    return tasks[:limit]


def get_task_log(host: InfrastructureHost, secret: str, node: str, upid: str, limit: int = 1000) -> list[str]:
    lines = _get(host, secret, f"{_path('nodes', node, 'tasks', upid)}/log", limit=limit) or []
    return [str(line.get("t", "")) for line in lines]


def get_sdn(host: InfrastructureHost, secret: str, nodes: list[str]) -> SdnOverview:
    """Zones, VNets and subnets including staged (not yet applied) changes,
    plus each node's zone status and the read-only plugin lists."""
    zones = _get(host, secret, "/cluster/sdn/zones", pending=1) or []
    vnets = _get(host, secret, "/cluster/sdn/vnets", pending=1) or []
    subnets = []
    for vnet in vnets:
        name = vnet.get("vnet")
        if name and _state(vnet) != "new":
            subnets.extend(_get(host, secret, f"{_path('cluster', 'sdn', 'vnets', name)}/subnets", pending=1) or [])
    statuses = []
    for node in nodes:
        try:
            for item in _get(host, secret, f"{_path('nodes', node, 'sdn', 'zones')}") or []:
                statuses.append(SdnZoneStatus(zone=str(item.get("zone") or ""), node=node,
                                              status=str(item.get("status") or "")))
        except ProxmoxApiError:
            pass  # an offline node; its zones just show no status
    return parse_sdn(
        zones, vnets, subnets, statuses,
        _optional_list(host, secret, "/cluster/sdn/controllers"),
        _optional_list(host, secret, "/cluster/sdn/ipams"),
        _optional_list(host, secret, "/cluster/sdn/dns"),
    )


def _optional_list(host: InfrastructureHost, secret: str, path: str) -> list[dict]:
    try:
        return _get(host, secret, path) or []
    except ProxmoxApiError as error:
        if error.status in (403, 501):
            return []
        raise


def guests_by_bridge(host: InfrastructureHost, secret: str, guests: list[ProxmoxGuest]) -> dict[str, list[str]]:
    """Bridge or VNet name -> labels of the guests with a NIC on it, from
    each guest's netN "bridge=" option. One config read per guest; a guest
    that can't be read is skipped."""
    users: dict[str, list[str]] = {}
    for guest in guests:
        try:
            config = _get(host, secret, f"{_path('nodes', guest.node, guest.type, guest.vmid)}/config") or {}
        except ProxmoxApiError:
            continue
        for bridge in nic_bridges(config):
            users.setdefault(bridge, []).append(guest.label)
    return users


def nic_bridges(config: dict) -> list[str]:
    bridges = []
    for key, value in sorted(config.items()):
        if key.startswith("net") and key[3:].isdigit():
            options = dict(p.split("=", 1) for p in str(value).split(",") if "=" in p)
            if options.get("bridge"):
                bridges.append(options["bridge"])
    return bridges


def guest_web_url(host: InfrastructureHost, guest: ProxmoxGuest) -> str:
    """The guest's page in the Proxmox web UI."""
    return f"{host.url.rstrip('/')}/#v1:0:={guest.type}%2F{guest.vmid}:4:::::::"


def novnc_url(host: InfrastructureHost, guest: ProxmoxGuest) -> str:
    console = "lxc" if guest.is_container else "kvm"
    return (
        f"{host.url.rstrip('/')}/?console={console}&novnc=1&vmid={guest.vmid}"
        f"&vmname={quote(guest.name)}&node={quote(guest.node)}&resize=off&cmd="
    )

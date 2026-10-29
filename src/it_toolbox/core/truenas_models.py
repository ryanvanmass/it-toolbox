"""What the TrueNAS dashboard shows, parsed from the middleware's JSON.

Every parser is forgiving: a field missing on one release (or renamed
between 25.04 and 25.10) leaves a blank in the table instead of breaking
the whole tab. Secrets never make it into these models -- the credential
models carry names and types only, never keys or passwords.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: Alert levels from most to least severe, as TrueNAS names them.
ALERT_LEVELS = ("EMERGENCY", "ALERT", "CRITICAL", "ERROR", "WARNING", "NOTICE", "INFO")
#: Levels that turn a host's health dot red / amber.
RED_LEVELS = {"EMERGENCY", "ALERT", "CRITICAL", "ERROR"}
AMBER_LEVELS = {"WARNING"}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> datetime | None:
    """The middleware sends times as {"$date": <ms since epoch>}, a bare
    number of seconds, or (rarely) an ISO string."""
    if isinstance(value, dict) and "$date" in value:
        value = _int(value["$date"])
        return datetime.fromtimestamp(value / 1000, timezone.utc) if value is not None else None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def zfs_value(prop: Any) -> Any:
    """A ZFS property arrives as {"value": "1.2G", "rawvalue": "...",
    "parsed": 1288490188}; the parsed form is what we want."""
    if isinstance(prop, dict):
        return prop.get("parsed", prop.get("value"))
    return prop


def format_schedule(schedule: Any) -> str:
    """{"minute": "0", "hour": "*/6", ...} -> "0 */6 * * *" (cron order)."""
    s = _dict(schedule)
    if not s:
        return ""
    return " ".join(str(s.get(k, "*")) for k in ("minute", "hour", "dom", "month", "dow"))


@dataclass(frozen=True)
class SystemOverview:
    hostname: str
    version: str
    model: str
    uptime_seconds: float | None
    physical_memory: int | None
    cores: int | None
    loadavg: tuple[float, ...]
    ecc_memory: bool | None

    @classmethod
    def from_api(cls, info: dict) -> "SystemOverview":
        uptime = info.get("uptime_seconds")
        return cls(
            hostname=str(info.get("hostname") or ""),
            version=str(info.get("version") or ""),
            model=str(info.get("system_product") or info.get("model") or ""),
            uptime_seconds=float(uptime) if isinstance(uptime, (int, float)) else None,
            physical_memory=_int(info.get("physmem")),
            cores=_int(info.get("cores")),
            loadavg=tuple(float(x) for x in _list(info.get("loadavg")) if isinstance(x, (int, float))),
            ecc_memory=info.get("ecc_memory") if isinstance(info.get("ecc_memory"), bool) else None,
        )


@dataclass(frozen=True)
class Alert:
    uuid: str
    level: str
    klass: str
    text: str
    when: datetime | None
    dismissed: bool

    @classmethod
    def from_api(cls, data: dict) -> "Alert":
        return cls(
            uuid=str(data.get("uuid") or data.get("id") or ""),
            level=str(data.get("level") or "INFO").upper(),
            klass=str(data.get("klass") or ""),
            text=str(data.get("formatted") or data.get("text") or "").strip(),
            when=parse_time(data.get("datetime")),
            dismissed=bool(data.get("dismissed")),
        )


@dataclass(frozen=True)
class PoolDevice:
    """One vdev or disk in a pool's topology."""

    name: str
    kind: str  # "MIRROR", "RAIDZ1", "DISK", ...
    status: str
    disk: str = ""
    read_errors: int = 0
    write_errors: int = 0
    checksum_errors: int = 0
    children: tuple["PoolDevice", ...] = ()

    @classmethod
    def from_api(cls, data: dict) -> "PoolDevice":
        stats = _dict(data.get("stats"))
        return cls(
            name=str(data.get("name") or data.get("guid") or ""),
            kind=str(data.get("type") or ""),
            status=str(data.get("status") or ""),
            disk=str(data.get("disk") or ""),
            read_errors=_int(stats.get("read_errors")) or 0,
            write_errors=_int(stats.get("write_errors")) or 0,
            checksum_errors=_int(stats.get("checksum_errors")) or 0,
            children=tuple(cls.from_api(c) for c in _list(data.get("children")) if isinstance(c, dict)),
        )


@dataclass(frozen=True)
class Pool:
    id: int
    name: str
    status: str
    healthy: bool
    size: int | None
    allocated: int | None
    free: int | None
    scan_function: str
    scan_state: str
    scan_end: datetime | None
    scan_errors: int | None
    #: role ("data", "cache", "log", "spare", "special", "dedup") -> vdevs
    topology: dict[str, tuple[PoolDevice, ...]] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict) -> "Pool":
        scan = _dict(data.get("scan"))
        topology = {
            role: tuple(PoolDevice.from_api(v) for v in _list(vdevs) if isinstance(v, dict))
            for role, vdevs in _dict(data.get("topology")).items()
            if _list(vdevs)
        }
        return cls(
            id=_int(data.get("id")) or 0,
            name=str(data.get("name") or ""),
            status=str(data.get("status") or ""),
            healthy=bool(data.get("healthy", data.get("status") == "ONLINE")),
            size=_int(data.get("size")),
            allocated=_int(data.get("allocated")),
            free=_int(data.get("free")),
            scan_function=str(scan.get("function") or ""),
            scan_state=str(scan.get("state") or ""),
            scan_end=parse_time(scan.get("end_time")),
            scan_errors=_int(scan.get("errors")),
            topology=topology,
        )

    @property
    def used_percent(self) -> int | None:
        if not self.size or self.allocated is None:
            return None
        return round(100 * self.allocated / self.size)


@dataclass(frozen=True)
class Disk:
    identifier: str
    name: str
    serial: str
    model: str
    size: int | None
    kind: str  # HDD / SSD
    pool: str
    temperature: int | None = None

    @classmethod
    def from_api(cls, data: dict, temperatures: dict | None = None) -> "Disk":
        name = str(data.get("name") or data.get("devname") or "")
        temp = _dict(temperatures).get(name)
        if isinstance(temp, dict):  # include_thresholds form
            temp = temp.get("temp")
        return cls(
            identifier=str(data.get("identifier") or name),
            name=name,
            serial=str(data.get("serial") or ""),
            model=str(data.get("model") or ""),
            size=_int(data.get("size")),
            kind=str(data.get("type") or ""),
            pool=str(data.get("pool") or ""),
            temperature=_int(temp),
        )


@dataclass(frozen=True)
class Dataset:
    id: str  # "tank/media"
    pool: str
    kind: str  # FILESYSTEM / VOLUME
    used: int | None
    available: int | None
    quota: int | None
    compression: str
    encrypted: bool
    locked: bool
    mountpoint: str

    @classmethod
    def from_api(cls, data: dict) -> "Dataset":
        quota = zfs_value(data.get("quota"))
        return cls(
            id=str(data.get("id") or data.get("name") or ""),
            pool=str(data.get("pool") or ""),
            kind=str(data.get("type") or ""),
            used=_int(zfs_value(data.get("used"))),
            available=_int(zfs_value(data.get("available"))),
            quota=_int(quota) or None,  # 0 means "no quota"
            compression=str(zfs_value(data.get("compression")) or ""),
            encrypted=bool(data.get("encrypted")),
            locked=bool(data.get("locked")),
            mountpoint=str(data.get("mountpoint") or ""),
        )

    @property
    def parent(self) -> str | None:
        return self.id.rsplit("/", 1)[0] if "/" in self.id else None

    @property
    def short_name(self) -> str:
        return self.id.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Snapshot:
    id: str  # "tank/media@auto-2026-10-29_00-00"
    dataset: str
    name: str
    created: datetime | None
    used: int | None
    referenced: int | None

    @classmethod
    def from_api(cls, data: dict) -> "Snapshot":
        props = _dict(data.get("properties"))
        snap_id = str(data.get("id") or data.get("name") or "")
        dataset, _, name = snap_id.partition("@")
        return cls(
            id=snap_id,
            dataset=str(data.get("dataset") or dataset),
            name=str(data.get("snapshot_name") or name),
            created=parse_time(zfs_value(props.get("creation"))) or parse_time(data.get("createtxg_time")),
            used=_int(zfs_value(props.get("used"))),
            referenced=_int(zfs_value(props.get("referenced"))),
        )


#: Data protection task kinds: (kind, query method, label).
TASK_KINDS = (
    ("snapshot", "pool.snapshottask.query", "Periodic snapshot"),
    ("replication", "replication.query", "Replication"),
    ("cloudsync", "cloudsync.query", "Cloud sync"),
    ("cloud_backup", "cloud_backup.query", "TrueCloud backup"),
    ("rsync", "rsynctask.query", "Rsync"),
    ("scrub", "pool.scrub.query", "Scrub"),
    ("smart", "smart.test.query", "SMART test"),
)
TASK_LABELS = {kind: label for kind, _method, label in TASK_KINDS}


@dataclass(frozen=True)
class ProtectionTask:
    kind: str  # one of TASK_KINDS' kinds
    id: int
    name: str
    target: str  # what it protects / where it goes, one line
    schedule: str
    enabled: bool
    last_state: str  # SUCCESS / FAILED / RUNNING / "" (never run)
    last_run: datetime | None
    last_error: str
    job_id: int | None
    credential_id: int | None = None

    @property
    def kind_label(self) -> str:
        return TASK_LABELS.get(self.kind, self.kind)

    @property
    def can_run_now(self) -> bool:
        return self.kind not in {"smart"}

    @classmethod
    def from_api(cls, kind: str, data: dict) -> "ProtectionTask":
        state = _dict(data.get("state"))
        job = _dict(data.get("job"))
        last_state = str(job.get("state") or state.get("state") or "")
        last_run = parse_time(job.get("time_finished") or job.get("time_started") or state.get("datetime"))
        last_error = str(job.get("error") or state.get("error") or "").strip()
        credential_id = None
        if kind == "snapshot":
            value, unit = data.get("lifetime_value", "?"), str(data.get("lifetime_unit", "")).lower()
            lifetime = f"keep {value} {unit}{'' if value == 1 else 's'}"
            name = str(data.get("dataset") or "")
            target = f"{name}{' (recursive)' if data.get('recursive') else ''}, {lifetime}"
        elif kind == "replication":
            name = str(data.get("name") or "")
            sources = ", ".join(str(s) for s in _list(data.get("source_datasets")))
            direction = str(data.get("direction") or "PUSH")
            arrow = "→" if direction == "PUSH" else "←"
            transport = str(data.get("transport") or "")
            target = f"{sources} {arrow} {data.get('target_dataset', '')} ({transport})"
            credential_id = _int(_dict(data.get("ssh_credentials")).get("id") or data.get("ssh_credentials"))
        elif kind in {"cloudsync", "cloud_backup"}:
            name = str(data.get("description") or data.get("path") or "")
            credentials = data.get("credentials")
            credential_name = _dict(credentials).get("name", "")
            credential_id = _int(_dict(credentials).get("id") if isinstance(credentials, dict) else credentials)
            direction = str(data.get("direction") or ("PUSH" if kind == "cloud_backup" else ""))
            arrow = "→" if direction == "PUSH" else "←"
            target = f"{data.get('path', '')} {arrow} {credential_name or 'cloud'}"
        elif kind == "rsync":
            name = str(data.get("desc") or data.get("path") or "")
            remote = data.get("remotehost") or _dict(data.get("ssh_credentials")).get("name") or ""
            arrow = "→" if str(data.get("direction") or "PUSH") == "PUSH" else "←"
            target = f"{data.get('path', '')} {arrow} {remote}:{data.get('remotepath') or data.get('remotemodule') or ''}"
            credential_id = _int(_dict(data.get("ssh_credentials")).get("id") or data.get("ssh_credentials"))
        elif kind == "scrub":
            name = str(data.get("pool_name") or data.get("pool") or "")
            target = f"pool {name}, every {data.get('threshold', '?')} days at most"
        else:  # smart
            name = f"{data.get('type', '')} test".strip()
            disks = "all disks" if data.get("all_disks") else ", ".join(str(d) for d in _list(data.get("disks")))
            target = disks or "no disks"
        return cls(
            kind=kind,
            id=_int(data.get("id")) or 0,
            name=name,
            target=target,
            schedule=format_schedule(data.get("schedule")),
            enabled=bool(data.get("enabled", True)),
            last_state=last_state,
            last_run=last_run,
            last_error=last_error,
            job_id=_int(job.get("id")),
            credential_id=credential_id,
        )


@dataclass(frozen=True)
class Credential:
    """A remote credential, by name and type only -- the keys, passwords
    and access secrets stay on the NAS."""

    source: str  # "keychain" (SSH) or "cloud"
    id: int
    name: str
    kind: str  # "SSH connection", "SSH keypair", "S3", "B2", ...
    detail: str  # the host or bucket endpoint, never a secret

    @classmethod
    def from_keychain(cls, data: dict) -> "Credential":
        kind = str(data.get("type") or "")
        attributes = _dict(data.get("attributes"))
        if kind == "SSH_CREDENTIALS":
            port = attributes.get("port")
            detail = f"{attributes.get('username', '')}@{attributes.get('host', '')}" + (
                f":{port}" if port and port != 22 else ""
            )
            label = "SSH connection"
        elif kind == "SSH_KEY_PAIR":
            detail = "key pair"
            label = "SSH keypair"
        else:
            detail, label = "", kind
        return cls("keychain", _int(data.get("id")) or 0, str(data.get("name") or ""), label, detail)

    @classmethod
    def from_cloud(cls, data: dict) -> "Credential":
        provider = data.get("provider")
        # 25.04+: {"type": "S3", ...secrets}; older: "S3" + "attributes".
        kind = str(_dict(provider).get("type") if isinstance(provider, dict) else provider or "")
        source = _dict(provider) if isinstance(provider, dict) else _dict(data.get("attributes"))
        detail = str(source.get("endpoint") or source.get("region") or "")
        return cls("cloud", _int(data.get("id")) or 0, str(data.get("name") or ""), kind, detail)


@dataclass(frozen=True)
class Share:
    protocol: str  # "SMB" / "NFS"
    id: int
    name: str
    path: str
    enabled: bool
    comment: str

    @classmethod
    def from_smb(cls, data: dict) -> "Share":
        return cls(
            "SMB",
            _int(data.get("id")) or 0,
            str(data.get("name") or ""),
            str(data.get("path") or ""),
            bool(data.get("enabled", True)),
            str(data.get("comment") or ""),
        )

    @classmethod
    def from_nfs(cls, data: dict) -> "Share":
        path = str(data.get("path") or "")
        return cls(
            "NFS",
            _int(data.get("id")) or 0,
            path.rsplit("/", 1)[-1] or path,
            path,
            bool(data.get("enabled", True)),
            str(data.get("comment") or ""),
        )


#: service.query names for the shares' services.
SHARE_SERVICES = {"SMB": "cifs", "NFS": "nfs"}


@dataclass(frozen=True)
class Service:
    name: str  # "cifs", "nfs", ...
    running: bool
    enabled_at_boot: bool

    @classmethod
    def from_api(cls, data: dict) -> "Service":
        return cls(
            str(data.get("service") or ""),
            str(data.get("state") or "") == "RUNNING",
            bool(data.get("enable")),
        )


@dataclass(frozen=True)
class AppContainer:
    id: str
    service: str
    image: str
    state: str


@dataclass(frozen=True)
class App:
    name: str
    title: str
    state: str  # RUNNING / STOPPED / DEPLOYING / CRASHED
    version: str
    upgrade_available: bool
    ports: tuple[str, ...]
    portals: dict[str, str]
    containers: tuple[AppContainer, ...]

    @classmethod
    def from_api(cls, data: dict) -> "App":
        metadata = _dict(data.get("metadata"))
        workloads = _dict(data.get("active_workloads"))
        ports = []
        for port in _list(workloads.get("used_ports")):
            for host_port in _list(_dict(port).get("host_ports")):
                number = _dict(host_port).get("host_port")
                if number is not None:
                    ports.append(f"{number}/{_dict(port).get('protocol', 'tcp')}")
        containers = tuple(
            AppContainer(
                str(_dict(c).get("id") or ""),
                str(_dict(c).get("service_name") or ""),
                str(_dict(c).get("image") or ""),
                str(_dict(c).get("state") or ""),
            )
            for c in _list(workloads.get("container_details"))
        )
        return cls(
            name=str(data.get("name") or data.get("id") or ""),
            title=str(metadata.get("title") or data.get("name") or ""),
            state=str(data.get("state") or ""),
            version=str(data.get("human_version") or data.get("version") or ""),
            upgrade_available=bool(data.get("upgrade_available")),
            ports=tuple(dict.fromkeys(ports)),
            portals={str(k): str(v) for k, v in _dict(data.get("portals")).items() if v},
            containers=containers,
        )


@dataclass(frozen=True)
class Vm:
    id: int
    name: str
    state: str  # RUNNING / STOPPED / SUSPENDED
    vcpus: int | None
    memory_mib: int | None
    autostart: bool
    description: str

    @classmethod
    def from_api(cls, data: dict) -> "Vm":
        vcpus = _int(data.get("vcpus"))
        cores, threads = _int(data.get("cores")) or 1, _int(data.get("threads")) or 1
        return cls(
            id=_int(data.get("id")) or 0,
            name=str(data.get("name") or ""),
            state=str(_dict(data.get("status")).get("state") or ""),
            vcpus=vcpus * cores * threads if vcpus is not None else None,
            memory_mib=_int(data.get("memory")),
            autostart=bool(data.get("autostart")),
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True)
class RealtimeStats:
    """One reporting.realtime event, reduced to what the Overview shows."""

    cpu_percent: float | None
    memory_used: int | None
    memory_total: int | None
    arc_size: int | None
    net_rx_bytes_per_sec: float | None
    net_tx_bytes_per_sec: float | None
    disk_read_bytes_per_sec: float | None
    disk_write_bytes_per_sec: float | None

    @classmethod
    def from_event(cls, fields: dict) -> "RealtimeStats":
        cpu = _dict(fields.get("cpu"))
        # 25.04 sends the all-CPU figure under "cpu"; some releases call it "average".
        usage = _dict(cpu.get("cpu")).get("usage")
        if usage is None:
            usage = _dict(cpu.get("average")).get("usage")
        memory = _dict(fields.get("memory"))
        total = _int(memory.get("physical_memory_total"))
        available = _int(memory.get("physical_memory_available"))
        zfs = _dict(fields.get("zfs"))
        rx = tx = None
        for stats in _dict(fields.get("interfaces")).values():
            stats = _dict(stats)
            if "received_bytes_rate" in stats:
                rx = (rx or 0) + float(stats.get("received_bytes_rate") or 0)
                tx = (tx or 0) + float(stats.get("sent_bytes_rate") or 0)
        disks = _dict(fields.get("disks"))
        return cls(
            cpu_percent=float(usage) if isinstance(usage, (int, float)) else None,
            memory_used=total - available if total is not None and available is not None else None,
            memory_total=total,
            arc_size=_int(zfs.get("arc_size")),
            net_rx_bytes_per_sec=rx,
            net_tx_bytes_per_sec=tx,
            disk_read_bytes_per_sec=float(disks["read_bytes"]) if isinstance(disks.get("read_bytes"), (int, float)) else None,
            disk_write_bytes_per_sec=float(disks["write_bytes"]) if isinstance(disks.get("write_bytes"), (int, float)) else None,
        )


def health(alerts: list[Alert], pools: list[Pool]) -> str:
    """"red", "amber" or "green" for a host's tree dot."""
    active = [a for a in alerts if not a.dismissed]
    if any(not p.healthy for p in pools) or any(a.level in RED_LEVELS for a in active):
        return "red"
    if any(a.level in AMBER_LEVELS for a in active):
        return "amber"
    return "green"


def format_bytes(num: int | float | None) -> str:
    if num is None:
        return ""
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(value) < 1024 or unit == "PiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_time(when: datetime | None) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M") if when else ""

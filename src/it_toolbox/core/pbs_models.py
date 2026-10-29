"""What pbs_client returns -- plain frozen dataclasses, no Qt.

Field names follow PBS's own API schema (pbs.proxmox.com/docs/api-viewer),
with hyphens turned into underscores. Times are Unix epoch seconds, sizes
bytes, as PBS sends them; formatting is the dashboard's job.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeStatus:
    """GET /nodes/localhost/status, plus /version and /subscription."""

    version: str = ""
    cpu: float = 0.0  # 0..1
    cpus: int = 0
    memory_used: int = 0
    memory_total: int = 0
    root_used: int = 0
    root_total: int = 0
    uptime: int = 0
    kernel: str = ""
    fingerprint: str = ""
    subscription: str = ""  # "active", "notfound", ...


@dataclass(frozen=True)
class DatastoreUsage:
    """One entry of GET /status/datastore-usage, joined with the
    datastore list's comment and maintenance mode."""

    store: str
    used: int | None = None
    total: int | None = None
    avail: int | None = None
    backend_type: str = "filesystem"  # or "s3"
    mount_status: str = "nonremovable"
    comment: str = ""
    maintenance: str = ""  # e.g. "read-only" / "offline"; empty when none
    # PBS's own linear-regression guess over the last month. None when it
    # has too little history yet; a date in the past means usage isn't
    # growing.
    estimated_full_date: int | None = None
    history: tuple[float | None, ...] = ()  # used/total ratios, oldest first
    error: str = ""

    @property
    def used_fraction(self) -> float | None:
        if not self.total or self.used is None:
            return None
        return self.used / self.total


@dataclass(frozen=True)
class BackupGroup:
    """One entry of GET /admin/datastore/{store}/groups."""

    backup_type: str  # "vm", "ct" or "host"
    backup_id: str
    backup_count: int = 0
    last_backup: int = 0
    owner: str = ""
    comment: str = ""

    @property
    def label(self) -> str:
        """"vm/101" -- how PBS writes a group everywhere."""
        return f"{self.backup_type}/{self.backup_id}"


@dataclass(frozen=True)
class Snapshot:
    """One entry of GET /admin/datastore/{store}/snapshots."""

    backup_type: str
    backup_id: str
    backup_time: int
    size: int | None = None
    protected: bool = False
    verify_state: str = ""  # "ok", "failed", or "" when never verified
    encrypted: bool = False  # has a key fingerprint
    owner: str = ""
    comment: str = ""
    files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def group_label(self) -> str:
        return f"{self.backup_type}/{self.backup_id}"


@dataclass(frozen=True)
class PbsJob:
    """A sync, verify, prune or garbage-collection job with its last and
    next run (GET /admin/sync, /admin/verify, /admin/prune, /admin/gc)."""

    kind: str  # "sync", "verify", "prune" or "gc"
    id: str
    store: str
    schedule: str = ""
    last_run_state: str = ""  # "OK", an error message, or "" if never run
    last_run_endtime: int | None = None
    next_run: int | None = None
    comment: str = ""
    # Sync jobs only: where it pulls from (or pushes to).
    remote: str = ""
    remote_store: str = ""

    @property
    def target(self) -> str:
        if self.kind == "sync" and self.remote_store:
            source = f"{self.remote}:{self.remote_store}" if self.remote else self.remote_store
            return f"{source} → {self.store}"
        return self.store


@dataclass(frozen=True)
class PbsTask:
    """One entry of GET /nodes/localhost/tasks."""

    upid: str
    worker_type: str
    worker_id: str = ""
    user: str = ""
    starttime: int = 0
    endtime: int | None = None
    status: str = ""  # "OK", "WARNINGS: n", an error, or "" while running

    @property
    def running(self) -> bool:
        return self.endtime is None

    @property
    def failed(self) -> bool:
        return not self.running and self.status != "OK" and not self.status.startswith("WARNINGS")

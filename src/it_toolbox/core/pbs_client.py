"""Proxmox Backup Server access over its REST API (port 8007) with an API
token -- no Qt, so it runs on async_utils' worker threads and is easy to
test with mocked requests.

Same shape as glinet_client: one stateless function per operation, the
host and its secret passed as plain first arguments, and one flat error
class (PbsApiError) for everything that can go wrong, including a
changed certificate. Each call opens its own requests session through
core/pinned_tls, so a host is either verified normally or pinned to the
fingerprint trusted when it was added -- never unchecked.

Response field names come from PBS's published API schema
(https://pbs.proxmox.com/docs/api-viewer/apidoc.js), checked against
PBS 4.2. PBS uses hyphenated keys ("backup-type"); the parsers below are
the only place that knows them.
"""

from typing import TYPE_CHECKING, Any

import requests

from it_toolbox.core import pinned_tls
from it_toolbox.core.pbs_models import (
    BackupGroup,
    DatastoreUsage,
    NodeStatus,
    PbsJob,
    PbsTask,
    Snapshot,
)

if TYPE_CHECKING:
    # Any object with url / token_id / verify_ssl / fingerprint will do;
    # core doesn't import modules at runtime.
    from it_toolbox.modules.infrastructure.hosts import InfrastructureHost

DEFAULT_PORT = 8007
# PBS is a single node; "localhost" always addresses it.
NODE = "localhost"
TIMEOUT = 15


class PbsApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def auth_header(token_id: str, secret: str) -> str:
    """PBS's token header. Unlike Proxmox VE (PVEAPIToken=id=secret) the
    id and secret are joined with a colon."""
    return f"PBSAPIToken={token_id}:{secret}"


def _request(host: "InfrastructureHost", secret: str, method: str, path: str, params: dict | None = None) -> Any:
    url = f"{host.url.rstrip('/')}/api2/json{path}"
    try:
        session = pinned_tls.make_session(host.url, host.verify_ssl, host.fingerprint)
    except ValueError as error:
        raise PbsApiError(str(error)) from error
    try:
        with session:
            response = session.request(
                method,
                url,
                params=params,
                headers={"Authorization": auth_header(host.token_id, secret)},
                timeout=TIMEOUT,
            )
    except requests.exceptions.SSLError as error:
        _raise_certificate_error(host, error)
    except requests.RequestException as error:
        raise PbsApiError(f"Couldn't reach {host.url}: {error}") from error

    if response.status_code == 401:
        raise PbsApiError(
            "The API token was rejected. Check the token ID (user@realm!name) and secret.", 401
        )
    if not response.ok:
        raise PbsApiError(_error_message(response), response.status_code)
    try:
        return response.json().get("data")
    except ValueError as error:
        raise PbsApiError(f"{host.url} didn't answer like a Proxmox Backup Server.") from error


def _raise_certificate_error(host: "InfrastructureHost", error: Exception):
    """Turns urllib3's generic fingerprint mismatch into a message that says
    the certificate changed."""
    if not host.verify_ssl and host.fingerprint:
        try:
            pinned_tls.check_pinned(host.url, host.fingerprint)
        except pinned_tls.CertificateMismatchError as mismatch:
            raise PbsApiError(str(mismatch)) from mismatch
        except OSError:
            pass
    raise PbsApiError(f"TLS error talking to {host.url}: {error}") from error


def _error_message(response: requests.Response) -> str:
    """PBS puts the reason in "message", parameter errors in "errors", and
    sometimes only in the status line."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        if body.get("message"):
            return str(body["message"]).strip()
        if isinstance(body.get("errors"), dict) and body["errors"]:
            return "; ".join(f"{k}: {v}" for k, v in body["errors"].items())
    text = (response.text or "").strip()
    if text and len(text) < 300 and not text.startswith("<"):
        return text
    return f"HTTP {response.status_code} {response.reason}".strip()


def _get(host: "InfrastructureHost", secret: str, path: str, params: dict | None = None) -> Any:
    return _request(host, secret, "GET", path, params)


# -- Host ---------------------------------------------------------------------


def test_connection(host: "InfrastructureHost", secret: str) -> str:
    """One line for the Add host dialog: version and the datastores this
    token can see (privilege separation means that can be fewer than
    exist)."""
    version = _get(host, secret, "/version") or {}
    stores = [d.get("store", "") for d in _get(host, secret, "/admin/datastore") or []]
    text = f"Proxmox Backup Server {version.get('version', '?')}.{version.get('release', '')}".rstrip(".")
    if stores:
        return f"{text}, datastores: {', '.join(stores)}"
    return f"{text}, no datastores visible to this token (it needs DatastoreAudit)"


def get_node_status(host: "InfrastructureHost", secret: str) -> NodeStatus:
    status = _get(host, secret, f"/nodes/{NODE}/status") or {}
    version = _get(host, secret, "/version") or {}
    try:
        subscription = (_get(host, secret, f"/nodes/{NODE}/subscription") or {}).get("status", "")
    except PbsApiError:
        subscription = ""  # needs Sys.Audit; not worth failing the card over
    memory = status.get("memory") or {}
    root = status.get("root") or {}
    kernel = status.get("current-kernel") or {}
    return NodeStatus(
        version=".".join(p for p in (version.get("version", ""), version.get("release", "")) if p),
        cpu=float(status.get("cpu") or 0),
        cpus=int((status.get("cpuinfo") or {}).get("cpus") or 0),
        memory_used=int(memory.get("used") or 0),
        memory_total=int(memory.get("total") or 0),
        root_used=int(root.get("used") or 0),
        root_total=int(root.get("total") or 0),
        uptime=int(status.get("uptime") or 0),
        kernel=kernel.get("release", "") or status.get("kversion", ""),
        fingerprint=(status.get("info") or {}).get("fingerprint", ""),
        subscription=subscription,
    )


# -- Datastores -----------------------------------------------------------------


def list_datastores(host: "InfrastructureHost", secret: str) -> list[DatastoreUsage]:
    """Every datastore the token can see, with usage and PBS's own
    estimated full date. Sorted by name."""
    configs = {d.get("store"): d for d in _get(host, secret, "/admin/datastore") or []}
    usage = {u.get("store"): u for u in _get(host, secret, "/status/datastore-usage") or []}
    result = []
    for store in sorted(set(configs) | set(usage), key=lambda s: str(s)):
        if not store:
            continue
        result.append(_parse_usage(store, usage.get(store, {}), configs.get(store, {})))
    return result


def _parse_usage(store: str, usage: dict, config: dict) -> DatastoreUsage:
    history = tuple(
        float(v) if isinstance(v, (int, float)) else None for v in usage.get("history") or ()
    )
    return DatastoreUsage(
        store=store,
        used=_int_or_none(usage.get("used")),
        total=_int_or_none(usage.get("total")),
        avail=_int_or_none(usage.get("avail")),
        backend_type=usage.get("backend-type") or config.get("backend-type") or "filesystem",
        mount_status=usage.get("mount-status") or config.get("mount-status") or "",
        comment=config.get("comment", "") or "",
        maintenance=_maintenance_label(config.get("maintenance")),
        estimated_full_date=_int_or_none(usage.get("estimated-full-date")),
        history=history,
        error=usage.get("error", "") or "",
    )


def _maintenance_label(value: str | None) -> str:
    """The datastore list sends maintenance mode as a property string,
    "type=read-only,message=..." -- only the type is shown."""
    if not value:
        return ""
    for part in str(value).split(","):
        key, _, val = part.partition("=")
        if key == "type" or not val:
            return val or key
    return str(value)


def list_namespaces(host: "InfrastructureHost", secret: str, store: str) -> list[str]:
    """Namespace paths ("", "site-a", "site-a/web"), root first."""
    entries = _get(host, secret, f"/admin/datastore/{store}/namespace") or []
    names = sorted({str(e.get("ns") or "") for e in entries})
    return names if "" in names else ["", *names]


def list_groups(host: "InfrastructureHost", secret: str, store: str, ns: str = "") -> list[BackupGroup]:
    entries = _get(host, secret, f"/admin/datastore/{store}/groups", _ns_params(ns)) or []
    groups = [
        BackupGroup(
            backup_type=e.get("backup-type", ""),
            backup_id=str(e.get("backup-id", "")),
            backup_count=int(e.get("backup-count") or 0),
            last_backup=int(e.get("last-backup") or 0),
            owner=e.get("owner", "") or "",
            comment=e.get("comment", "") or "",
        )
        for e in entries
    ]
    return sorted(groups, key=_group_sort_key)


def list_snapshots(
    host: "InfrastructureHost",
    secret: str,
    store: str,
    ns: str = "",
    group: BackupGroup | None = None,
) -> list[Snapshot]:
    """Snapshots in a datastore (or one group of it), newest first."""
    params = _ns_params(ns)
    if group is not None:
        params.update({"backup-type": group.backup_type, "backup-id": group.backup_id})
    entries = _get(host, secret, f"/admin/datastore/{store}/snapshots", params) or []
    snapshots = [_parse_snapshot(e) for e in entries]
    return sorted(snapshots, key=lambda s: (_group_sort_key(s), -s.backup_time))


def _parse_snapshot(entry: dict) -> Snapshot:
    files = entry.get("files") or []
    return Snapshot(
        backup_type=entry.get("backup-type", ""),
        backup_id=str(entry.get("backup-id", "")),
        backup_time=int(entry.get("backup-time") or 0),
        size=_int_or_none(entry.get("size")),
        protected=bool(entry.get("protected")),
        verify_state=(entry.get("verification") or {}).get("state", "") or "",
        encrypted=bool(entry.get("fingerprint")),
        owner=entry.get("owner", "") or "",
        comment=entry.get("comment", "") or "",
        # Older PBS sends {"filename": ...} objects, newer plain names.
        files=tuple(f.get("filename", "") if isinstance(f, dict) else str(f) for f in files),
    )


def _ns_params(ns: str) -> dict:
    return {"ns": ns} if ns else {}


_TYPE_ORDER = {"vm": 0, "ct": 1, "host": 2}


def _group_sort_key(item) -> tuple:
    """vm before ct before host, then numerically by id (vm/2 < vm/10)."""
    backup_id = item.backup_id
    numeric = (0, int(backup_id), "") if backup_id.isdigit() else (1, 0, backup_id.lower())
    return (_TYPE_ORDER.get(item.backup_type, 3), *numeric)


# -- Jobs and tasks -----------------------------------------------------------


_JOB_PATHS = {"sync": "/admin/sync", "verify": "/admin/verify", "prune": "/admin/prune", "gc": "/admin/gc"}


def list_jobs(host: "InfrastructureHost", secret: str) -> list[PbsJob]:
    """Sync, verify, prune and GC jobs with their last and next run. A job
    kind the token can't read is skipped rather than failing the list."""
    jobs: list[PbsJob] = []
    errors: list[PbsApiError] = []
    for kind, path in _JOB_PATHS.items():
        try:
            entries = _get(host, secret, path) or []
        except PbsApiError as error:
            if error.status != 403:
                errors.append(error)
            continue
        jobs.extend(_parse_job(kind, e) for e in entries)
    if errors and not jobs:
        raise errors[0]
    return jobs


def _parse_job(kind: str, entry: dict) -> PbsJob:
    store = entry.get("store", "") or ""
    return PbsJob(
        kind=kind,
        # GC has no job id: it is one per datastore.
        id=entry.get("id") or store,
        store=store,
        schedule=entry.get("schedule", "") or "",
        last_run_state=entry.get("last-run-state", "") or "",
        last_run_endtime=_int_or_none(entry.get("last-run-endtime")),
        next_run=_int_or_none(entry.get("next-run")),
        comment=entry.get("comment", "") or "",
        remote=entry.get("remote", "") or "",
        remote_store=entry.get("remote-store", "") or "",
    )


def list_tasks(host: "InfrastructureHost", secret: str, limit: int = 50, errors_only: bool = False) -> list[PbsTask]:
    params: dict = {"limit": limit}
    if errors_only:
        params["errors"] = 1
    entries = _get(host, secret, f"/nodes/{NODE}/tasks", params) or []
    return [
        PbsTask(
            upid=e.get("upid", ""),
            worker_type=e.get("worker_type", ""),
            worker_id=e.get("worker_id", "") or "",
            user=e.get("user", "") or "",
            starttime=int(e.get("starttime") or 0),
            endtime=_int_or_none(e.get("endtime")),
            status=e.get("status", "") or "",
        )
        for e in entries
    ]


def get_task_log(host: "InfrastructureHost", secret: str, upid: str, limit: int = 500) -> list[str]:
    entries = _get(host, secret, f"/nodes/{NODE}/tasks/{requests.utils.quote(upid, safe='')}/log", {"limit": limit}) or []
    return [str(e.get("t", "")) for e in entries]


def _int_or_none(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


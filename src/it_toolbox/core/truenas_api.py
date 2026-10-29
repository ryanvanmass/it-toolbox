"""The TrueNAS calls the dashboard makes, one function each, over an open
TrueNasConnection (core/truenas_client.py), returning truenas_models
dataclasses. Kept apart from the client so the client stays a plain
JSON-RPC transport and these stay easy to test with a fake connection.

Method names are the 25.04 API's. Where 25.10 renamed something, the
newer name is tried first and the older one used if the NAS says the
method doesn't exist.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from it_toolbox.core import truenas_models as tm
from it_toolbox.core.truenas_client import TrueNasApiError, TrueNasConnection

Progress = Callable[[int, str], None] | None


def _call_first(connection: TrueNasConnection, methods: tuple[str, ...], *params: Any) -> Any:
    """Calls the first of `methods` this release has."""
    for method in methods[:-1]:
        try:
            return connection.call(method, *params)
        except TrueNasApiError as error:
            if not error.is_method_missing:
                raise
    return connection.call(methods[-1], *params)


# -- Overview ------------------------------------------------------------------


def get_overview(connection: TrueNasConnection) -> tm.SystemOverview:
    return tm.SystemOverview.from_api(connection.call("system.info") or {})


def list_alerts(connection: TrueNasConnection) -> list[tm.Alert]:
    alerts = [tm.Alert.from_api(a) for a in connection.call("alert.list") or [] if isinstance(a, dict)]
    order = {level: i for i, level in enumerate(tm.ALERT_LEVELS)}
    return sorted(alerts, key=lambda a: (a.dismissed, order.get(a.level, len(order))))


def dismiss_alert(connection: TrueNasConnection, uuid: str) -> None:
    connection.call("alert.dismiss", uuid)


def host_health(connection: TrueNasConnection) -> str:
    return tm.health(list_alerts(connection), list_pools(connection))


# -- Storage -------------------------------------------------------------------


def list_pools(connection: TrueNasConnection) -> list[tm.Pool]:
    return [tm.Pool.from_api(p) for p in connection.call("pool.query") or [] if isinstance(p, dict)]


def list_disks(connection: TrueNasConnection) -> list[tm.Disk]:
    disks = [d for d in connection.call("disk.query") or [] if isinstance(d, dict)]
    try:
        temperatures = connection.call("disk.temperatures", [d.get("name") for d in disks if d.get("name")])
    except TrueNasApiError:
        temperatures = {}  # some controllers / VMs report none
    return [tm.Disk.from_api(d, temperatures) for d in disks]


def start_scrub(connection: TrueNasConnection, pool_id: int, on_progress: Progress = None) -> None:
    connection.call_job("pool.scrub", pool_id, "START", on_progress=on_progress)


def run_smart_test(connection: TrueNasConnection, disk_identifiers: list[str], kind: str = "SHORT") -> None:
    connection.call("smart.test.manual_test", [{"identifier": d, "type": kind} for d in disk_identifiers])


# -- Datasets and snapshots ------------------------------------------------------


def list_datasets(connection: TrueNasConnection) -> list[tm.Dataset]:
    rows = connection.call(
        "pool.dataset.query", [], {"extra": {"flat": True, "retrieve_children": False}}
    ) or []
    return sorted((tm.Dataset.from_api(d) for d in rows if isinstance(d, dict)), key=lambda d: d.id)


SNAPSHOT_QUERY_OPTIONS = {"extra": {"properties": ["creation", "used", "referenced"]}, "order_by": ["-createtxg"]}


def list_snapshots(connection: TrueNasConnection, dataset: str) -> list[tm.Snapshot]:
    rows = _call_first(
        connection,
        ("pool.snapshot.query", "zfs.snapshot.query"),
        [["dataset", "=", dataset]],
        SNAPSHOT_QUERY_OPTIONS,
    ) or []
    return [tm.Snapshot.from_api(s) for s in rows if isinstance(s, dict)]


def create_snapshot(connection: TrueNasConnection, dataset: str, name: str, recursive: bool = False) -> None:
    _call_first(
        connection,
        ("pool.snapshot.create", "zfs.snapshot.create"),
        {"dataset": dataset, "name": name, "recursive": recursive},
    )


def delete_snapshot(connection: TrueNasConnection, snapshot_id: str) -> None:
    _call_first(connection, ("pool.snapshot.delete", "zfs.snapshot.delete"), snapshot_id)


def rollback_snapshot(connection: TrueNasConnection, snapshot_id: str) -> None:
    """Refuses (as TrueNAS does) when newer snapshots exist -- never
    passes recursive/force, so nothing newer is destroyed silently."""
    _call_first(connection, ("pool.snapshot.rollback", "zfs.snapshot.rollback"), snapshot_id, {})


def clone_snapshot(connection: TrueNasConnection, snapshot_id: str, new_dataset: str) -> None:
    _call_first(
        connection,
        ("pool.snapshot.clone", "zfs.snapshot.clone"),
        {"snapshot": snapshot_id, "dataset_dst": new_dataset},
    )


# -- Data protection ---------------------------------------------------------------

#: kind -> (run-now method, update method)
TASK_METHODS = {
    "snapshot": ("pool.snapshottask.run", "pool.snapshottask.update"),
    "replication": ("replication.run", "replication.update"),
    "cloudsync": ("cloudsync.sync", "cloudsync.update"),
    "cloud_backup": ("cloud_backup.sync", "cloud_backup.update"),
    "rsync": ("rsynctask.run", "rsynctask.update"),
    "scrub": ("pool.scrub.run", "pool.scrub.update"),
    "smart": ("", "smart.test.update"),
}


def list_protection_tasks(connection: TrueNasConnection) -> tuple[list[tm.ProtectionTask], list[str]]:
    """Every data protection task, plus the kinds this NAS couldn't list
    (e.g. TrueCloud backup on a release without it) for a footnote."""
    tasks, missing = [], []
    for kind, method, label in tm.TASK_KINDS:
        try:
            rows = connection.call(method) or []
        except TrueNasApiError as error:
            if error.is_method_missing:
                missing.append(label)
                continue
            raise
        tasks.extend(tm.ProtectionTask.from_api(kind, r) for r in rows if isinstance(r, dict))
    return tasks, missing


def run_task(connection: TrueNasConnection, task: tm.ProtectionTask) -> None:
    """Starts the task now. Doesn't wait for its job: replication or a cloud
    sync can run for hours, and its progress shows in the task's state."""
    method, _update = TASK_METHODS[task.kind]
    if not method:
        raise ValueError(f"{task.kind_label} tasks can't be run on demand.")
    if task.kind == "scrub":
        connection.call(method, task.name)  # pool.scrub.run takes the pool name
    else:
        connection.call(method, task.id)


def set_task_enabled(connection: TrueNasConnection, task: tm.ProtectionTask, enabled: bool) -> None:
    _run, method = TASK_METHODS[task.kind]
    connection.call(method, task.id, {"enabled": enabled})


def job_log(connection: TrueNasConnection, job_id: int) -> str:
    jobs = connection.call("core.get_jobs", [["id", "=", job_id]]) or []
    if not jobs:
        return "That job is no longer in the NAS's job history."
    job = jobs[0]
    parts = [f"State: {job.get('state', '?')}"]
    if job.get("error"):
        parts.append(f"Error: {str(job['error']).strip()}")
    excerpt = job.get("logs_excerpt")
    if excerpt:
        parts.append(str(excerpt).rstrip())
    return "\n\n".join(parts)


def list_credentials(connection: TrueNasConnection) -> list[tm.Credential]:
    keychain = [tm.Credential.from_keychain(c) for c in connection.call("keychaincredential.query") or [] if isinstance(c, dict)]
    cloud = [tm.Credential.from_cloud(c) for c in connection.call("cloudsync.credentials.query") or [] if isinstance(c, dict)]
    return keychain + cloud


def test_credential(connection: TrueNasConnection, credential: tm.Credential) -> str:
    """A one-line verdict. The secrets go from the NAS's own record back to
    the NAS's own verify method -- they're never shown or kept here."""
    if credential.source == "cloud":
        rows = connection.call("cloudsync.credentials.query", [["id", "=", credential.id]]) or []
        if not rows:
            return "That credential no longer exists."
        record = rows[0]
        provider = record.get("provider")
        if isinstance(provider, dict):
            payload = provider
        else:  # pre-25.04 shape
            payload = {"provider": provider, "attributes": record.get("attributes") or {}}
        result = connection.call("cloudsync.credentials.verify", payload) or {}
        if result.get("valid"):
            return "The NAS reached the provider with this credential."
        return f"Failed: {str(result.get('error') or result.get('excerpt') or 'invalid credential').strip()}"
    if credential.kind == "SSH connection":
        connection.call("replication.list_datasets", "SSH", credential.id)
        return "The NAS logged in to the remote host with this connection."
    return "Key pairs can't be tested on their own -- test an SSH connection that uses it."


# -- Shares ----------------------------------------------------------------------


def list_shares(connection: TrueNasConnection) -> tuple[list[tm.Share], dict[str, tm.Service]]:
    smb = [tm.Share.from_smb(s) for s in connection.call("sharing.smb.query") or [] if isinstance(s, dict)]
    nfs = [tm.Share.from_nfs(s) for s in connection.call("sharing.nfs.query") or [] if isinstance(s, dict)]
    services = {
        s.name: s
        for s in (
            tm.Service.from_api(row)
            for row in connection.call("service.query", [["service", "in", list(tm.SHARE_SERVICES.values())]]) or []
            if isinstance(row, dict)
        )
    }
    return smb + nfs, services


def set_share_enabled(connection: TrueNasConnection, share: tm.Share, enabled: bool) -> None:
    method = "sharing.smb.update" if share.protocol == "SMB" else "sharing.nfs.update"
    connection.call(method, share.id, {"enabled": enabled})


def restart_service(connection: TrueNasConnection, service: str, on_progress: Progress = None) -> None:
    try:
        connection.call_job("service.control", "RESTART", service, {}, on_progress=on_progress)
    except TrueNasApiError as error:
        if not error.is_method_missing:
            raise
        connection.call("service.restart", service)


# -- Apps ------------------------------------------------------------------------


def list_apps(connection: TrueNasConnection) -> list[tm.App]:
    rows = connection.call("app.query", [], {"extra": {"retrieve_config": False}}) or []
    return sorted((tm.App.from_api(a) for a in rows if isinstance(a, dict)), key=lambda a: a.name)


APP_ACTIONS = {"start": "app.start", "stop": "app.stop", "restart": "app.redeploy"}


def app_action(connection: TrueNasConnection, name: str, action: str, on_progress: Progress = None) -> None:
    connection.call_job(APP_ACTIONS[action], name, on_progress=on_progress)


def update_app(connection: TrueNasConnection, name: str, on_progress: Progress = None) -> None:
    connection.call_job("app.upgrade", name, {}, on_progress=on_progress)


def follow_app_logs(
    connection: TrueNasConnection, app: str, container_id: str, on_line: Callable[[str], None], tail_lines: int = 500
) -> Callable[[], None]:
    """Streams a container's log; on_line runs on the client's reader
    thread. Returns the function that stops it."""
    name = "app.container_log_follow: " + json.dumps(
        {"app_name": app, "container_id": container_id, "tail_lines": tail_lines}
    )

    def on_event(_msg: str, fields: dict) -> None:
        data = fields.get("data")
        if data:
            on_line(str(data).rstrip("\n"))

    return connection.subscribe(name, on_event)


# -- VMs -------------------------------------------------------------------------


def list_vms(connection: TrueNasConnection) -> list[tm.Vm]:
    return sorted(
        (tm.Vm.from_api(v) for v in connection.call("vm.query") or [] if isinstance(v, dict)), key=lambda v: v.name
    )


def vm_action(connection: TrueNasConnection, vm_id: int, action: str, on_progress: Progress = None) -> None:
    if action == "start":
        connection.call("vm.start", vm_id)
    elif action == "stop":  # ACPI shutdown, waits for the guest
        connection.call_job("vm.stop", vm_id, {"force": False}, on_progress=on_progress)
    elif action == "poweroff":
        connection.call("vm.poweroff", vm_id)
    else:
        raise ValueError(action)


# -- Live stats --------------------------------------------------------------------


def follow_realtime(connection: TrueNasConnection, on_stats: Callable[[tm.RealtimeStats], None]) -> Callable[[], None]:
    def on_event(_msg: str, fields: dict) -> None:
        on_stats(tm.RealtimeStats.from_event(fields))

    return connection.subscribe("reporting.realtime", on_event)

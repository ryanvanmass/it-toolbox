import threading

import pytest
from truenas_fake import API_KEY, FakeTrueNas

from it_toolbox.core import truenas_api as api
from it_toolbox.core import truenas_models as tm
from it_toolbox.core.truenas_client import TrueNasApiError, TrueNasConnection


@pytest.fixture
def nas(tmp_path):
    with FakeTrueNas(tmp_path) as server:
        yield server


@pytest.fixture
def conn(nas):
    connection = TrueNasConnection(nas.url, API_KEY, fingerprint=nas.fingerprint).open()
    yield connection
    connection.close()


def test_overview(conn):
    overview = api.get_overview(conn)
    assert overview.hostname == "nas01"
    assert overview.cores == 8
    assert overview.ecc_memory is True
    assert tm.format_duration(overview.uptime_seconds) == "1d 2h"


def test_alerts_sorted_by_severity_with_dismissed_last(conn):
    alerts = api.list_alerts(conn)
    assert [a.uuid for a in alerts] == ["a1", "a2", "a3"]
    assert alerts[0].when is not None


def test_health_ignores_dismissed_alerts(conn, nas):
    assert api.host_health(conn) == "amber"  # WARNING active, CRITICAL dismissed
    nas.results["pool.query"][0]["healthy"] = False
    assert api.host_health(conn) == "red"


def test_pools_and_topology(conn):
    (pool,) = api.list_pools(conn)
    assert pool.name == "tank"
    assert pool.used_percent == 38
    mirror = pool.topology["data"][0]
    assert mirror.kind == "MIRROR"
    assert [d.disk for d in mirror.children] == ["sda", "sdb"]
    assert mirror.children[1].checksum_errors == 2
    assert "cache" not in pool.topology  # empty roles dropped


def test_disks_with_temperatures(conn, nas):
    disks = api.list_disks(conn)
    assert [(d.name, d.temperature) for d in disks] == [("sda", 34), ("sdb", 37)]
    assert ("disk.temperatures", [["sda", "sdb"]]) in nas.calls


def test_disks_without_temperatures(conn, nas):
    nas.errors["disk.temperatures"] = {"code": -32001, "message": "no sensors"}
    assert [d.temperature for d in api.list_disks(conn)] == [None, None]


def test_datasets(conn):
    datasets = {d.id: d for d in api.list_datasets(conn)}
    assert datasets["tank/media"].quota == 10000
    assert datasets["tank"].quota is None
    assert datasets["tank/vault"].locked
    assert datasets["tank/media"].parent == "tank"


def test_snapshots_use_pool_snapshot(conn, nas):
    (snapshot,) = api.list_snapshots(conn, "tank/media")
    assert snapshot.name == "auto-2025-10-29"
    assert snapshot.referenced == 2048
    assert snapshot.created is not None
    assert nas.methods_called()[-1] == "pool.snapshot.query"


def test_snapshots_fall_back_to_zfs_snapshot(conn, nas):
    nas.results["zfs.snapshot.query"] = nas.results.pop("pool.snapshot.query")
    assert api.list_snapshots(conn, "tank/media")[0].dataset == "tank/media"
    assert nas.methods_called()[-2:] == ["pool.snapshot.query", "zfs.snapshot.query"]


def test_fallback_does_not_hide_real_errors(conn, nas):
    nas.errors["pool.snapshot.delete"] = {"code": -32001, "message": "x", "data": {"reason": "busy"}}
    with pytest.raises(TrueNasApiError, match="busy"):
        api.delete_snapshot(conn, "tank/media@x")
    assert "zfs.snapshot.delete" not in nas.methods_called()


def test_snapshot_actions(conn, nas):
    api.create_snapshot(conn, "tank/media", "manual-1")
    api.rollback_snapshot(conn, "tank/media@manual-1")
    api.clone_snapshot(conn, "tank/media@manual-1", "tank/clone")
    api.delete_snapshot(conn, "tank/media@manual-1")
    assert ("pool.snapshot.create", [{"dataset": "tank/media", "name": "manual-1", "recursive": False}]) in nas.calls
    assert ("pool.snapshot.rollback", ["tank/media@manual-1", {}]) in nas.calls
    assert ("pool.snapshot.clone", [{"snapshot": "tank/media@manual-1", "dataset_dst": "tank/clone"}]) in nas.calls


def test_protection_tasks(conn):
    tasks, missing = api.list_protection_tasks(conn)
    kinds = [t.kind for t in tasks]
    assert kinds == ["snapshot", "replication", "cloudsync", "scrub", "smart"]
    assert missing == ["TrueCloud backup"]  # the fake has no cloud_backup.query
    replication = tasks[1]
    assert replication.target == "tank/media → backup/media (SSH)"
    assert replication.last_state == "FAILED"
    assert replication.last_error == "No route to host"
    assert replication.credential_id == 7
    assert replication.job_id == 41
    assert tasks[0].schedule == "0 * * * *"
    assert tasks[2].credential_id == 9
    assert tasks[2].last_state == ""
    assert not tasks[4].can_run_now


def test_run_and_toggle_tasks(conn, nas):
    tasks, _ = api.list_protection_tasks(conn)
    by_kind = {t.kind: t for t in tasks}
    api.run_task(conn, by_kind["replication"])
    api.run_task(conn, by_kind["scrub"])
    api.set_task_enabled(conn, by_kind["cloudsync"], True)
    assert ("replication.run", [3]) in nas.calls
    assert ("pool.scrub.run", ["tank"]) in nas.calls
    assert ("cloudsync.update", [4, {"enabled": True}]) in nas.calls
    with pytest.raises(ValueError):
        api.run_task(conn, by_kind["smart"])


def test_job_log_for_a_vanished_job(conn):
    assert "no longer" in api.job_log(conn, 41)


def test_credentials_never_carry_secrets(conn):
    credentials = api.list_credentials(conn)
    assert [(c.name, c.kind, c.detail) for c in credentials] == [
        ("backup-nas", "SSH connection", "root@10.0.0.9"),
        ("backup-nas key", "SSH keypair", "key pair"),
        ("b2-main", "B2", ""),
    ]
    text = repr(credentials)
    assert "SECRET" not in text and "BEGIN OPENSSH" not in text


def test_cloud_credential_test_sends_the_nas_its_own_record(conn, nas):
    cloud = [c for c in api.list_credentials(conn) if c.source == "cloud"][0]
    assert "reached" in api.test_credential(conn, cloud)
    assert ("cloudsync.credentials.verify", [{"type": "B2", "account": "acct", "key": "SECRETKEY"}]) in nas.calls


def test_ssh_credential_test(conn, nas):
    ssh = api.list_credentials(conn)[0]
    assert "logged in" in api.test_credential(conn, ssh)
    assert ("replication.list_datasets", ["SSH", 7]) in nas.calls


def test_shares_and_services(conn, nas):
    shares, services = api.list_shares(conn)
    assert [(s.protocol, s.name, s.enabled) for s in shares] == [("SMB", "media", True), ("NFS", "vms", False)]
    assert services["cifs"].running and not services["nfs"].running
    api.set_share_enabled(conn, shares[1], True)
    assert ("sharing.nfs.update", [2, {"enabled": True}]) in nas.calls


def test_restart_service_uses_service_control(conn, nas):
    api.restart_service(conn, "cifs")
    assert ("service.control", ["RESTART", "cifs", {}]) in nas.calls


def test_restart_service_falls_back_on_older_releases(conn, nas):
    nas.errors["service.control"] = {"code": -32601, "message": "Method does not exist"}
    nas.results["service.restart"] = True
    api.restart_service(conn, "nfs")
    assert ("service.restart", ["nfs"]) in nas.calls


def test_apps(conn, nas):
    (app,) = api.list_apps(conn)
    assert app.title == "ProFTPD"
    assert app.ports == ("2121/tcp",)
    assert app.upgrade_available
    assert app.containers[0].id == "c0ffee"
    api.app_action(conn, "proftpd", "restart")
    api.update_app(conn, "proftpd")
    assert ("app.redeploy", ["proftpd"]) in nas.calls
    assert ("app.upgrade", ["proftpd", {}]) in nas.calls


def test_app_logs_stream(conn, nas):
    got = threading.Event()
    lines = []

    def on_line(line):
        lines.append(line)
        got.set()

    stop = api.follow_app_logs(conn, "proftpd", "c0ffee", on_line, tail_lines=50)
    assert got.wait(5)
    assert lines == ["line one"]
    stop()
    subscribe = next(params for method, params in nas.calls if method == "core.subscribe")
    assert subscribe[0].startswith("app.container_log_follow: ")
    assert '"container_id": "c0ffee"' in subscribe[0]


def test_vms(conn, nas):
    (vm,) = api.list_vms(conn)
    assert (vm.name, vm.state, vm.vcpus, vm.memory_mib) == ("homeassistant", "RUNNING", 2, 4096)
    api.vm_action(conn, 1, "stop")
    api.vm_action(conn, 1, "poweroff")
    assert ("vm.stop", [1, {"force": False}]) in nas.calls
    assert ("vm.poweroff", [1]) in nas.calls


def test_realtime_stats(conn):
    got = threading.Event()
    stats = []
    stop = api.follow_realtime(conn, lambda s: (stats.append(s), got.set()))
    assert got.wait(5)
    stop()
    assert stats[0].cpu_percent == 12.5
    assert stats[0].memory_used == 17179869184
    assert stats[0].net_rx_bytes_per_sec == 1048576


def test_parsers_tolerate_missing_fields():
    assert tm.Pool.from_api({}).name == ""
    assert tm.App.from_api({"active_workloads": None}).ports == ()
    assert tm.ProtectionTask.from_api("replication", {}).last_state == ""
    assert tm.RealtimeStats.from_event({}).cpu_percent is None
    assert tm.parse_time("2025-10-29T00:00:00Z").year == 2025
    assert tm.format_bytes(1536) == "1.5 KiB"

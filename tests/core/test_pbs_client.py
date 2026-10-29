import pytest
import requests

from it_toolbox.core import pbs_client, pinned_tls
from it_toolbox.modules.infrastructure.hosts import InfrastructureHost

HOST = InfrastructureHost(
    name="pbs1",
    url="https://pbs1.lan:8007",
    token_id="backup@pbs!toolbox",
    fingerprint="AA:BB",
)

# Shapes as PBS 4.2's API schema documents them (hyphenated keys).
RESPONSES = {
    "/version": {"version": "4.2", "release": "8", "repoid": "abc"},
    "/admin/datastore": [
        {"store": "local", "backend-type": "filesystem", "mount-status": "nonremovable", "comment": "Main"},
        {"store": "offsite", "backend-type": "s3", "mount-status": "nonremovable", "maintenance": "type=read-only,message=moving"},
    ],
    "/status/datastore-usage": [
        {
            "store": "local",
            "used": 850,
            "total": 1000,
            "avail": 150,
            "backend-type": "filesystem",
            "mount-status": "nonremovable",
            "estimated-full-date": 1900000000,
            "history": [0.5, None, 0.85],
        },
        {"store": "offsite", "backend-type": "s3", "mount-status": "nonremovable", "error": "bucket unreachable"},
    ],
    "/nodes/localhost/status": {
        "cpu": 0.25,
        "cpuinfo": {"cpus": 4, "model": "x", "sockets": 1},
        "memory": {"used": 2048, "total": 8192, "free": 6144},
        "root": {"used": 10, "total": 100, "avail": 90},
        "uptime": 90061,
        "current-kernel": {"release": "6.14.8-pve"},
        "info": {"fingerprint": "AA:BB"},
    },
    "/nodes/localhost/subscription": {"status": "notfound"},
    "/admin/datastore/local/namespace": [{"ns": ""}, {"ns": "site-a"}],
    "/admin/datastore/local/groups": [
        {"backup-type": "host", "backup-id": "laptop", "backup-count": 1, "last-backup": 100, "files": []},
        {"backup-type": "vm", "backup-id": "10", "backup-count": 3, "last-backup": 300, "owner": "root@pam", "files": []},
        {"backup-type": "vm", "backup-id": "2", "backup-count": 2, "last-backup": 200, "comment": "dc01", "files": []},
        {"backup-type": "ct", "backup-id": "105", "backup-count": 1, "last-backup": 250, "files": []},
    ],
    "/admin/datastore/local/snapshots": [
        {"backup-type": "vm", "backup-id": "2", "backup-time": 100, "size": 5, "protected": False, "files": ["index.json.blob"]},
        {
            "backup-type": "vm",
            "backup-id": "2",
            "backup-time": 200,
            "size": 6,
            "protected": True,
            "fingerprint": "12:34",
            "verification": {"state": "failed", "upid": "UPID:x"},
            "comment": "before upgrade",
            "files": [{"filename": "drive-scsi0.img.fidx"}],
        },
        {"backup-type": "ct", "backup-id": "105", "backup-time": 150, "protected": False, "files": []},
    ],
    "/admin/sync": [
        {"id": "pull-main", "store": "offsite", "remote": "pbs2", "remote-store": "local", "schedule": "daily",
         "last-run-state": "OK", "last-run-endtime": 500, "next-run": 600},
    ],
    "/admin/verify": [{"id": "v-local", "store": "local", "schedule": "sat 02:00", "last-run-state": "verification failed"}],
    "/admin/prune": [],
    "/admin/gc": [{"store": "local", "schedule": "daily", "last-run-state": "OK", "next-run": 700}],
    "/nodes/localhost/tasks": [
        {"upid": "UPID:a", "worker_type": "verify", "worker_id": "local", "user": "root@pam", "starttime": 10, "endtime": 20, "status": "OK", "node": "localhost", "pid": 1, "pstart": 1},
        {"upid": "UPID:b", "worker_type": "garbage_collection", "user": "root@pam", "starttime": 30, "node": "localhost", "pid": 1, "pstart": 1},
    ],
}


class FakeResponse:
    def __init__(self, status: int, body, reason: str = "") -> None:
        self.status_code = status
        self._body = body
        self.reason = reason
        self.text = "" if body is None else str(body)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self):
        if isinstance(self._body, (dict, list)):
            return self._body
        raise ValueError("not json")


class FakeSession:
    def __init__(self, responses: dict, calls: list) -> None:
        self._responses = responses
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def request(self, method, url, params=None, headers=None, timeout=None):
        path = url.split("/api2/json", 1)[1]
        self._calls.append((method, path, params, headers))
        response = self._responses.get(path)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, FakeResponse):
            return response
        if response is None:
            return FakeResponse(404, {"message": f"no such path {path}"}, "Not Found")
        return FakeResponse(200, {"data": response})


@pytest.fixture
def api(monkeypatch):
    calls: list = []
    responses = dict(RESPONSES)
    made: list = []

    def make_session(url, verify_ssl, fingerprint):
        made.append((url, verify_ssl, fingerprint))
        return FakeSession(responses, calls)

    monkeypatch.setattr(pinned_tls, "make_session", make_session)
    return responses, calls, made


def test_token_header_uses_colon_not_equals():
    assert pbs_client.auth_header("backup@pbs!toolbox", "s3cret") == "PBSAPIToken=backup@pbs!toolbox:s3cret"


def test_requests_go_through_pinned_session_with_token(api):
    _responses, calls, made = api
    pbs_client.test_connection(HOST, "s3cret")
    assert made[0] == ("https://pbs1.lan:8007", False, "AA:BB")
    method, path, _params, headers = calls[0]
    assert (method, path) == ("GET", "/version")
    assert headers["Authorization"] == "PBSAPIToken=backup@pbs!toolbox:s3cret"


def test_test_connection_summary(api):
    assert pbs_client.test_connection(HOST, "x") == "Proxmox Backup Server 4.2.8, datastores: local, offsite"


def test_test_connection_without_visible_datastores(api):
    api[0]["/admin/datastore"] = []
    assert "no datastores visible" in pbs_client.test_connection(HOST, "x")


def test_rejected_token(api):
    api[0]["/version"] = FakeResponse(401, None, "authentication failed")
    with pytest.raises(pbs_client.PbsApiError, match="token was rejected") as info:
        pbs_client.test_connection(HOST, "x")
    assert info.value.status == 401


def test_error_message_comes_from_body(api):
    api[0]["/version"] = FakeResponse(403, {"data": None, "message": "permission check failed\n"}, "Forbidden")
    with pytest.raises(pbs_client.PbsApiError, match="^permission check failed$"):
        pbs_client.test_connection(HOST, "x")


def test_parameter_errors_are_listed(api):
    api[0]["/version"] = FakeResponse(400, {"data": None, "errors": {"ns": "bad value"}}, "Bad Request")
    with pytest.raises(pbs_client.PbsApiError, match="ns: bad value"):
        pbs_client.test_connection(HOST, "x")


def test_connection_failure(api):
    api[0]["/version"] = requests.ConnectionError("refused")
    with pytest.raises(pbs_client.PbsApiError, match="Couldn't reach https://pbs1.lan:8007"):
        pbs_client.test_connection(HOST, "x")


def test_changed_certificate_is_explained(api, monkeypatch):
    api[0]["/version"] = requests.exceptions.SSLError("fingerprint mismatch")

    def check_pinned(url, fingerprint):
        raise pinned_tls.CertificateMismatchError(url, fingerprint, "CC:DD")

    monkeypatch.setattr(pinned_tls, "check_pinned", check_pinned)
    with pytest.raises(pbs_client.PbsApiError, match="certificate for https://pbs1.lan:8007 has changed"):
        pbs_client.test_connection(HOST, "x")


def test_missing_fingerprint_is_an_api_error(monkeypatch):
    host = HOST.with_changes(fingerprint=None)
    with pytest.raises(pbs_client.PbsApiError, match="No pinned certificate"):
        pbs_client.test_connection(host, "x")


def test_node_status(api):
    status = pbs_client.get_node_status(HOST, "x")
    assert status.version == "4.2.8"
    assert status.cpus == 4 and status.cpu == 0.25
    assert (status.memory_used, status.memory_total) == (2048, 8192)
    assert status.kernel == "6.14.8-pve"
    assert status.subscription == "notfound"


def test_node_status_survives_forbidden_subscription(api):
    api[0]["/nodes/localhost/subscription"] = FakeResponse(403, {"message": "no"}, "Forbidden")
    assert pbs_client.get_node_status(HOST, "x").subscription == ""


def test_list_datastores_joins_config_and_usage(api):
    local, offsite = pbs_client.list_datastores(HOST, "x")
    assert local.store == "local" and local.comment == "Main"
    assert local.used_fraction == pytest.approx(0.85)
    assert local.estimated_full_date == 1900000000
    assert local.history == (0.5, None, 0.85)
    assert offsite.backend_type == "s3"
    assert offsite.maintenance == "read-only"
    assert offsite.error == "bucket unreachable"
    assert offsite.used_fraction is None


def test_maintenance_label():
    assert pbs_client._maintenance_label(None) == ""
    assert pbs_client._maintenance_label("type=offline") == "offline"
    assert pbs_client._maintenance_label("message=x,type=read-only") == "read-only"
    assert pbs_client._maintenance_label("read-only") == "read-only"


def test_list_namespaces_root_first(api):
    assert pbs_client.list_namespaces(HOST, "x", "local") == ["", "site-a"]
    api[0]["/admin/datastore/local/namespace"] = [{"ns": "b"}]
    assert pbs_client.list_namespaces(HOST, "x", "local") == ["", "b"]


def test_list_groups_sorted_by_type_then_numeric_id(api):
    labels = [g.label for g in pbs_client.list_groups(HOST, "x", "local")]
    assert labels == ["vm/2", "vm/10", "ct/105", "host/laptop"]


def test_list_groups_passes_namespace(api):
    pbs_client.list_groups(HOST, "x", "local", "site-a")
    assert api[1][-1][2] == {"ns": "site-a"}
    pbs_client.list_groups(HOST, "x", "local")
    assert api[1][-1][2] == {}


def test_list_snapshots(api):
    snapshots = pbs_client.list_snapshots(HOST, "x", "local")
    assert [(s.group_label, s.backup_time) for s in snapshots] == [("vm/2", 200), ("vm/2", 100), ("ct/105", 150)]
    newest = snapshots[0]
    assert newest.protected and newest.encrypted
    assert newest.verify_state == "failed"
    assert newest.files == ("drive-scsi0.img.fidx",)
    assert snapshots[1].verify_state == "" and not snapshots[1].encrypted
    assert snapshots[2].size is None


def test_list_snapshots_for_one_group(api):
    group = pbs_client.list_groups(HOST, "x", "local")[0]
    pbs_client.list_snapshots(HOST, "x", "local", "site-a", group)
    assert api[1][-1][2] == {"ns": "site-a", "backup-type": "vm", "backup-id": "2"}


def test_list_jobs(api):
    jobs = {(j.kind, j.id): j for j in pbs_client.list_jobs(HOST, "x")}
    assert set(jobs) == {("sync", "pull-main"), ("verify", "v-local"), ("gc", "local")}
    assert jobs[("sync", "pull-main")].target == "pbs2:local → offsite"
    assert jobs[("verify", "v-local")].last_run_state == "verification failed"
    assert jobs[("gc", "local")].next_run == 700


def test_list_jobs_skips_kinds_the_token_cannot_read(api):
    api[0]["/admin/sync"] = FakeResponse(403, {"message": "no"}, "Forbidden")
    kinds = {j.kind for j in pbs_client.list_jobs(HOST, "x")}
    assert kinds == {"verify", "gc"}


def test_list_jobs_raises_when_everything_fails(api):
    for path in ("/admin/sync", "/admin/verify", "/admin/prune", "/admin/gc"):
        api[0][path] = requests.ConnectionError("down")
    with pytest.raises(pbs_client.PbsApiError):
        pbs_client.list_jobs(HOST, "x")


def test_list_tasks(api):
    done, running = pbs_client.list_tasks(HOST, "x")
    assert not done.running and not done.failed
    assert running.running and not running.failed
    assert api[1][-1][2] == {"limit": 50}


def test_task_log_quotes_upid(api):
    api[0]["/nodes/localhost/tasks/UPID%3Apbs%3A1%3A/log"] = [{"n": 1, "t": "start"}, {"n": 2, "t": "TASK OK"}]
    assert pbs_client.get_task_log(HOST, "x", "UPID:pbs:1:") == ["start", "TASK OK"]

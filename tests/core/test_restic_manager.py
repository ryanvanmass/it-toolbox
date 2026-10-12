import json
import shlex

from it_toolbox.core import remote_helper as rh
from it_toolbox.core import restic_manager as rm

SERVER = rm.ResticServer(name="lab", host="lab.lan", username="root")


class _Scripted(rm.ResticConnection):
    """Answers every helper call with `reply`, recording (subcommand, args, timeout)."""

    def __init__(self, reply):
        super().__init__(SERVER)
        self._client = object()
        self.helper_path = rm.HELPER_PATH
        self.reply = reply
        self.calls = []

    def _exec_raw(self, command, stdin=b"", timeout=rh.DEFAULT_TIMEOUT):
        argv = shlex.split(command)
        assert argv[0] == rm.HELPER_PATH
        self.calls.append((argv[1], json.loads(stdin), timeout))
        return 0, json.dumps(self.reply), ""


def test_finds_the_rpm_helper_path():
    assert rm.ResticConnection.HELPER_PATHS == ("/usr/libexec/cockpit-restic/cockpit-restic-helper",)


def test_create_repo_sends_only_the_backends_fields():
    connection = _Scripted({"repo": {"id": "r1"}, "generated_password": "pw"})

    result = connection.create_repo("NAS", "sftp", host="nas.lan", port=2222, remote_path="/srv/r", user="bk")

    assert result["generated_password"] == "pw"
    name, args, timeout = connection.calls[0]
    assert name == "create-repo" and timeout == rm.SLOW_TIMEOUT
    assert args == {"name": "NAS", "backend": "sftp", "host": "nas.lan", "port": 2222, "remote_path": "/srv/r",
                    "user": "bk"}

    connection.create_repo("Local", "local", path="/mnt/b", password="")
    assert connection.calls[1][1] == {"name": "Local", "backend": "local", "path": "/mnt/b"}


def test_update_repo_leaves_out_unchanged_fields_but_keeps_an_empty_schedule():
    connection = _Scripted({"repo": {"id": "r1"}})

    connection.update_repo("r1", check_schedule="", check_read_data=0)

    assert connection.calls[0][:2] == ("update-repo", {"id": "r1", "check_schedule": "", "check_read_data": 0})


def test_jobs_and_snapshots_use_the_helpers_argument_names():
    connection = _Scripted({"job": {}, "runs": [], "checks": [], "files": [], "snapshots": []})

    connection.update_job("j1", {"name": "home", "enabled": False, "pre_command": None})
    connection.trigger_job("j1")
    connection.list_job_runs("j1")
    connection.trigger_check("r1")
    connection.list_repo_checks("r1")
    connection.list_snapshot_files("r1", "abcd1234", "/home")
    connection.restore_snapshot("r1", "abcd1234", "/var/restore")
    connection.forget_snapshots("r1", ["abcd1234"])

    assert [(name, args) for name, args, _ in connection.calls] == [
        ("update-job", {"id": "j1", "name": "home", "enabled": False}),
        ("trigger-job", {"id": "j1"}),
        ("list-job-runs", {"job_id": "j1"}),
        ("trigger-check", {"repo_id": "r1"}),
        ("list-repo-checks", {"repo_id": "r1"}),
        ("list-snapshot-files", {"repo_id": "r1", "snapshot_id": "abcd1234", "path": "/home"}),
        ("restore-snapshot", {"repo_id": "r1", "snapshot_id": "abcd1234", "target": "/var/restore",
                              "include_paths": []}),
        ("forget-snapshots", {"repo_id": "r1", "snapshot_ids": ["abcd1234"]}),
    ]


def test_labels():
    assert rm.location_label({"backend": "local", "path": "/mnt/b"}) == "/mnt/b"
    assert rm.location_label({"backend": "sftp", "user": "bk", "host": "nas", "remote_path": "/r"}) == "bk@nas:/r"
    assert rm.retention_label(dict(rm.DEFAULT_RETENTION)) == "7 daily, 4 weekly, 6 monthly, 0 yearly"
    assert rm.schedule_label("daily") == "Daily" and rm.schedule_label("*-*-* 03:00") == "*-*-* 03:00"
    items = [{"name": "a", "last_run": {"status": "failure"}}, {"name": "b", "last_run": {"status": "running"}},
             {"name": "c", "last_run": None}]
    assert rm.failed_names(items, "last_run") == ["a"]
    assert rm.any_running(items, "last_run") and not rm.any_running(items[:1], "last_run")


def test_toggle_path_collapses_into_chosen_folders():
    lines = rm.toggle_path(["/home/alice/a.txt", "/etc/"], "/home/alice", True)
    assert lines == ["/etc/", "/home/alice"]
    assert rm.toggle_path(lines, "/etc", False) == ["/home/alice"]
    assert rm.toggle_path(["/x"], "/", True) == ["/"]
    assert rm.covered_by("/home/alice/a.txt", ["/home/alice"]) == "/home/alice"
    assert rm.covered_by("/home/alice", ["/home/alice"]) is None
    assert rm.covered_by("/home/alicex", ["/home/alice"]) is None
    assert rm.path_lines(" /a \n\n/b\n") == ["/a", "/b"]

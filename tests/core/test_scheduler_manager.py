import json
import shlex

import pytest

from it_toolbox.core import remote_helper as rh
from it_toolbox.core import scheduler_manager as sm

SERVER = sm.SchedulerServer(name="lab", host="lab.lan", username="root")
SHELLS = [
    {"name": "bash", "path": "/bin/bash", "aliases": ["/usr/bin/bash"]},
    {"name": "sh", "path": "/bin/sh", "aliases": []},
]


class _Scripted(sm.SchedulerConnection):
    """Answers every helper call with `reply`, recording (subcommand, args)."""

    def __init__(self, reply):
        super().__init__(SERVER)
        self._client = object()
        self.helper_path = sm.HELPER_PATH
        self.reply = reply
        self.calls = []

    def _exec_raw(self, command, stdin=b"", timeout=rh.DEFAULT_TIMEOUT):
        argv = shlex.split(command)
        assert argv[0] == sm.HELPER_PATH
        self.calls.append((argv[1], json.loads(stdin)))
        return 0, json.dumps(self.reply), ""


def test_finds_the_rpm_helper_path():
    assert sm.SchedulerConnection.HELPER_PATHS == ("/usr/libexec/cockpit-scheduler/cockpit-scheduler-helper",)


def test_server_round_trips_as_scheduler_server():
    assert isinstance(sm.SchedulerServer.from_dict(SERVER.to_dict()), sm.SchedulerServer)


@pytest.mark.parametrize(
    "call, reply, subcommand, args, result",
    [
        (lambda c: c.status(), {"ok": True}, "status", {}, {"ok": True}),
        (lambda c: c.dialog_data(), {"users": []}, "dialog-data", {}, {"users": []}),
        (lambda c: c.validate_schedule("daily"), {"next": []}, "validate-schedule", {"schedule": "daily"},
         {"next": []}),
        (lambda c: c.list_tasks(), {"tasks": [{"id": "a"}]}, "list-tasks", {}, [{"id": "a"}]),
        (lambda c: c.get_task("a"), {"task": {"id": "a"}}, "get-task", {"id": "a"}, {"id": "a"}),
        (lambda c: c.create_task({"name": "n"}), {"task": {"id": "a"}}, "create-task", {"name": "n"},
         {"id": "a"}),
        (lambda c: c.update_task("a", {"name": "n"}), {"task": {"id": "a"}}, "update-task",
         {"id": "a", "name": "n"}, {"id": "a"}),
        (lambda c: c.set_enabled("a", False), {"task": {"id": "a"}}, "set-enabled",
         {"id": "a", "enabled": False}, {"id": "a"}),
        (lambda c: c.delete_task("a"), {"deleted": True}, "delete-task", {"id": "a"}, {"deleted": True}),
        (lambda c: c.trigger_task("a"), {"triggered": True}, "trigger-task", {"id": "a"}, {"triggered": True}),
        (lambda c: c.list_task_runs("a"), {"runs": []}, "list-task-runs", {"id": "a"}, []),
        (lambda c: c.get_task_logs("a"), {"lines": []}, "get-task-logs", {"id": "a"}, []),
        (lambda c: c.get_task_logs("a", "f" * 32), {"lines": []}, "get-task-logs",
         {"id": "a", "invocation_id": "f" * 32}, []),
        (lambda c: c.list_channels(), {"channels": []}, "list-channels", {}, []),
        (lambda c: c.create_channel("Ops", "webhook", "https://x", {"A": "b"}), {"channel": {"id": "c"}},
         "create-channel", {"name": "Ops", "type": "webhook", "url": "https://x", "headers": {"A": "b"}},
         {"id": "c"}),
        (lambda c: c.create_channel("HC", "healthchecks", "https://hc"), {"channel": {"id": "c"}},
         "create-channel", {"name": "HC", "type": "healthchecks", "url": "https://hc"}, {"id": "c"}),
        (lambda c: c.update_channel("c", "Ops", ""), {"channel": {"id": "c"}}, "update-channel",
         {"id": "c", "name": "Ops", "url": ""}, {"id": "c"}),
        (lambda c: c.delete_channel("c"), {"deleted": True}, "delete-channel", {"id": "c"}, {"deleted": True}),
        (lambda c: c.test_channel("c"), {"ok": True}, "test-channel", {"id": "c"}, {"ok": True}),
        (lambda c: c.export_config(True), {"document": {}}, "export-config", {"include_secrets": True},
         {"document": {}}),
        (lambda c: c.preview_import({"backup": "b.json"}, "skip", {"Ops": "https://x"}, True), {"plan": {"p": 1}},
         "preview-import", {"backup": "b.json", "mode": "skip", "channel_urls": {"Ops": "https://x"},
                            "import_paused": True}, {"p": 1}),
        (lambda c: c.apply_import({"document": {"f": 1}}, "overwrite", {}, False), {"summary": {}},
         "apply-import", {"document": {"f": 1}, "mode": "overwrite", "channel_urls": {}, "import_paused": False},
         {"summary": {}}),
        (lambda c: c.get_backup_settings(), {"count": 0}, "get-backup-settings", {}, {"count": 0}),
        (lambda c: c.set_backup_settings({"enabled": True}), {"count": 0}, "set-backup-settings",
         {"enabled": True}, {"count": 0}),
        (lambda c: c.backup_now(), {"backup": {}}, "backup-now", {}, {"backup": {}}),
        (lambda c: c.list_backups(), {"backups": []}, "list-backups", {}, {"backups": []}),
        (lambda c: c.get_backup("b.json"), {"document": {}}, "get-backup", {"name": "b.json"}, {"document": {}}),
        (lambda c: c.delete_backup("b.json"), {"deleted": True}, "delete-backup", {"name": "b.json"},
         {"deleted": True}),
    ],
)
def test_methods_match_the_cockpit_pages_helper_calls(call, reply, subcommand, args, result):
    conn = _Scripted(reply)
    assert call(conn) == result
    assert conn.calls[0] == (subcommand, args)


def test_helper_errors_are_raised():
    with pytest.raises(sm.SchedulerError, match="Task not found"):
        _Scripted({"error": "Task not found."}).get_task("a")


@pytest.mark.parametrize(
    "expression, kind",
    [
        ("*-*-* *:15:00", "hourly"),
        ("*-*-* 0/6:05:00", "interval"),
        ("*-*-* 02:30:00", "daily"),
        ("Mon,Fri *-*-* 09:30:00", "weekly"),
        ("*-*-07 01:00:00", "monthly"),
    ],
)
def test_presets_round_trip(expression, kind):
    spec = sm.parse_schedule(expression)
    assert spec.kind == kind
    assert sm.serialize_schedule(spec) == expression


@pytest.mark.parametrize(
    "expression",
    ["*-*-* 0/1:00:00", "*-*-* 0/06:00:00", "Fri,Mon *-*-* 09:30:00", "*-*-30 01:00:00", "*:0/15"],
)
def test_non_canonical_expressions_are_custom(expression):
    spec = sm.parse_schedule(expression)
    assert spec.kind == "custom" and spec.expression == expression


def test_systemd_shorthands_and_descriptions():
    assert sm.parse_schedule("daily") == sm.ScheduleSpec("daily", hour=0, minute=0)
    assert sm.describe_schedule("Mon,Fri *-*-* 09:30:00") == "Weekly on Mon, Fri at 09:30"
    assert sm.describe_schedule("*-*-* 0/6:00:00") == "Every 6 hours, at minute 0"
    assert sm.describe_schedule("*:0/15") == "*:0/15"
    assert sm.serialize_schedule(sm.ScheduleSpec("weekly", days=[])) == ""


def test_shebang_helpers():
    assert sm.template_for("/bin/bash") == "#!/bin/bash\nset -euo pipefail\n\n"
    assert sm.template_for("/bin/sh") == "#!/bin/sh\nset -eu\n\n"
    assert sm.shell_for("#!/usr/bin/bash\necho", SHELLS)["path"] == "/bin/bash"
    assert sm.shell_for("#!/usr/bin/env python3\n", SHELLS) is None
    # an untouched template is regenerated for the new shell
    assert sm.change_shell(sm.template_for("/bin/bash"), "/bin/sh", SHELLS) == sm.template_for("/bin/sh")
    # otherwise only the first line changes, keeping a listed shell's argument
    assert sm.change_shell("#!/bin/bash -x\necho hi\n", "/bin/sh", SHELLS) == "#!/bin/sh -x\necho hi\n"
    assert sm.change_shell("#!/usr/bin/env python3\nprint()\n", "/bin/sh", SHELLS) == "#!/bin/sh\nprint()\n"
    assert sm.change_shell("echo hi", "/bin/sh", SHELLS) == "#!/bin/sh\necho hi"


def test_commands_compose_and_split():
    path, args = sm.compose_command("/bin/bash", "/opt/my script.sh", "--fast")
    assert (path, args) == ("/bin/bash", '"/opt/my script.sh" --fast')
    assert sm.split_command(path, args, SHELLS) == ("/bin/bash", "/opt/my script.sh", "--fast")
    assert sm.compose_command("", "/usr/bin/rsync", "-a x y") == ("/usr/bin/rsync", "-a x y")
    assert sm.split_command("/usr/bin/rsync", "-a x y", SHELLS) == ("", "/usr/bin/rsync", "-a x y")


def test_rule_summary_and_run_labels():
    channels = [{"id": "a", "name": "Ops", "type": "webhook"}, {"id": "b", "name": "HC", "type": "healthchecks"}]
    rules = [{"channel_id": "a", "events": ["failure", "missed"], "slug": ""},
             {"channel_id": "b", "events": [], "slug": "x"}, {"channel_id": "gone", "events": [], "slug": ""}]
    assert sm.summarize_rules(rules, channels) == "Ops (failure, missed run), HC (every run)"
    assert sm.run_result_label({"status": "success"}) == "Succeeded"
    assert sm.run_result_label({"status": "failed", "exit_code": 2, "exit_kind": "exited"}) == \
        "Failed (Exit code 2)"
    assert sm.run_result_label({"status": "failed", "exit_code": 9, "exit_kind": "killed"}) == \
        "Failed (Killed by signal 9)"
    assert sm.run_result_label({"status": "failed", "result": "timeout", "exit_code": 15}) == \
        "Failed (Timed out)"
    assert [sm.duration_label(s) for s in (None, 0.05, 3.25, 125)] == ["", "< 0.1 s", "3.2 s", "2 min 5 s"]

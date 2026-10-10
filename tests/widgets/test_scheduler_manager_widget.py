import json

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from it_toolbox.core import remote_helper as rh
from it_toolbox.core import scheduler_manager as sm
from it_toolbox.widgets import remote_helper_widget as rw
from it_toolbox.widgets import scheduler_dialogs as dialogs
from it_toolbox.widgets import scheduler_manager_widget as w

SERVER = sm.SchedulerServer(name="lab", host="lab.lan", username="admin")
SHELLS = [{"name": "bash", "path": "/bin/bash", "aliases": ["/usr/bin/bash"]},
          {"name": "sh", "path": "/bin/sh", "aliases": []}]
CHANNELS = [
    {"id": "c" * 12, "name": "Ops", "type": "webhook", "type_label": "Webhook",
     "destination": "https://hooks.example/…", "header_names": ["Authorization"], "used_by": 1,
     "created_at": ""},
    {"id": "d" * 12, "name": "HC", "type": "healthchecks", "type_label": "Healthchecks.io",
     "destination": "https://hc-ping.com/…", "header_names": [], "used_by": 0, "created_at": ""},
]


def _task(task_id, name, **extra):
    task = {"id": task_id, "name": name, "description": "", "kind": "inline", "command_path": None,
            "command_args": "", "run_as": "root", "schedule": "*-*-* 02:30:00", "timeout_sec": 0, "env": {},
            "working_dir": None, "retries": 0, "retry_delay_sec": 60, "on_failure_task_id": None,
            "enabled": True, "created_at": "", "notify": [], "missed_grace_min": 15, "state": "idle",
            "timer_active": True, "next_run": "2026-10-11T02:30:00+00:00", "last_run": None}
    task.update(extra)
    return task


TASKS = [
    _task("a" * 12, "nightly", description="backs up", env={"GREETING": "hi"},
          notify=[{"channel_id": "c" * 12, "events": ["failure", "missed"], "slug": ""}],
          last_run={"invocation_id": "1" * 32, "started_at": "2026-10-10T02:30:00+00:00", "status": "failed",
                    "result": "exit-code", "exit_code": 3, "exit_kind": "exited", "duration_sec": 1.5,
                    "finished_at": None}),
    _task("b" * 12, "cleanup", kind="path", command_path="/bin/sh", command_args='"/opt/clean.sh" -v',
          schedule="Mon,Fri *-*-* 09:30:00", enabled=False, run_as="alice"),
]
BACKUP = {"name": "cockpit-scheduler-lab-20261010-020000.json", "size": 2048,
          "created_at": "2026-10-10T02:00:00+00:00", "kind": "automatic", "tasks": 2, "channels": 2,
          "host": "lab", "readable": True}


class FakeConnection:
    instances = []
    connect_errors = []
    helper_path = sm.HELPER_PATH

    def __init__(self, server, **credentials):
        self.server = server
        self.credentials = credentials
        self.calls = []
        self.helper_path = type(self).helper_path
        self.tasks = {t["id"]: dict(t) for t in TASKS}
        FakeConnection.instances.append(self)

    def connect(self):
        if FakeConnection.connect_errors:
            raise FakeConnection.connect_errors.pop(0)

    def close(self):
        pass

    def _record(self, *call):
        self.calls.append(call)

    def status(self):
        return {"ok": True, "systemd_version": 257, "timezone": "America/Toronto"}

    def validate_schedule(self, schedule):
        if schedule == "bogus":
            raise rh.RemoteHelperError("Failed to parse calendar specification 'bogus'")
        return {"normalized": schedule, "next": ["Sun 2026-10-11 02:30:00 EDT"]}

    def dialog_data(self):
        return {"users": [{"name": "root"}, {"name": "alice"}], "shells": SHELLS, "channels": CHANNELS}

    def list_tasks(self):
        return [dict(t) for t in self.tasks.values()]

    def get_task(self, task_id):
        task = dict(self.tasks[task_id])
        if task["kind"] == "inline":
            task["script"] = "#!/bin/bash\necho hi\n"
        return task

    def create_task(self, values):
        self._record("create_task", values)
        return values

    def update_task(self, task_id, values):
        self._record("update_task", task_id, values)
        return values

    def set_enabled(self, task_id, enabled):
        self._record("set_enabled", task_id, enabled)
        self.tasks[task_id]["enabled"] = enabled
        return self.tasks[task_id]

    def delete_task(self, task_id):
        self._record("delete_task", task_id)
        del self.tasks[task_id]
        return {"deleted": True}

    def trigger_task(self, task_id):
        self._record("trigger_task", task_id)
        return {"triggered": True}

    def list_task_runs(self, task_id):
        return [TASKS[0]["last_run"]]

    def get_task_logs(self, task_id, invocation_id=None):
        return [{"time": "2026-10-10T02:30:00+00:00", "source": "systemd", "message": "Starting x"},
                {"time": "2026-10-10T02:30:01+00:00", "source": "task", "message": "hello"}]

    def list_channels(self):
        return [dict(c) for c in CHANNELS]

    def create_channel(self, name, channel_type, url, headers=None):
        self._record("create_channel", name, channel_type, url, headers)
        return {}

    def update_channel(self, channel_id, name, url, headers=None):
        self._record("update_channel", channel_id, name, url, headers)
        return {}

    def delete_channel(self, channel_id):
        self._record("delete_channel", channel_id)
        return {"deleted": True}

    def test_channel(self, channel_id):
        self._record("test_channel", channel_id)
        return {"ok": True, "detail": "HTTP 200"}

    def export_config(self, include_secrets):
        self._record("export_config", include_secrets)
        return {"document": {"format": "cockpit-scheduler", "tasks": []}, "filename": "export.json"}

    def preview_import(self, source, mode, channel_urls, import_paused):
        self._record("preview_import", source, mode, channel_urls, import_paused)
        return {"channels": [{"name": "Ops", "type": "webhook", "action": "create", "reason": None,
                              "needs_url": not channel_urls, "warnings": []}],
                "tasks": [{"name": "nightly", "kind": "inline", "run_as": "root", "schedule": "*-*-* 02:30:00",
                           "enabled": True, "action": "update", "reason": None, "warnings": []}],
                "warnings": [], "source": {"host": "lab", "exported_at": None, "secrets_included": False},
                "summary": {"channels": {"create": 1, "update": 0, "skip": 0, "reject": 0},
                            "tasks": {"create": 0, "update": 1, "skip": 0, "reject": 0}}}

    def apply_import(self, source, mode, channel_urls, import_paused):
        self._record("apply_import", source, mode, channel_urls, import_paused)
        return {"results": {"channels": [{"name": "Ops", "status": "created", "reason": None}],
                            "tasks": [{"name": "nightly", "status": "updated", "reason": None, "warnings": []}]},
                "summary": {}}

    def get_backup_settings(self):
        return {"settings": {"enabled": True, "schedule": "*-*-* 04:00:00", "retention": 7,
                             "directory": "/srv/backups"},
                "directory_exists": True, "timer_active": True, "next_run": "2026-10-11T04:00:00+00:00",
                "last_failed": True, "last_error": "disk full", "latest": BACKUP, "count": 1}

    def set_backup_settings(self, settings):
        self._record("set_backup_settings", settings)
        return self.get_backup_settings()

    def backup_now(self):
        self._record("backup_now")
        return {"backup": BACKUP, "removed": []}

    def list_backups(self):
        return {"backups": [BACKUP], "directory": "/srv/backups"}

    def get_backup(self, name):
        return {"name": name, "document": {"format": "cockpit-scheduler"}}

    def delete_backup(self, name):
        self._record("delete_backup", name)
        return {"deleted": True}


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeConnection.instances = []
    FakeConnection.connect_errors = []
    FakeConnection.helper_path = sm.HELPER_PATH


@pytest.fixture
def yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)


def _make(qtbot):
    widget = w.SchedulerManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.task_table.rowCount() == 2 and widget.backup_table.rowCount() == 1)
    qtbot.waitUntil(lambda: "Ops" in widget.task_table.item(0, 6).text())
    return widget


def _select_task(widget, row):
    widget.task_table.selectRow(row)
    return widget.selected_task()


def test_connects_and_lists_tasks_channels_and_backups(qtbot):
    widget = _make(qtbot)

    assert widget.stack.currentWidget() is widget.main_page
    assert "systemd 257" in widget.server_label.text() and "America/Toronto" in widget.server_label.text()
    row = [widget.task_table.item(0, c).text() for c in range(7)]
    assert row[0] == "nightly" and row[1] == "Daily at 02:30"
    assert row[3].startswith("Failed (Exit code 3), ")
    assert row[4:] == ["root", "Yes", "Ops (failure, missed run)"]
    assert widget.task_table.item(0, 0).toolTip() == "backs up"
    # a disabled task has no next run
    assert widget.task_table.item(1, 2).text() == "-"
    assert widget.task_table.item(1, 1).text() == "Weekly on Mon, Fri at 09:30"
    assert widget.channel_table.rowCount() == 2
    assert widget.channel_table.item(0, 2).text() == "https://hooks.example/…"
    assert widget.backup_table.item(0, 1).text() == "Scheduled"
    assert widget.backup_table.item(0, 4).text() == "2.0 KB"
    assert "failed: disk full" in widget.backup_status.text()
    assert widget.backup_settings.settings() == {"enabled": True, "schedule": "*-*-* 04:00:00", "retention": 7,
                                                 "directory": "/srv/backups"}


def test_missing_module_shows_the_install_page(qtbot):
    FakeConnection.helper_path = None
    widget = w.SchedulerManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)

    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.missing_page)
    assert "cockpit-scheduler" in widget.missing_page.text()


def test_prompts_for_sudo_password_and_reconnects(qtbot, monkeypatch):
    FakeConnection.connect_errors = [rh.SudoPasswordRequired()]
    monkeypatch.setattr(rw.QInputDialog, "getText", lambda *a, **k: ("pw", True))
    _make(qtbot)

    assert FakeConnection.instances[-1].credentials == {"sudo_password": "pw"}


def test_task_buttons_follow_the_selection(qtbot):
    widget = _make(qtbot)
    assert not any(b.isEnabled() for b in widget.task_buttons)

    _select_task(widget, 1)

    assert all(b.isEnabled() for b in widget.task_buttons)
    assert widget.task_buttons[2].text() == "Enable"


def test_run_toggle_and_delete(qtbot, yes):
    widget = _make(qtbot)
    connection = widget.connection

    widget.run_task(_select_task(widget, 0))
    widget.toggle_task(_select_task(widget, 1))
    qtbot.waitUntil(lambda: ("set_enabled", "b" * 12, True) in connection.calls)
    widget.delete_task(_select_task(widget, 0))
    qtbot.waitUntil(lambda: widget.task_table.rowCount() == 1)

    assert ("trigger_task", "a" * 12) in connection.calls
    assert ("delete_task", "a" * 12) in connection.calls


def test_edit_task_loads_the_dialog_and_saves(qtbot, monkeypatch):
    widget = _make(qtbot)
    seen = {}

    def accept(dialog):
        seen["dialog"] = dialog
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.TaskDialog, "exec", accept)
    widget.edit_task(_select_task(widget, 0))
    qtbot.waitUntil(lambda: any(c[0] == "update_task" for c in widget.connection.calls))

    dialog = seen["dialog"]
    assert dialog.script.toPlainText() == "#!/bin/bash\necho hi\n"
    assert dialog.on_failure.count() == 2  # Nothing + the other task
    _, task_id, values = next(c for c in widget.connection.calls if c[0] == "update_task")
    assert task_id == "a" * 12
    assert values["env"] == {"GREETING": "hi"}
    assert values["notify"] == [{"channel_id": "c" * 12, "events": ["failure", "missed"], "slug": ""}]
    assert values["schedule"] == "*-*-* 02:30:00"


def test_task_dialog_for_a_program(qtbot):
    data = FakeConnection(SERVER).dialog_data()
    dialog = dialogs.TaskDialog(data, [], dict(TASKS[1]))
    qtbot.addWidget(dialog)

    assert dialog.path_radio.isChecked()
    assert (dialog.command_shell.currentData(), dialog.program.text(), dialog.arguments.text()) == \
        ("/bin/sh", "/opt/clean.sh", "-v")
    assert dialog.schedule.current_kind() == "weekly"
    values = dialog.values()
    assert (values["command_path"], values["command_args"]) == ("/bin/sh", '"/opt/clean.sh" -v')
    assert "script" not in values and values["run_as"] == "alice" and values["enabled"] is False


def test_task_dialog_new_task_defaults_and_shell_menu(qtbot):
    dialog = dialogs.TaskDialog(FakeConnection(SERVER).dialog_data(), [])
    qtbot.addWidget(dialog)

    assert dialog.script.toPlainText() == "#!/bin/bash\nset -euo pipefail\n\n"
    dialog.script_shell.setCurrentIndex(dialog.script_shell.findData("/bin/sh"))
    assert dialog.script.toPlainText() == "#!/bin/sh\nset -eu\n\n"
    dialog.script.setPlainText("#!/usr/bin/env python3\nprint(1)\n")
    assert dialog.script_shell.currentText().startswith("Other (/usr/bin/env python3")
    # alert channels: healthchecks has a check name, a webhook needs an event
    assert dialog.grace_row.isHidden()
    ops = dialog.channel_rows["c" * 12]
    ops["box"].setChecked(True)
    ops["events"]["missed"].setChecked(True)
    assert not dialog.grace_row.isHidden()
    for check in ops["events"].values():
        check.setChecked(False)
    dialog.name.setText("n")
    assert dialog._problem() == "Choose at least one event for Ops, or untick it."
    ops["box"].setChecked(False)
    dialog.channel_rows["d" * 12]["box"].setChecked(True)
    dialog.channel_rows["d" * 12]["slug"].setText("bad slug")
    assert "check name for HC" in dialog._problem()
    dialog.channel_rows["d" * 12]["slug"].setText("my-check")
    dialog.env.setPlainText("1BAD=x")
    assert dialog._problem() == "1BAD isn't a valid environment variable name."
    dialog.env.setPlainText("A=1\nB=two words")
    assert dialog._problem() is None
    assert dialog.values()["notify"] == [{"channel_id": "d" * 12, "events": [], "slug": "my-check"}]
    assert dialog.values()["env"] == {"A": "1", "B": "two words"}


def test_schedule_picker_presets_and_validation(qtbot):
    calls = []

    def validate(expression):
        calls.append(expression)
        return FakeConnection(SERVER).validate_schedule(expression)

    picker = dialogs.SchedulePicker("*-*-* 0/6:15:00", validate)
    qtbot.addWidget(picker)
    assert picker.current_kind() == "interval" and picker.schedule() == "*-*-* 0/6:15:00"
    qtbot.waitUntil(lambda: picker.valid is True)
    assert "Sun 2026-10-11" in picker.preview.text()

    picker.kind.setCurrentIndex(sm.SCHEDULE_KINDS.index("custom"))
    assert picker.expression.text() == "*-*-* 0/6:15:00"  # carried over
    picker.expression.setText("bogus")
    qtbot.waitUntil(lambda: picker.valid is False)
    assert "Invalid schedule" in picker.preview.text()

    picker.kind.setCurrentIndex(sm.SCHEDULE_KINDS.index("weekly"))
    for box in picker.days.values():
        box.setChecked(False)
    assert picker.schedule() == "" and picker.valid is False


def test_runs_dialog_shows_runs_and_log(qtbot):
    connection = FakeConnection(SERVER)
    dialog = w.RunsDialog(connection, TASKS[0])
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: "hello" in dialog.log.toPlainText())
    assert dialog.table.item(0, 2).text() == "Failed (Exit code 3)"
    assert dialog.table.item(0, 1).text() == "1.5 s"
    assert "[systemd] Starting x" in dialog.log.toPlainText()


def test_channel_add_edit_test_delete(qtbot, monkeypatch, yes):
    widget = _make(qtbot)
    connection = widget.connection
    values = iter([
        {"name": "Chat", "type": "googlechat", "url": "https://chat", "headers": None},
        {"name": "Ops", "type": "webhook", "url": "", "headers": {"Authorization": ""}},
    ])
    monkeypatch.setattr(dialogs.ChannelDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(dialogs.ChannelDialog, "values", lambda self: next(values))

    widget.add_channel()
    widget.channel_table.selectRow(0)
    widget.edit_channel(widget.selected_channel())
    widget.test_channel(widget.selected_channel())
    widget.delete_channel(widget.selected_channel())
    qtbot.waitUntil(lambda: any(c[0] == "delete_channel" for c in connection.calls))

    assert ("create_channel", "Chat", "googlechat", "https://chat", None) in connection.calls
    assert ("update_channel", "c" * 12, "Ops", "", {"Authorization": ""}) in connection.calls
    assert ("test_channel", "c" * 12) in connection.calls


def test_channel_dialog_keeps_secrets_on_edit(qtbot):
    dialog = dialogs.ChannelDialog(CHANNELS[0])
    qtbot.addWidget(dialog)

    assert not dialog.type.isEnabled()
    assert "Leave blank to keep" in dialog.url.placeholderText()
    assert dialog.values() == {"name": "Ops", "type": "webhook", "url": "", "headers": {"Authorization": ""}}
    dialog.headers.setPlainText("X: 1\nX: 2")
    with pytest.raises(ValueError, match="listed twice"):
        dialog.header_values()


def test_backup_settings_now_download_and_delete(qtbot, monkeypatch, tmp_path, yes):
    widget = _make(qtbot)
    connection = widget.connection
    target = tmp_path / "backup.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))

    widget.backup_settings.retention.setValue(9)
    widget.save_backup_settings()
    widget.backup_now()
    widget.download_backup(BACKUP["name"])
    widget.delete_backup(BACKUP["name"])
    qtbot.waitUntil(lambda: target.exists() and ("delete_backup", BACKUP["name"]) in connection.calls)

    saved = next(c for c in connection.calls if c[0] == "set_backup_settings")[1]
    assert saved["retention"] == 9 and saved["directory"] == "/srv/backups"
    assert ("backup_now",) in connection.calls
    assert json.loads(target.read_text()) == {"format": "cockpit-scheduler"}


def test_export_writes_the_document(qtbot, monkeypatch, tmp_path):
    widget = _make(qtbot)
    target = tmp_path / "export.json"
    monkeypatch.setattr(dialogs.ExportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))

    widget.export_config()
    qtbot.waitUntil(target.exists)

    assert ("export_config", False) in widget.connection.calls
    assert json.loads(target.read_text())["format"] == "cockpit-scheduler"


def test_import_previews_asks_for_missing_urls_and_applies(qtbot):
    connection = FakeConnection(SERVER)
    dialog = dialogs.ImportDialog(connection, {"document": {"format": "cockpit-scheduler"}}, "f.json")
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: dialog.plan is not None)
    assert "Ops" in dialog.url_fields and not dialog.urls_box.isHidden()
    assert dialog.summary.text() == "Channels: 1 to create  Tasks: 1 to update"
    assert "Update       nightly" in dialog.plan_view.toPlainText()
    assert dialog.apply_button.isEnabled()

    dialog.url_fields["Ops"].setText("https://hooks.example/new")
    dialog.paused.setChecked(True)
    qtbot.waitUntil(lambda: connection.calls[-1][3] == {"Ops": "https://hooks.example/new"})
    qtbot.waitUntil(dialog.apply_button.isEnabled)
    dialog.apply()
    qtbot.waitUntil(lambda: dialog.outcome is not None)

    assert connection.calls[-1] == ("apply_import", {"document": {"format": "cockpit-scheduler"}}, "skip",
                                    {"Ops": "https://hooks.example/new"}, True)
    assert dialogs.describe_outcome(dialog.outcome) == "Channel Ops: Created\nTask nightly: Updated"


def test_restoring_a_backup_overwrites_by_default(qtbot):
    connection = FakeConnection(SERVER)
    dialog = dialogs.ImportDialog(connection, {"backup": BACKUP["name"]}, "backup")
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: dialog.plan is not None)
    assert dialog.windowTitle() == "Restore from Backup"
    assert connection.calls[0][1:3] == ({"backup": BACKUP["name"]}, "overwrite")


def test_parse_pairs():
    assert dialogs.parse_pairs("A=1\n\nB= x ", "=", "NAME=value") == {"A": "1", "B": " x "}
    assert dialogs.parse_pairs("Auth:  Bearer t ", ":", "Name: value") == {"Auth": "Bearer t"}
    with pytest.raises(ValueError, match="isn't NAME=value"):
        dialogs.parse_pairs("nope", "=", "NAME=value")

"""One Scheduler Manager tab (General Tools): manages the automated tasks of
a server running the user's cockpit-scheduler Cockpit module over SSH,
with the same features as that module's page -- tasks (inline scripts or
existing programs on a systemd-timer schedule) with run now, enable and
disable, run history and logs; alert channels; and configuration export,
import and backups. See core/scheduler_manager.py for how it talks to the
server.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import scheduler_manager as sm
from it_toolbox.widgets import scheduler_dialogs as dialogs
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.hosting_dialogs import monospace
from it_toolbox.widgets.hosting_manager_widget import size_label, when_label
from it_toolbox.widgets.remote_helper_widget import (
    Busy,
    RemoteHelperTab,
    fill_table,
    make_table,
    selected_data,
)

TITLE = dialogs.TITLE
# The page's own limit on a configuration file (the helper's MAX_CONFIG_BYTES).
MAX_IMPORT_BYTES = 10 * 1024 * 1024
# How often the task list refreshes itself while it's on screen, so Next
# run / Last run / Running stay current like the Cockpit page's.
AUTO_REFRESH_MS = 15_000


def _button(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(lambda _=False: slot())
    return button


def _row(*widgets: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return layout


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


def last_run_label(task: dict) -> str:
    if task.get("state") == "running":
        return "Running"
    run = task.get("last_run")
    if not run:
        return "No runs yet"
    return f"{sm.run_result_label(run)}, {when_label(run.get('started_at'))}"


def _save_json(parent: QWidget, title: str, filename: str, document: dict) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, str(Path.home() / filename), "JSON files (*.json)")
    if not path:
        return None
    Path(path).write_text(json.dumps(document, indent=2) + "\n")
    return path


# -- Run history ---------------------------------------------------------------------


class RunsDialog(QDialog):
    """A task's run history, with the selected run's log underneath (the
    page's TaskRunsDialog)."""

    COLUMNS = ("Started", "Duration", "Result")

    def __init__(self, connection: sm.SchedulerConnection, task: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self.task = task
        self.busy = Busy(self, TITLE)
        self.setWindowTitle(f"Run History — {task['name']}")
        self.resize(820, 620)
        self.runs: list[dict] = []
        self.table = make_table(list(self.COLUMNS))
        self.table.itemSelectionChanged.connect(self._load_log)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(monospace())
        self.log.setPlaceholderText("Select a run to see its log.")
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.log)
        splitter.setSizes([220, 380])
        layout = QVBoxLayout(self)
        layout.addLayout(_row(_button("Refresh", self.refresh), _button("Save Log…", self.save_log),
                              _button("Close", self.accept)))
        layout.addWidget(splitter, 1)
        self.refresh()

    def refresh(self) -> None:
        task_id = self.task["id"]
        self.busy("Loading run history…", lambda: self._connection.list_task_runs(task_id), self.show_runs)

    def show_runs(self, runs: list[dict]) -> None:
        selected = selected_data(self.table)
        self.runs = runs
        rows = [[when_label(r.get("started_at")), sm.duration_label(r.get("duration_sec")),
                 sm.run_result_label(r)] for r in runs]
        fill_table(self.table, rows, [r["invocation_id"] for r in runs])
        if not runs:
            self.log.setPlainText("No runs yet.")
            return
        ids = [r["invocation_id"] for r in runs]
        self.table.selectRow(ids.index(selected) if selected in ids else 0)

    def _load_log(self) -> None:
        invocation_id = selected_data(self.table)
        if not invocation_id:
            return
        task_id = self.task["id"]
        self.busy("Loading log…", lambda: self._connection.get_task_logs(task_id, invocation_id),
                  lambda lines: self._show_log(invocation_id, lines))

    def _show_log(self, invocation_id: str, lines: list[dict]) -> None:
        if selected_data(self.table) != invocation_id:
            return
        self.log.setPlainText(self.format_log(lines) or "No log output was recorded for this run.")

    @staticmethod
    def format_log(lines: list[dict]) -> str:
        out = []
        for line in lines:
            prefix = "[systemd] " if line.get("source") == "systemd" else ""
            out.append(f"{when_label(line.get('time'))}  {prefix}{line.get('message', '')}")
        return "\n".join(out)

    def save_log(self) -> None:
        text = self.log.toPlainText()
        invocation_id = selected_data(self.table)
        if not invocation_id or not text:
            return
        run = next((r for r in self.runs if r["invocation_id"] == invocation_id), {})
        stamp = when_label(run.get("started_at")).replace(" ", "_").replace(":", "")
        default = Path.home() / f"{self.task['name']}-{stamp}.log"
        path, _ = QFileDialog.getSaveFileName(self, "Save Log", str(default), "Log files (*.log *.txt)")
        if path:
            Path(path).write_text(text + "\n")


# -- The manager tab ---------------------------------------------------------------------


class SchedulerManagerWidget(RemoteHelperTab):
    """Connects on construction, then shows the management tabs, or a
    page explaining that cockpit-scheduler isn't installed."""

    TOOL_NAME = TITLE
    TASK_COLUMNS = ("Name", "Schedule", "Next run", "Last run", "Runs as", "Enabled", "Alerts")
    CHANNEL_COLUMNS = ("Name", "Type", "Destination", "Used by")
    BACKUP_COLUMNS = ("Created", "Kind", "Tasks", "Channels", "Size", "File")

    def __init__(self, server: sm.SchedulerServer, connection_factory=sm.SchedulerConnection,
                 parent: QWidget | None = None) -> None:
        super().__init__(server, connection_factory, parent)
        self.tasks: list[dict] = []
        self.channels: list[dict] = []
        self.backups: list[dict] = []
        self._loading_tasks = False

        self.missing_page = QLabel(
            "This server doesn't have the cockpit-scheduler module "
            f"({sm.HELPER_PATH}).\n\nInstall the cockpit-scheduler package (the RPM on its GitHub "
            "release page), then click Reconnect."
        )
        self.missing_page.setWordWrap(True)
        self.missing_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.missing_page)

        self.server_label = QLabel()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tasks_tab(), "Tasks")
        self.tabs.addTab(self._build_channels_tab(), "Notification Channels")
        self.tabs.addTab(self._build_backups_tab(), "Backup && Restore")
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self.server_label)
        page_layout.addWidget(self.tabs, 1)
        self.main_page = page
        self.stack.addWidget(page)

        self._auto_refresh = QTimer(self)
        self._auto_refresh.setInterval(AUTO_REFRESH_MS)
        self._auto_refresh.timeout.connect(self._tick)

        self.connect_to_server()

    def flash(self, message: str) -> None:
        status_bar.begin(self, message).finish(message)

    def validate_schedule(self, expression: str) -> dict:
        """Blocking; handed to the schedule pickers."""
        return self.connection.validate_schedule(expression)

    # -- Connecting --------------------------------------------------------------

    def before_reconnect(self) -> None:
        self._auto_refresh.stop()

    def on_connected(self) -> None:
        if self.connection.helper_path is None:
            self.stack.setCurrentWidget(self.missing_page)
            return
        self.show_message("Reading the server's status…")
        self.busy("Reading cockpit-scheduler status…", self.connection.status, self._on_first_status)

    def _on_first_status(self, status: dict) -> None:
        version = status.get("systemd_version")
        self.server_label.setText(
            f"systemd {version or '?'} · server time zone {status.get('timezone') or '?'} "
            "· times below are shown in your local time"
        )
        self.stack.setCurrentWidget(self.main_page)
        self.refresh_tasks()
        self.refresh_channels()
        self.refresh_backups()
        self._auto_refresh.start()

    def _tick(self) -> None:
        if self.connection is not None and self.isVisible() and self.tabs.currentIndex() == 0:
            self.refresh_tasks(quiet=True)

    # -- Tasks ---------------------------------------------------------------------

    def _build_tasks_tab(self) -> QWidget:
        page = QWidget()
        self.task_table = make_table(list(self.TASK_COLUMNS))
        self.task_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_table.customContextMenuRequested.connect(self._tasks_menu)
        self.task_table.doubleClicked.connect(lambda _: self.edit_task(self.selected_task()))
        self.task_table.itemSelectionChanged.connect(self._sync_task_buttons)
        self.task_buttons = [
            _button("Run Now", lambda: self.run_task(self.selected_task())),
            _button("Edit…", lambda: self.edit_task(self.selected_task())),
            _button("Enable/Disable", lambda: self.toggle_task(self.selected_task())),
            _button("Run History…", lambda: self.show_runs(self.selected_task())),
            _button("Delete", lambda: self.delete_task(self.selected_task())),
        ]
        layout = QVBoxLayout(page)
        layout.addLayout(_row(_button("Create Task…", self.create_task), _button("Refresh", self.refresh_tasks),
                              *self.task_buttons))
        layout.addWidget(self.task_table, 1)
        self._sync_task_buttons()
        return page

    def selected_task(self) -> dict | None:
        task_id = selected_data(self.task_table)
        return next((t for t in self.tasks if t["id"] == task_id), None)

    def _sync_task_buttons(self) -> None:
        task = self.selected_task()
        for button in self.task_buttons:
            button.setEnabled(task is not None)
        if task is not None:
            self.task_buttons[0].setEnabled(task.get("state") != "running")
            self.task_buttons[2].setText("Disable" if task.get("enabled") else "Enable")

    def refresh_tasks(self, quiet: bool = False) -> None:
        if self._loading_tasks:
            return
        self._loading_tasks = True

        def done(tasks):
            self._loading_tasks = False
            self.show_tasks(tasks)

        def failed(_error):
            self._loading_tasks = False

        if quiet:
            async_utils.run_in_background(self.connection.list_tasks, on_result=lambda t: _safe(done, t),
                                          on_error=lambda e: _safe(failed, e))
        else:
            self.busy("Loading tasks…", self.connection.list_tasks, done, on_error=failed)

    def _task_row(self, task: dict) -> list:
        next_run = when_label(task.get("next_run")) if task.get("enabled") and task.get("next_run") else "-"
        return [task["name"], sm.describe_schedule(task.get("schedule") or ""), next_run, last_run_label(task),
                task.get("run_as", ""), "Yes" if task.get("enabled") else "No",
                sm.summarize_rules(task.get("notify") or [], self.channels)]

    def show_tasks(self, tasks: list[dict]) -> None:
        selected = selected_data(self.task_table)
        self.tasks = tasks
        self.task_table.blockSignals(True)
        fill_table(self.task_table, [self._task_row(t) for t in tasks], [t["id"] for t in tasks])
        for row, task in enumerate(tasks):
            if task.get("description"):
                self.task_table.item(row, 0).setToolTip(task["description"])
        ids = [t["id"] for t in tasks]
        if selected in ids:
            self.task_table.selectRow(ids.index(selected))
        self.task_table.blockSignals(False)
        self._sync_task_buttons()

    def _tasks_menu(self, pos) -> None:
        task = self.selected_task()
        menu = QMenu(self)
        if task is not None:
            run = menu.addAction("Run Now")
            run.setEnabled(task.get("state") != "running")
            run.triggered.connect(lambda: self.run_task(task))
            menu.addAction("Edit…").triggered.connect(lambda: self.edit_task(task))
            menu.addAction("Disable" if task.get("enabled") else "Enable").triggered.connect(
                lambda: self.toggle_task(task))
            menu.addAction("Run History and Logs…").triggered.connect(lambda: self.show_runs(task))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(lambda: self.delete_task(task))
            menu.addSeparator()
        menu.addAction("Create Task…").triggered.connect(self.create_task)
        menu.exec(self.task_table.viewport().mapToGlobal(pos))

    def _open_task_dialog(self, task: dict | None) -> None:
        """Loads dialog-data (and the task itself, for an edit) in one
        background call, then shows the dialog and saves it."""
        connection = self.connection
        task_id = task["id"] if task else None

        def load():
            data = connection.dialog_data()
            return data, connection.get_task(task_id) if task_id else None

        def show(result):
            data, full_task = result
            others = [t for t in self.tasks if t["id"] != task_id]
            dialog = dialogs.TaskDialog(data, others, full_task, self.validate_schedule, parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            values = dialog.values()
            if task_id:
                self.busy(f"Saving {values['name']}…", lambda: connection.update_task(task_id, values),
                          self._after_task_change, done_message="Saved")
            else:
                self.busy(f"Creating {values['name']}…", lambda: connection.create_task(values),
                          self._after_task_change, done_message="Task created")

        self.busy("Loading…", load, show)

    def create_task(self) -> None:
        self._open_task_dialog(None)

    def edit_task(self, task: dict | None) -> None:
        if task is not None:
            self._open_task_dialog(task)

    def _after_task_change(self, _=None) -> None:
        self.refresh_tasks()
        self.refresh_channels()  # "Used by" counts

    def run_task(self, task: dict | None) -> None:
        if task is None:
            return
        task_id = task["id"]

        def started(_):
            self.flash(f"Started {task['name']} — check its run history for progress.")
            self.refresh_tasks()
            QTimer.singleShot(3000, lambda: self.connection is not None and self.refresh_tasks(quiet=True))

        self.busy(f"Starting {task['name']}…", lambda: self.connection.trigger_task(task_id), started)

    def toggle_task(self, task: dict | None) -> None:
        if task is None:
            return
        enabled = not task.get("enabled")
        task_id = task["id"]
        self.busy(f"{'Enabling' if enabled else 'Disabling'} {task['name']}…",
                  lambda: self.connection.set_enabled(task_id, enabled), self._after_task_change)

    def delete_task(self, task: dict | None) -> None:
        if task is None or not _confirm(
                self, "Delete Task", f"Delete task {task['name']}? This also removes its systemd timer and script."):
            return
        task_id = task["id"]
        self.busy(f"Deleting {task['name']}…", lambda: self.connection.delete_task(task_id),
                  self._after_task_change, done_message="Task deleted")

    def show_runs(self, task: dict | None) -> None:
        if task is not None:
            RunsDialog(self.connection, task, parent=self).exec()

    # -- Notification channels ---------------------------------------------------------

    def _build_channels_tab(self) -> QWidget:
        page = QWidget()
        self.channel_table = make_table(list(self.CHANNEL_COLUMNS))
        self.channel_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_table.customContextMenuRequested.connect(self._channels_menu)
        self.channel_table.doubleClicked.connect(lambda _: self.edit_channel(self.selected_channel()))
        layout = QVBoxLayout(page)
        note = QLabel("Channels are where alerts are sent: a webhook, a Google Chat space or a Healthchecks.io "
                      "project. Set one up here, then pick it, and the events you care about, in each task's "
                      "Alerts tab.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addLayout(_row(
            _button("Add Channel…", self.add_channel),
            _button("Edit…", lambda: self.edit_channel(self.selected_channel())),
            _button("Send Test Alert", lambda: self.test_channel(self.selected_channel())),
            _button("Delete", lambda: self.delete_channel(self.selected_channel())),
            _button("Refresh", self.refresh_channels),
        ))
        layout.addWidget(self.channel_table, 1)
        return page

    def selected_channel(self) -> dict | None:
        channel_id = selected_data(self.channel_table)
        return next((c for c in self.channels if c["id"] == channel_id), None)

    def refresh_channels(self) -> None:
        self.busy("Loading notification channels…", self.connection.list_channels, self.show_channels)

    def show_channels(self, channels: list[dict]) -> None:
        self.channels = channels
        rows = [[c["name"], c.get("type_label") or sm.CHANNEL_TYPE_LABELS.get(c["type"], c["type"]),
                 c.get("destination", ""), c.get("used_by", 0)] for c in channels]
        fill_table(self.channel_table, rows, [c["id"] for c in channels])
        # the task list's Alerts column names channels
        if self.tasks:
            self.show_tasks(self.tasks)

    def _channels_menu(self, pos) -> None:
        channel = self.selected_channel()
        menu = QMenu(self)
        if channel is not None:
            menu.addAction("Edit…").triggered.connect(lambda: self.edit_channel(channel))
            menu.addAction("Send Test Alert").triggered.connect(lambda: self.test_channel(channel))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(lambda: self.delete_channel(channel))
            menu.addSeparator()
        menu.addAction("Add Channel…").triggered.connect(self.add_channel)
        menu.exec(self.channel_table.viewport().mapToGlobal(pos))

    def _after_channel_change(self, _=None) -> None:
        self.refresh_channels()
        self.refresh_tasks()

    def add_channel(self) -> None:
        dialog = dialogs.ChannelDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        v = dialog.values()
        self.busy(f"Adding {v['name']}…",
                  lambda: self.connection.create_channel(v["name"], v["type"], v["url"], v["headers"]),
                  self._after_channel_change, done_message="Channel added")

    def edit_channel(self, channel: dict | None) -> None:
        if channel is None:
            return
        dialog = dialogs.ChannelDialog(channel, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        v = dialog.values()
        channel_id = channel["id"]
        self.busy(f"Saving {v['name']}…",
                  lambda: self.connection.update_channel(channel_id, v["name"], v["url"], v["headers"]),
                  self._after_channel_change, done_message="Saved")

    def test_channel(self, channel: dict | None) -> None:
        if channel is None:
            return
        channel_id = channel["id"]

        def sent(result: dict) -> None:
            QMessageBox.information(self, TITLE, f"Test alert sent to {channel['name']} ({result.get('detail', 'OK')}).")

        self.busy(f"Sending a test alert to {channel['name']}…", lambda: self.connection.test_channel(channel_id), sent)

    def delete_channel(self, channel: dict | None) -> None:
        if channel is None:
            return
        used_by = channel.get("used_by", 0)
        text = f"Delete channel {channel['name']}?"
        if used_by:
            text += f" {used_by} task(s) currently alert through it and will stop doing so."
        if not _confirm(self, "Delete Channel", text):
            return
        channel_id = channel["id"]
        self.busy(f"Deleting {channel['name']}…", lambda: self.connection.delete_channel(channel_id),
                  self._after_channel_change, done_message="Channel deleted")

    # -- Backup & restore ------------------------------------------------------------------

    def _build_backups_tab(self) -> QWidget:
        page = QWidget()
        intro = QLabel("Export saves every task and notification channel to a file, to keep or to move to another "
                       "server; import previews what a file would change before anything is touched. Backups do "
                       "the same automatically, on a schedule, into a folder on the server.")
        intro.setWordWrap(True)
        self.backup_settings = dialogs.BackupSettingsBox(self.validate_schedule)
        self.backup_status = QLabel()
        self.backup_status.setWordWrap(True)
        self.backup_table = make_table(list(self.BACKUP_COLUMNS))
        self.backup_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.backup_table.customContextMenuRequested.connect(self._backups_menu)

        layout = QVBoxLayout(page)
        layout.addWidget(intro)
        layout.addLayout(_row(_button("Export Configuration…", self.export_config),
                              _button("Import Configuration…", self.import_config)))
        layout.addWidget(self.backup_settings)
        layout.addLayout(_row(_button("Save Settings", self.save_backup_settings),
                              _button("Back Up Now", self.backup_now)))
        layout.addWidget(self.backup_status)
        layout.addLayout(_row(
            QLabel("Backups on the server:"),
            _button("Download…", lambda: self.download_backup(selected_data(self.backup_table))),
            _button("Restore…", lambda: self.restore_backup(selected_data(self.backup_table))),
            _button("Delete", lambda: self.delete_backup(selected_data(self.backup_table))),
            _button("Refresh", self.refresh_backups),
        ))
        layout.addWidget(self.backup_table, 1)
        return page

    def refresh_backups(self) -> None:
        connection = self.connection

        def load():
            status = connection.get_backup_settings()
            try:
                listing = connection.list_backups()
            except sm.SchedulerError:
                listing = {"backups": []}  # e.g. the directory doesn't exist yet
            return status, listing

        self.busy("Loading backups…", load, lambda result: self.show_backups(*result))

    def show_backups(self, status: dict, listing: dict) -> None:
        self.backup_settings.set_settings(status.get("settings") or {})
        self.show_backup_status(status)
        self.backups = listing.get("backups", [])
        rows = [[when_label(b.get("created_at")),
                 {"manual": "Manual", "automatic": "Scheduled"}.get(b.get("kind"), "") if b.get("readable", True)
                 else "Unreadable",
                 "" if b.get("tasks") is None else b["tasks"], "" if b.get("channels") is None else b["channels"],
                 size_label(b.get("size")), b["name"]] for b in self.backups]
        fill_table(self.backup_table, rows, [b["name"] for b in self.backups])

    def show_backup_status(self, status: dict) -> None:
        lines = []
        if status.get("last_failed"):
            reason = status.get("last_error") or "see the journal for cockpit-scheduler-backup.service."
            lines.append(f"⚠ The last scheduled backup failed: {reason}")
        settings = status.get("settings") or {}
        if settings.get("enabled"):
            next_run = when_label(status.get("next_run"))
            lines.append("Automatic backups are on." + (f" Next backup: {next_run}." if next_run else ""))
        else:
            lines.append("Automatic backups are off.")
        latest = status.get("latest")
        lines.append(f"Latest backup: {when_label(latest.get('created_at'))}." if latest
                     else "No backup has been made yet.")
        lines.append("Backups contain everything needed to restore, including secrets (channel URLs, header and "
                     "environment variable values), and are readable by root only. Keep a copy off the server "
                     "too.")
        self.backup_status.setText("\n".join(lines))

    def save_backup_settings(self) -> None:
        settings = self.backup_settings.settings()
        if not settings["directory"].startswith("/"):
            QMessageBox.warning(self, TITLE, "The backup directory must be an absolute path.")
            return
        if not settings["schedule"]:
            QMessageBox.warning(self, TITLE, self.backup_settings.schedule.preview.text())
            return
        self.busy("Saving backup settings…", lambda: self.connection.set_backup_settings(settings),
                  lambda _: self.refresh_backups(), done_message="Saved")

    def backup_now(self) -> None:
        def done(result: dict) -> None:
            self.flash(f"Backup written: {result['backup']['name']}")
            self.refresh_backups()

        self.busy("Backing up…", self.connection.backup_now, done)

    def _backups_menu(self, pos) -> None:
        name = selected_data(self.backup_table)
        if name is None:
            return
        menu = QMenu(self)
        menu.addAction("Download…").triggered.connect(lambda: self.download_backup(name))
        menu.addAction("Restore…").triggered.connect(lambda: self.restore_backup(name))
        menu.addSeparator()
        menu.addAction("Delete").triggered.connect(lambda: self.delete_backup(name))
        menu.exec(self.backup_table.viewport().mapToGlobal(pos))

    def download_backup(self, name: str | None) -> None:
        if not name:
            return

        def save(result: dict) -> None:
            path = _save_json(self, "Download Backup", name, result["document"])
            if path:
                self.flash(f"Saved {Path(path).name} — it includes secrets: keep it private.")

        self.busy(f"Downloading {name}…", lambda: self.connection.get_backup(name), save)

    def restore_backup(self, name: str | None) -> None:
        if name:
            self._run_import({"backup": name}, f"Backup: {name}")

    def delete_backup(self, name: str | None) -> None:
        if not name or not _confirm(self, "Delete Backup", f"Delete backup {name}? This can't be undone."):
            return
        self.busy(f"Deleting {name}…", lambda: self.connection.delete_backup(name),
                  lambda _: self.refresh_backups(), done_message="Backup deleted")

    def export_config(self) -> None:
        dialog = dialogs.ExportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        include_secrets = dialog.include_secrets.isChecked()

        def save(result: dict) -> None:
            path = _save_json(self, "Export Configuration", result["filename"], result["document"])
            if path:
                self.flash(f"Exported to {Path(path).name}, "
                           + ("including secrets: keep it private." if include_secrets else "without secrets."))

        self.busy("Exporting…", lambda: self.connection.export_config(include_secrets), save)

    def import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Configuration", str(Path.home()),
                                              "JSON files (*.json);;All files (*)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > MAX_IMPORT_BYTES:
                raise ValueError("the file is larger than 10 MB")
            document = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, TITLE, f"That file couldn't be read: {exc}")
            return
        self._run_import({"document": document}, Path(path).name)

    def _run_import(self, source: dict, label: str) -> None:
        dialog = dialogs.ImportDialog(self.connection, source, label, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.outcome is None:
            return
        QMessageBox.information(self, "Import Finished", dialogs.describe_outcome(dialog.outcome))
        self.refresh_tasks()
        self.refresh_channels()


def _safe(fn, value) -> None:
    try:
        fn(value)
    except RuntimeError:
        pass  # widget closed while the call was running

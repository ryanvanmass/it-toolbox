"""Backups in the Hosting Manager, as on the cockpit-hosting page: the
server-wide Backups tab (where backups go, when, how many are kept,
recent runs) and each site's Backups sub-tab (its own schedule, its
snapshots, restoring one). Backups are restic snapshots on an rclone
remote, made and restored by the helper in units of their own, so both
views poll the status while something runs."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import hosting_manager as hm
from it_toolbox.widgets import hosting_dialogs as dialogs
from it_toolbox.widgets.remote_helper_widget import (
    fill_table,
    make_table,
    selected_data,
)

POLL_MS = 3000


def when(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M")


def run_state(run: dict) -> str:
    return {"running": "Running…", "failed": "Failed", "done": "Done"}.get(run.get("state"), run.get("state") or "")


def fill_runs(table, runs: list[dict], domains: dict[str, str] | None = None) -> None:
    rows = []
    for run in runs:
        row = [when(run.get("started_at"))]
        if domains is not None:
            row.append(domains.get(run.get("site") or "", run.get("site") or ""))
        state = run_state(run) + (f": {run['failure']}" if run.get("failure") else "")
        rows.append([*row, hm.backup_run_label(run), state])
    fill_table(table, rows)


def site_mode_text(mode: str, schedule: str | None, server_enabled: bool = True) -> str:
    if mode == "off":
        return "Off"
    if mode == "custom":
        return f"Own schedule: {hm.schedule_label(schedule or '')}"
    return "Server's schedule" if server_enabled else "Off (server's schedule is off)"


def _busy(backup: dict) -> bool:
    return bool(backup.get("running") or backup.get("busy_sites")
                or any(run.get("state") == "running" for run in backup.get("runs") or []))


def _quietly(fn, on_result) -> None:
    def deliver(result) -> None:
        try:
            on_result(result)
        except RuntimeError:
            pass

    async_utils.run_in_background(fn, on_result=deliver, on_error=lambda _error: None)


class PasswordDialog(QDialog):
    def __init__(self, password: str, is_new: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Encryption Password")
        self.setMinimumWidth(480)
        text = ("The backup destination is ready. " if is_new else "") + (
            "Backups are encrypted with this password. Keep a copy somewhere other than this server: without it, "
            "nobody can restore them if the server is lost.")
        label = QLabel(text)
        label.setWordWrap(True)
        value = QLineEdit(password)
        value.setReadOnly(True)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda _=False: QGuiApplication.clipboard().setText(password))
        close = QPushButton("Done")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(value, 1)
        row.addWidget(copy)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addLayout(row)
        layout.addWidget(close)


class BackupsTab(QWidget):
    """The server's Backups tab."""

    def __init__(self, manager) -> None:
        super().__init__()
        self.manager = manager
        self.backup: dict = {}
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.install_button = self._button("Install restic and rclone", self._install)
        self.setup_button = self._button("Set Up Backups…", self._edit_destination)
        self.now_button = self._button("Back Up Now", self._backup_now)
        self.schedule_button = self._button("Schedule…", self._edit_settings)
        self.destination_button = self._button("Destination…", self._edit_destination)
        self.password_button = self._button("Show Password…", self._show_password)
        self.sites_table = make_table(["Site", "Backups", "Last backup"])
        self.sites_table.doubleClicked.connect(lambda _: self._open_site())
        self.runs_table = make_table(["Started", "Site", "What", "State"])
        self.tables = QSplitter(Qt.Orientation.Vertical)
        for title, table in (("Sites (double-click to open)", self.sites_table), ("Recent activity", self.runs_table)):
            box = QGroupBox(title)
            QVBoxLayout(box).addWidget(table)
            self.tables.addWidget(box)
        buttons = QHBoxLayout()
        for button in (self.install_button, self.setup_button, self.now_button, self.schedule_button,
                       self.destination_button, self.password_button, self._button("Refresh", self.refresh)):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addLayout(buttons)
        layout.addWidget(self.tables, 1)
        self._poll = QTimer(self)
        self._poll.setSingleShot(True)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(lambda: _quietly(self.manager.connection.backup_status, self.show_backup))

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda _=False: slot())
        return button

    def stop(self) -> None:
        self._poll.stop()

    def refresh(self) -> None:
        self.manager.busy("Loading backups…", self.manager.connection.backup_status, self.show_backup)

    def _domains(self) -> dict[str, str]:
        return {site["name"]: site.get("primary_domain") or site["name"] for site in self.manager.sites}

    def show_backup(self, backup: dict) -> None:
        self.backup = backup
        installed = bool(backup.get("installed"))
        destination = backup.get("destination")
        ready = installed and bool(destination)
        status = self.manager.server_status
        self.install_button.setVisible(not installed)
        self.install_button.setEnabled(bool(status.get("supported", True)) and not status.get("usr_readonly"))
        self.setup_button.setVisible(installed and not destination)
        for button in (self.now_button, self.schedule_button, self.destination_button, self.password_button):
            button.setVisible(ready)
        self.now_button.setEnabled(not backup.get("running"))
        self.tables.setVisible(ready)
        if not installed:
            self.info.setText("Back up every site's files and databases to Google Drive, S3, SFTP or another disk, "
                              "on a schedule, and restore any site to how it was at any backup. restic and rclone "
                              "are not installed on this server.")
        elif not destination:
            self.info.setText("Choose where backups go: a Google shared drive, S3, an SFTP server or a folder on "
                              "another disk. They are encrypted before they leave the server.")
        else:
            keep = backup.get("keep") or {}
            lines = [
                (f"Destination: {hm.BACKUP_KIND_LABELS.get(destination.get('kind'), destination.get('kind'))}  "
                 f"{hm.backup_destination_text(destination)}"),
                "Scheduled backups: " + (hm.schedule_label(backup.get("schedule") or "")
                                         + (f" (next: {backup['next_run']})" if backup.get("next_run") else "")
                                         if backup.get("enabled") else "Off"),
                f"Keep: {keep.get('daily', 0)} daily, {keep.get('weekly', 0)} weekly, {keep.get('monthly', 0)} monthly",
                "Alerts: " + ("When a backup fails" if backup.get("alerts") else "Off"),
            ]
            failure = backup.get("alert_failure")
            if failure:
                lines.append(f"Last alert failed ({when(failure.get('at'))}): {failure.get('message')}")
            failed = self.failed_sites()
            if failed:
                domains = self._domains()
                lines.append("The last backup failed for: " + ", ".join(domains.get(n, n) for n in failed))
            self.info.setText("\n".join(lines))
            domains = self._domains()
            sites = backup.get("sites") or []
            fill_table(self.sites_table, [
                [domains.get(s["name"], s["name"]),
                 site_mode_text(s.get("mode") or "global", s.get("schedule"), bool(backup.get("enabled"))),
                 (when(s.get("last_backup")) or "Never") + (" — last one failed" if s["name"] in failed else "")]
                for s in sites
            ], [s["name"] for s in sites])
            fill_runs(self.runs_table, backup.get("runs") or [], domains)
        if _busy(backup):
            self._poll.start()

    def failed_sites(self) -> list[str]:
        failed = []
        runs = self.backup.get("runs") or []
        for site in self.backup.get("sites") or []:
            last = next((r for r in runs if r.get("site") == site["name"] and r.get("kind") == "backup"
                         and r.get("state") != "running"), None)
            if last and last.get("state") == "failed":
                failed.append(site["name"])
        return failed

    def _open_site(self) -> None:
        name = selected_data(self.sites_table)
        if name:
            self.manager.open_site(name, "backups")

    def _install(self) -> None:
        def done(_):
            self.manager.refresh_status()
            self.refresh()

        self.manager.busy("Installing restic and rclone (this can take several minutes)…",
                          lambda: self.manager.connection.stack_install(["backup"], []), done, "Installed")

    def _edit_destination(self) -> None:
        dialog = dialogs.BackupDestinationDialog(self.backup, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination, password = dialog.destination(), dialog.password.text()

        def done(reply: dict) -> None:
            self.show_backup(reply)
            if reply.get("repository") == "created":
                self._show_password(is_new=True)

        self.manager.busy("Connecting to the backup destination…",
                          lambda: self.manager.connection.backup_destination(destination, password), done, "Saved")

    def _edit_settings(self) -> None:
        dialog = dialogs.BackupSettingsDialog(self.backup, self.manager.connection.schedule_check, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = dialog.settings()
        self.manager.busy("Saving the backup schedule…", lambda: self.manager.connection.backup_settings(settings),
                          self.show_backup, "Saved")

    def _show_password(self, is_new: bool = False) -> None:
        self.manager.busy("Reading the encryption password…", self.manager.connection.backup_password,
                          lambda password: PasswordDialog(password, is_new, self).exec())

    def _backup_now(self) -> None:
        self.manager.busy("Starting backups of all sites…", lambda: self.manager.connection.backup_now(),
                          lambda reply: self.show_backup({**reply, "running": True}), "Backups started")


class SiteBackupsPanel(QWidget):
    """A site's Backups sub-tab. `load()` reads the server's backup status
    and, once backups are set up, the site's snapshots."""

    def __init__(self, detail) -> None:
        super().__init__()
        self.detail = detail
        self.backup: dict = {}
        self.snapshots: list[dict] = []
        self.loaded_for: str | None = None
        self.not_ready = QLabel("Backups aren't set up. Set up where backups go on the Backups tab first.")
        self.not_ready.setWordWrap(True)
        self.modes: dict[str, QRadioButton] = {}
        modes = QVBoxLayout()
        for mode, label in hm.BACKUP_MODES:
            button = QRadioButton(label)
            self.modes[mode] = button
            button.toggled.connect(self._mode_changed)
            modes.addWidget(button)
        self.schedule = dialogs.ScheduleEdit("0 2 * * *", None, hm.BACKUP_SCHEDULE_PRESETS,
                                             next_label="Next backup")
        self.now_button = self._button("Back Up Now", self._backup_now)
        form = QFormLayout()
        form.addRow("Back up:", modes)
        form.addRow("When:", self.schedule)
        self.schedule_form = form
        schedule_box = QGroupBox("Schedule")
        schedule_layout = QVBoxLayout(schedule_box)
        schedule_layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(self._button("Save", self._save))
        row.addWidget(self.now_button)
        row.addStretch(1)
        schedule_layout.addLayout(row)
        self.snapshots_table = make_table(["Taken", "Snapshot", "Size"])
        self.snapshots_table.doubleClicked.connect(lambda _: self._restore())
        self.snapshot_note = QLabel()
        self.snapshot_note.setWordWrap(True)
        snapshots_box = QGroupBox("Snapshots")
        snapshots_layout = QVBoxLayout(snapshots_box)
        row = QHBoxLayout()
        row.addWidget(self._button("Restore…", self._restore))
        row.addWidget(self._button("Refresh", self.load_snapshots))
        row.addStretch(1)
        snapshots_layout.addLayout(row)
        snapshots_layout.addWidget(self.snapshot_note)
        snapshots_layout.addWidget(self.snapshots_table)
        self.runs_table = make_table(["Started", "What", "State"])
        runs_box = QGroupBox("Recent activity")
        QVBoxLayout(runs_box).addWidget(self.runs_table)
        self.ready_area = QWidget()
        ready = QVBoxLayout(self.ready_area)
        ready.setContentsMargins(0, 0, 0, 0)
        ready.addWidget(schedule_box)
        ready.addWidget(snapshots_box, 2)
        ready.addWidget(runs_box, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.not_ready)
        layout.addWidget(self.ready_area, 1)
        self._poll = QTimer(self)
        self._poll.setSingleShot(True)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_status)
        self._was_busy = False

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda _=False: slot())
        return button

    @property
    def connection(self) -> hm.HostingConnection:
        return self.detail.connection

    def clear(self) -> None:
        self._poll.stop()
        self.loaded_for = None
        self.snapshots = []
        self.snapshots_table.setRowCount(0)
        self.runs_table.setRowCount(0)

    def load(self) -> None:
        name = self.detail.name
        if not name:
            return
        self.loaded_for = name
        self.schedule._checker = self.connection.schedule_check
        self.detail.busy("Loading backups…", self.connection.backup_status, lambda b: self.show_backup(b, True))

    def _mine(self) -> dict:
        return next((s for s in self.backup.get("sites") or [] if s["name"] == self.detail.name), {})

    def show_backup(self, backup: dict, reset: bool = False) -> None:
        name = self.detail.name
        if name != self.loaded_for:
            return
        self.backup = backup
        ready = bool(backup.get("installed")) and bool(backup.get("destination"))
        self.not_ready.setVisible(not ready)
        self.ready_area.setVisible(ready)
        if not ready:
            return
        mine = self._mine()
        if reset:
            self.modes.get(mine.get("mode") or "global", self.modes["global"]).setChecked(True)
            if mine.get("schedule"):
                self.schedule.edit.setText(mine["schedule"])
            self.load_snapshots()
        self.modes["global"].setText("On the server's schedule (" + (
            hm.schedule_label(backup.get("schedule") or "") if backup.get("enabled")
            else "scheduled backups are off for the server") + ")")
        runs = [run for run in backup.get("runs") or [] if run.get("site") == name]
        fill_runs(self.runs_table, runs)
        busy = (any(run.get("state") == "running" for run in runs) or bool(backup.get("running"))
                or name in (backup.get("busy_sites") or []))
        self.now_button.setEnabled(not busy)
        if busy:
            self._poll.start()
        elif self._was_busy:
            # A backup or restore ended: its snapshot shows up.
            self.load_snapshots()
        self._was_busy = busy
        self._mode_changed()

    def _poll_status(self) -> None:
        _quietly(self.connection.backup_status, self.show_backup)

    def _mode(self) -> str:
        return next(mode for mode, button in self.modes.items() if button.isChecked()) \
            if any(b.isChecked() for b in self.modes.values()) else "global"

    def _mode_changed(self) -> None:
        self.schedule_form.setRowVisible(self.schedule, self._mode() == "custom")

    def load_snapshots(self) -> None:
        name = self.detail.name
        self.snapshot_note.setText("Asking the backup destination…")

        def show(snapshots: list[dict]) -> None:
            if name != self.detail.name:
                return
            self.snapshots = snapshots
            self.snapshot_note.setText("" if snapshots else "No backups of this site yet.")
            host = self.backup.get("host")
            fill_table(self.snapshots_table, [
                [when(s.get("time")), s.get("short_id", "") + (f" (from {s['host']})" if s.get("host") and host
                                                               and s["host"] != host else ""),
                 hm.format_bytes(s.get("size"))]
                for s in snapshots
            ], snapshots)

        def failed(error: Exception) -> None:
            try:
                self.snapshot_note.setText(str(error))
            except RuntimeError:
                pass

        async_utils.run_in_background(lambda: self.connection.backup_snapshots(name),
                                      on_result=lambda s: self._safe(show, s), on_error=failed)

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except RuntimeError:
            pass

    def _save(self) -> None:
        mode = self._mode()
        schedule = self.schedule.text() if mode == "custom" else None
        if mode == "custom" and (not schedule or self.schedule.error()):
            QMessageBox.warning(self, dialogs.TITLE, f"Schedule: {self.schedule.error() or 'required'}")
            return
        name = self.detail.name
        self.detail.busy("Saving the site's backup schedule…",
                         lambda: self.connection.backup_site(name, mode, schedule), self.show_backup, "Saved")

    def _backup_now(self) -> None:
        name = self.detail.name
        self.detail.busy(f"Starting a backup of {name}…", lambda: self.connection.backup_now(name),
                         self.show_backup, "Backup started")

    def _restore(self) -> None:
        snapshot = selected_data(self.snapshots_table)
        if snapshot is None:
            self.detail.manager.flash("Select a snapshot first")
            return
        site = self.detail.site
        dialog = dialogs.RestoreDialog(site, snapshot, when(snapshot.get("time")), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, files, databases = site["name"], dialog.files.isChecked(), dialog.databases.isChecked()
        self.detail.busy(f"Starting the restore of {name}…",
                         lambda: self.connection.backup_restore(name, snapshot["id"], files, databases),
                         self.show_backup, "Restore started")

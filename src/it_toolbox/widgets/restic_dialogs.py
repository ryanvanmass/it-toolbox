"""Dialogs for the Restic Manager (widgets/restic_manager_widget.py).
They collect input the way the cockpit-restic page's dialogs do; the
manager makes the helper calls, except where a dialog needs the server
while it is open (run history, the snapshot list, the snapshot file
browser), which it does through the connection it is given.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import restic_manager as rm
from it_toolbox.widgets.hosting_dialogs import monospace
from it_toolbox.widgets.hosting_manager_widget import size_label, when_label
from it_toolbox.widgets.remote_helper_widget import (
    Busy,
    fill_table,
    make_table,
    selected_data,
)

TITLE = "Restic Manager"

PATH_ROLE = Qt.ItemDataRole.UserRole
IS_DIR_ROLE = Qt.ItemDataRole.UserRole + 1
LOADED_ROLE = Qt.ItemDataRole.UserRole + 2


def _form(parent=None) -> QFormLayout:
    """A form whose fields fill the width with the labels in one column on
    every platform (macOS's style otherwise keeps fields at their size hint
    and centres the form)."""
    form = QFormLayout(parent) if parent is not None else QFormLayout()
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    return form


def _buttons(dialog: QDialog, accept, ok_text: str | None = None) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    if ok_text:
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


def _lines_edit(text: str, placeholder: str) -> QPlainTextEdit:
    edit = QPlainTextEdit(text)
    edit.setPlaceholderText(placeholder)
    edit.setTabChangesFocus(True)
    edit.setFixedHeight(80)
    return edit


# -- Schedule --------------------------------------------------------------------


class SchedulePicker(QWidget):
    """The page's ScheduleFields: hourly/daily/weekly/monthly, or a custom
    systemd OnCalendar= expression (and, with allow_never, "Never")."""

    NEVER = "never"
    CUSTOM = "custom"

    def __init__(self, initial: str, allow_never: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice = QComboBox()
        if allow_never:
            self.choice.addItem("Never (manual only)", self.NEVER)
        for value, label in rm.SCHEDULE_PRESETS.items():
            self.choice.addItem(label, value)
        self.choice.addItem("Custom (systemd OnCalendar=)", self.CUSTOM)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("*-*-* 03:00:00")

        if initial == "" and allow_never:
            selected = self.NEVER
        elif initial in rm.SCHEDULE_PRESETS:
            selected = initial
        else:
            selected = self.CUSTOM
            self.custom.setText(initial)
        self.choice.setCurrentIndex(self.choice.findData(selected))
        self.choice.currentIndexChanged.connect(self._sync)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.choice)
        layout.addWidget(self.custom, 1)
        self._sync()

    def _sync(self) -> None:
        self.custom.setVisible(self.choice.currentData() == self.CUSTOM)

    def schedule(self) -> str:
        """'' for never; the custom expression (possibly empty) otherwise."""
        choice = self.choice.currentData()
        if choice == self.NEVER:
            return ""
        if choice == self.CUSTOM:
            return self.custom.text().strip()
        return choice

    def is_complete(self) -> bool:
        return self.choice.currentData() != self.CUSTOM or bool(self.custom.text().strip())


# -- Repositories ------------------------------------------------------------------


class RepoDialog(QDialog):
    """Create a repository: a local/mounted path, or SFTP (the server
    generates a keypair for it)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Repository")
        self.setMinimumWidth(520)
        self.name = QLineEdit()
        self.backend = QComboBox()
        self.backend.addItem("Local / mounted path", "local")
        self.backend.addItem("SFTP", "sftp")
        self.path = QLineEdit()
        self.path.setPlaceholderText("/mnt/backups/myrepo")
        self.host = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(22)
        self.user = QLineEdit()
        self.remote_path = QLineEdit()
        self.remote_path.setPlaceholderText("/srv/restic/myrepo")
        self.custom_password = QCheckBox(
            "Use my own password instead of generating one (for adopting an existing repository)"
        )
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setEnabled(False)
        self.custom_password.toggled.connect(self.password.setEnabled)

        self.form = _form()
        self.form.addRow("Name:", self.name)
        self.form.addRow("Backend:", self.backend)
        self.form.addRow("Path:", self.path)
        self.form.addRow("Host:", self.host)
        self.form.addRow("Port:", self.port)
        self.form.addRow("Remote user:", self.user)
        self.form.addRow("Remote path:", self.remote_path)
        self.sftp_note = _note(
            "An SSH keypair will be generated for this repository. You'll be shown the public key to add to "
            "the remote user's authorized_keys before it can be used."
        )
        self.form.addRow(self.sftp_note)
        self.form.addRow("Encryption password:", self.custom_password)
        self.form.addRow("", self.password)
        self.backend.currentIndexChanged.connect(self._sync)
        self._sync()

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(_buttons(self, self._accept, "Create"))

    def _sync(self) -> None:
        sftp = self.backend.currentData() == "sftp"
        self.form.setRowVisible(self.path, not sftp)
        for widget in (self.host, self.port, self.user, self.remote_path, self.sftp_note):
            self.form.setRowVisible(widget, sftp)

    def _problem(self) -> str | None:
        if not self.name.text().strip():
            return "Enter a name for the repository."
        if self.backend.currentData() == "local":
            if not self.path.text().strip().startswith("/"):
                return "The repository path must be an absolute path."
        else:
            if not self.host.text().strip() or not self.user.text().strip():
                return "Enter the SFTP host and remote user."
            if not self.remote_path.text().strip().startswith("/"):
                return "The remote path must be an absolute path."
        if self.custom_password.isChecked() and not self.password.text():
            return "Enter the repository's password, or let one be generated."
        return None

    def _accept(self) -> None:
        problem = self._problem()
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()

    def values(self) -> dict:
        """Keyword arguments for ResticConnection.create_repo."""
        values = {"name": self.name.text().strip(), "backend": self.backend.currentData()}
        if values["backend"] == "local":
            values["path"] = self.path.text().strip()
        else:
            values.update(host=self.host.text().strip(), port=self.port.value(), user=self.user.text().strip(),
                          remote_path=self.remote_path.text().strip())
        if self.custom_password.isChecked():
            values["password"] = self.password.text()
        return values


class SecretsDialog(QDialog):
    """The one-time password and/or SFTP public key of a new repository.
    The repository already exists by now; Done stays disabled until the
    user says they have saved them."""

    def __init__(self, result: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save These Before Continuing")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(_note(
            "This is the only time this password (and key, if shown) will be displayed. Without it, the backups "
            "in this repository cannot be restored."
        ))
        self.fields: dict[str, QLineEdit] = {}
        form = _form()
        if result.get("generated_password"):
            form.addRow("Repository password:", self._copyable("password", result["generated_password"]))
        if result.get("public_key"):
            form.addRow(QLabel("SSH public key — add this to the remote user's authorized_keys, then "
                               "Initialize the repository:"))
            form.addRow(self._copyable("public_key", result["public_key"]))
        layout.addLayout(form)
        self.saved = QCheckBox("I have saved this")
        layout.addWidget(self.saved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.done_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.done_button.setText("Done")
        self.done_button.setEnabled(False)
        self.saved.toggled.connect(self.done_button.setEnabled)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _copyable(self, key: str, value: str) -> QWidget:
        field = QLineEdit(value)
        field.setReadOnly(True)
        field.setFont(monospace())
        field.setCursorPosition(0)
        self.fields[key] = field
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(value))
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field, 1)
        layout.addWidget(copy)
        return row

    def reject(self) -> None:
        # Escape / the close button: only once the secrets are saved.
        if self.saved.isChecked():
            super().reject()


class HealthCheckDialog(QDialog):
    """The page's RepoMaintenanceDialog: scheduled `restic check`, how much
    data it reads back, and where to ping the result."""

    def __init__(self, repo: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Health Checks for {repo['name']}")
        self.setMinimumWidth(560)
        self.schedule = SchedulePicker(repo.get("check_schedule") or "", allow_never=True)
        self.read_data = QSpinBox()
        self.read_data.setRange(0, 100)
        self.read_data.setSuffix(" %")
        self.read_data.setValue(int(repo.get("check_read_data") or 0))
        self.healthcheck_url = QLineEdit(repo.get("healthcheck_url") or "")
        self.healthcheck_url.setPlaceholderText("https://hc-ping.com/your-uuid-here")
        form = _form()
        form.addRow("Scheduled check:", self.schedule)
        form.addRow("Verify data:", self.read_data)
        form.addRow("", _note(
            "0 checks the repository structure only (fast). A higher value also reads back that share of the "
            "stored data on every check, which catches silent corruption but downloads it — slow and costly "
            "on remote repositories."
        ))
        form.addRow("Healthcheck ping URL:", self.healthcheck_url)
        form.addRow("", _note(
            "Optional. Pinged when a check starts, succeeds (URL) or fails (URL/fail) — works with "
            "healthchecks.io or a self-hosted instance. Treat the URL as a secret."
        ))
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self._accept, "Save"))

    def _accept(self) -> None:
        if not self.schedule.is_complete():
            QMessageBox.warning(self, TITLE, "Enter an OnCalendar expression for the custom schedule.")
            return
        self.accept()

    def values(self) -> dict:
        """Keyword arguments for ResticConnection.update_repo."""
        return {"check_schedule": self.schedule.schedule(), "check_read_data": self.read_data.value(),
                "healthcheck_url": self.healthcheck_url.text().strip()}


# -- Backup jobs ---------------------------------------------------------------------


class JobDialog(QDialog):
    """Create or edit a backup job (the page's JobDialog)."""

    def __init__(self, job: dict | None, repos: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.job = job
        self.setWindowTitle(f"Edit {job['name']}" if job else "Create Backup Job")
        self.setMinimumWidth(600)
        job = job or {}
        self.name = QLineEdit(job.get("name", ""))
        self.repo = QComboBox()
        for repo in repos:
            self.repo.addItem(repo["name"], repo["id"])
        if job.get("repo_id"):
            index = self.repo.findData(job["repo_id"])
            if index != -1:
                self.repo.setCurrentIndex(index)
        self.source_paths = _lines_edit("\n".join(job.get("source_paths", [])),
                                        "One absolute path per line, e.g.\n/home\n/etc")
        self.exclude_patterns = _lines_edit("\n".join(job.get("exclude_patterns", [])),
                                            "One glob pattern per line, e.g.\n*.tmp\n*/node_modules")
        self.pre_command = QLineEdit(job.get("pre_command", ""))
        self.pre_command.setPlaceholderText("e.g. mysqldump mydb > /var/backups/mydb.sql")
        self.post_command = QLineEdit(job.get("post_command", ""))
        self.post_command.setPlaceholderText("e.g. systemctl start myapp")
        self.schedule = SchedulePicker(job.get("schedule", "daily"))
        self.healthcheck_url = QLineEdit(job.get("healthcheck_url", ""))
        self.healthcheck_url.setPlaceholderText("https://hc-ping.com/your-uuid-here")
        self.keep: dict[str, QSpinBox] = {}
        keep_row = QHBoxLayout()
        for key, label in (("keep_daily", "Daily"), ("keep_weekly", "Weekly"), ("keep_monthly", "Monthly"),
                           ("keep_yearly", "Yearly")):
            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(int(job.get(key, rm.DEFAULT_RETENTION[key])))
            self.keep[key] = spin
            keep_row.addWidget(QLabel(f"{label}:"))
            keep_row.addWidget(spin)
        keep_row.addStretch(1)
        self.enabled = QCheckBox("Enabled (runs on the schedule above)")
        self.enabled.setChecked(bool(job.get("enabled", True)))

        form = _form()
        form.addRow("Name:", self.name)
        form.addRow("Repository:", self.repo)
        form.addRow("Source paths:", self.source_paths)
        form.addRow("Exclude patterns:", self.exclude_patterns)
        form.addRow("Pre-backup command:", self.pre_command)
        form.addRow("", _note("Run via a shell right before the backup starts. If it fails, the backup is "
                              "skipped entirely."))
        form.addRow("Post-backup command:", self.post_command)
        form.addRow("", _note("Run via a shell right after the backup finishes, even if it (or the pre-backup "
                              "command) failed."))
        form.addRow("Schedule:", self.schedule)
        form.addRow("", self.enabled)
        form.addRow("Healthcheck ping URL:", self.healthcheck_url)
        form.addRow("", _note("Optional. Pinged when a run starts, succeeds (URL) or fails (URL/fail), and "
                              "alerts you when a scheduled backup never runs. Treat the URL as a secret."))
        form.addRow("Keep snapshots:", keep_row)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self._accept, "Save" if self.job else "Create"))

    def _problem(self) -> str | None:
        if not self.name.text().strip():
            return "Enter a name for the job."
        if self.repo.currentData() is None:
            return "Create and initialize a repository first."
        paths = rm.path_lines(self.source_paths.toPlainText())
        if not paths:
            return "At least one source path is required."
        bad = next((p for p in paths if not p.startswith("/")), None)
        if bad:
            return f"Source paths must be absolute: {bad}"
        if not self.schedule.is_complete():
            return "Enter an OnCalendar expression for the custom schedule."
        return None

    def _accept(self) -> None:
        problem = self._problem()
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()

    def values(self) -> dict:
        """The helper's create-job / update-job fields."""
        return {
            "name": self.name.text().strip(),
            "repo_id": self.repo.currentData(),
            "source_paths": rm.path_lines(self.source_paths.toPlainText()),
            "exclude_patterns": rm.path_lines(self.exclude_patterns.toPlainText()),
            "schedule": self.schedule.schedule(),
            **{key: spin.value() for key, spin in self.keep.items()},
            "enabled": self.enabled.isChecked(),
            "pre_command": self.pre_command.text().strip(),
            "post_command": self.post_command.text().strip(),
            "healthcheck_url": self.healthcheck_url.text().strip(),
        }


# -- Run / check history -------------------------------------------------------------------


class RunsDialog(QDialog):
    """A job's run history or a repository's check history (the same shape),
    with the selected run's output underneath."""

    COLUMNS = ("Started", "Finished", "Status")

    def __init__(self, title: str, empty_text: str, load, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._load = load
        self._empty_text = empty_text
        self.busy = Busy(self, TITLE)
        self.runs: list[dict] = []
        self.setWindowTitle(title)
        self.resize(820, 600)
        self.table = make_table(list(self.COLUMNS))
        self.table.itemSelectionChanged.connect(self._show_output)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(monospace())
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.output)
        splitter.setSizes([220, 380])
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addStretch(1)
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.busy("Loading history…", self._load, self.show_runs)

    def show_runs(self, runs: list[dict]) -> None:
        selected = selected_data(self.table)
        self.runs = runs
        rows = [[when_label(r.get("started_at")), when_label(r.get("finished_at")),
                 rm.run_status_label(r.get("status"))] for r in runs]
        fill_table(self.table, rows, [r["id"] for r in runs])
        if not runs:
            self.output.setPlainText(self._empty_text)
            return
        ids = [r["id"] for r in runs]
        self.table.selectRow(ids.index(selected) if selected in ids else 0)

    def _show_output(self) -> None:
        run_id = selected_data(self.table)
        run = next((r for r in self.runs if r["id"] == run_id), None)
        if run is not None:
            self.output.setPlainText(run.get("output_tail") or "(no output recorded)")


# -- Snapshots ------------------------------------------------------------------------------


def snapshot_time(snapshot: dict) -> str:
    return when_label(snapshot.get("time"))


class SnapshotsDialog(QDialog):
    """A repository's snapshots with its size and count: restore (all or
    chosen files) and delete."""

    COLUMNS = ("ID", "Time", "Host", "Paths", "Files")

    def __init__(self, connection: rm.ResticConnection, repo: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self.repo = repo
        self.busy = Busy(self, TITLE)
        self.snapshots: list[dict] = []
        self.setWindowTitle(f"Snapshots in {repo['name']}")
        self.resize(900, 560)
        self.stats = QLabel("Reading repository statistics…")
        self.stats.setWordWrap(True)
        self.table = make_table(list(self.COLUMNS))
        self.table.doubleClicked.connect(lambda _: self.restore(self.selected()))
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.restore_button = QPushButton("Restore…")
        self.restore_button.clicked.connect(lambda: self.restore(self.selected()))
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(lambda: self.delete(self.selected()))
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        for button in (self.restore_button, self.delete_button, refresh):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.stats)
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        self._sync_buttons()
        self.refresh()

    def selected(self) -> dict | None:
        snapshot_id = selected_data(self.table)
        return next((s for s in self.snapshots if s["id"] == snapshot_id), None)

    def _sync_buttons(self) -> None:
        has = self.selected() is not None
        self.restore_button.setEnabled(has)
        self.delete_button.setEnabled(has)

    def refresh(self) -> None:
        repo_id = self.repo["id"]
        self.busy("Loading snapshots…", lambda: self._connection.list_snapshots(repo_id), self.show_snapshots)

        # Stats are a nicety: a failure is shown inline, never as an error box.
        def stats():
            try:
                return self._connection.repo_stats(repo_id), None
            except rm.ResticError as exc:
                return None, str(exc)

        self.busy("Reading repository statistics…", stats, lambda result: self.show_stats(*result))

    def show_stats(self, stats: dict | None, error: str | None) -> None:
        if stats is None:
            self.stats.setText(f"Could not read repository statistics: {error}")
            return
        self.stats.setText(f"Size on disk: {size_label(stats.get('size'))} · "
                           f"Snapshots: {stats.get('snapshot_count', 0)}")

    def show_snapshots(self, snapshots: list[dict]) -> None:
        self.snapshots = sorted(snapshots, key=lambda s: s.get("time", ""), reverse=True)
        rows = [[s.get("short_id", s["id"][:8]), snapshot_time(s), s.get("hostname", ""),
                 ", ".join(s.get("paths", [])),
                 (s.get("summary") or {}).get("total_files_processed", "")] for s in self.snapshots]
        fill_table(self.table, rows, [s["id"] for s in self.snapshots])
        if not self.snapshots:
            self.stats.setText(self.stats.text() + "\nNo snapshots yet — they appear once a backup job has run "
                               "against this repository.")
        self._sync_buttons()

    def restore(self, snapshot: dict | None) -> None:
        if snapshot is None:
            return
        dialog = RestoreDialog(self._connection, self.repo, snapshot, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target, include = dialog.target(), dialog.include_paths()
        repo_id, snapshot_id = self.repo["id"], snapshot["id"]
        self.busy(f"Restoring snapshot {snapshot.get('short_id', '')} to {target}…",
                  lambda: self._connection.restore_snapshot(repo_id, snapshot_id, target, include),
                  lambda _: QMessageBox.information(self, TITLE, f"Restored to {target}."),
                  done_message=f"Restored to {target}")

    def delete(self, snapshot: dict | None) -> None:
        if snapshot is None:
            return
        confirmed = QMessageBox.question(
            self, "Delete Snapshot",
            f"Permanently delete snapshot {snapshot.get('short_id', '')} from {snapshot_time(snapshot)}? Data "
            "that only this snapshot uses is removed from the repository. This cannot be undone.",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        repo_id, snapshot_id = self.repo["id"], snapshot["id"]
        self.busy(f"Deleting snapshot {snapshot.get('short_id', '')}…",
                  lambda: self._connection.forget_snapshots(repo_id, [snapshot_id]),
                  lambda _: self.refresh(), done_message="Snapshot deleted")


class RestoreDialog(QDialog):
    """Where to restore a snapshot to, and everything or chosen paths. The
    paths box is the single source of truth; ticking files in the folder
    tree edits it (the page's RestoreDialog)."""

    def __init__(self, connection: rm.ResticConnection, repo: dict, snapshot: dict,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self.repo = repo
        self.snapshot = snapshot
        self.setWindowTitle(f"Restore Snapshot from {snapshot_time(snapshot)}")
        self.resize(640, 380)
        self.target_edit = QLineEdit(rm.DEFAULT_RESTORE_TARGET)
        self.restore_all = QRadioButton("Restore everything in this snapshot")
        self.restore_some = QRadioButton("Restore only specific files or directories")
        self.restore_all.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.restore_all)
        group.addButton(self.restore_some)
        self.paths = _lines_edit("", "One absolute path per line, e.g.\n/home/alice/report.docx\n/home/alice/notes")
        self.paths.textChanged.connect(self._paths_changed)
        self.browse_button = QPushButton("Browse Files in This Snapshot…")
        self.browse_button.clicked.connect(self._browse)
        self.browser: SnapshotBrowser | None = None

        self.specific = QWidget()
        specific_layout = QVBoxLayout(self.specific)
        specific_layout.setContentsMargins(0, 0, 0, 0)
        specific_layout.addWidget(self.paths)
        specific_layout.addWidget(_note("A directory restores everything under it. Type paths here, or tick "
                                        "them in the folder tree."))
        specific_layout.addWidget(self.browse_button)
        self._specific_layout = specific_layout
        self.restore_some.toggled.connect(self.specific.setVisible)
        self.specific.setVisible(False)

        form = _form()
        form.addRow("Restore to directory:", self.target_edit)
        form.addRow("What to restore:", self.restore_all)
        form.addRow("", self.restore_some)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.specific, 1)
        layout.addWidget(_buttons(self, self._accept, "Restore"))

    def selected(self) -> list[str]:
        return [rm.normalize_path(p) for p in rm.path_lines(self.paths.toPlainText())]

    def toggle_path(self, path: str, checked: bool) -> None:
        lines = rm.toggle_path(rm.path_lines(self.paths.toPlainText()), path, checked)
        self.paths.setPlainText("\n".join(lines))

    def _paths_changed(self) -> None:
        if self.browser is not None:
            self.browser.sync(self.selected())

    def _browse(self) -> None:
        self.browse_button.hide()
        self.browser = SnapshotBrowser(self._connection, self.repo["id"], self.snapshot["id"], self.toggle_path)
        self._specific_layout.addWidget(self.browser, 1)
        self.browser.sync(self.selected())
        self.resize(self.width(), max(self.height(), 640))

    def target(self) -> str:
        return self.target_edit.text().strip()

    def include_paths(self) -> list[str]:
        return [] if self.restore_all.isChecked() else rm.path_lines(self.paths.toPlainText())

    def _accept(self) -> None:
        if not self.target().startswith("/"):
            QMessageBox.warning(self, TITLE, "The restore directory must be an absolute path.")
            return
        if self.restore_some.isChecked() and not self.include_paths():
            QMessageBox.warning(self, TITLE, 'Enter or pick at least one file or directory to restore, or choose '
                                             '"Restore everything".')
            return
        self.accept()


class SnapshotBrowser(QWidget):
    """A snapshot's folder tree, loaded one directory at a time as folders
    are expanded, with a name search. Ticking an entry calls
    on_toggle(path, checked); sync() reflects the current selection (an
    entry inside a chosen folder shows as ticked and can't be changed)."""

    def __init__(self, connection: rm.ResticConnection, repo_id: str, snapshot_id: str, on_toggle,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self._repo_id = repo_id
        self._snapshot_id = snapshot_id
        self._on_toggle = on_toggle
        self._selected: list[str] = []
        self._syncing = False
        self.busy = Busy(self, TITLE)

        self.query = QLineEdit()
        self.query.setPlaceholderText("Search by file name…")
        self.query.returnPressed.connect(self.search)
        search = QPushButton("Search")
        search.clicked.connect(self.search)
        self.back = QPushButton("Back to Folders")
        self.back.clicked.connect(self.show_folders)
        self.back.hide()
        row = QHBoxLayout()
        row.addWidget(self.query, 1)
        row.addWidget(search)
        row.addWidget(self.back)

        self.tree = self._make_tree()
        self.tree.itemExpanded.connect(self._on_expanded)
        self.results = self._make_tree()
        self.results.setRootIsDecorated(False)
        self.results_note = QLabel()
        self.results_note.setWordWrap(True)
        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(self.results_note)
        results_layout.addWidget(self.results, 1)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.tree)
        self.pages.addWidget(results_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.pages, 1)
        self._load(None, "/")

    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(["Name", "Size"])
        tree.setColumnWidth(0, 360)
        tree.itemChanged.connect(self._on_item_changed)
        return tree

    def _entry_item(self, entry: dict, label: str) -> QTreeWidgetItem:
        is_dir = entry.get("type") == "dir"
        item = QTreeWidgetItem([label + ("/" if is_dir and not label.endswith("/") else ""),
                                "" if is_dir else size_label(entry.get("size"))])
        item.setData(0, PATH_ROLE, entry["path"])
        item.setData(0, IS_DIR_ROLE, is_dir)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        if is_dir:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return item

    # -- Folder tree ---------------------------------------------------------------

    def _load(self, parent: QTreeWidgetItem | None, path: str) -> None:
        placeholder = QTreeWidgetItem(["Loading…"])
        if parent is None:
            self.tree.addTopLevelItem(placeholder)
        else:
            parent.setData(0, LOADED_ROLE, True)
            parent.addChild(placeholder)

        def fill(files: list[dict]) -> None:
            self._syncing = True
            try:
                if parent is None:
                    self.tree.clear()
                    if not files:
                        self.tree.addTopLevelItem(QTreeWidgetItem(["(this snapshot is empty)"]))
                    for entry in files:
                        self.tree.addTopLevelItem(self._entry_item(entry, entry["name"]))
                else:
                    parent.takeChildren()
                    if not files:
                        parent.addChild(QTreeWidgetItem(["(empty)"]))
                    for entry in files:
                        parent.addChild(self._entry_item(entry, entry["name"]))
            finally:
                self._syncing = False
            self.sync(self._selected)

        def failed(error: Exception) -> None:
            if parent is None:
                self.tree.clear()
                self.tree.addTopLevelItem(QTreeWidgetItem([f"Could not list the snapshot: {error}"]))
            else:
                parent.takeChildren()
                parent.setData(0, LOADED_ROLE, False)
                parent.addChild(QTreeWidgetItem([f"Could not list this folder: {error}"]))

        repo_id, snapshot_id = self._repo_id, self._snapshot_id
        self.busy(f"Listing {path}…", lambda: self._connection.list_snapshot_files(repo_id, snapshot_id, path),
                  fill, on_error=failed)

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, IS_DIR_ROLE) and not item.data(0, LOADED_ROLE):
            item.takeChildren()
            self._load(item, item.data(0, PATH_ROLE))

    # -- Search ----------------------------------------------------------------------

    def search(self) -> None:
        pattern = self.query.text().strip()
        if not pattern:
            self.show_folders()
            return
        repo_id, snapshot_id = self._repo_id, self._snapshot_id
        self.busy(f"Searching for {pattern}…",
                  lambda: self._connection.find_snapshot_files(repo_id, snapshot_id, pattern), self.show_results)

    def show_results(self, result: dict) -> None:
        matches = result.get("matches", [])
        self._syncing = True
        try:
            self.results.clear()
            for entry in matches:
                self.results.addTopLevelItem(self._entry_item(entry, entry["path"]))
                self.results.topLevelItem(self.results.topLevelItemCount() - 1).setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        finally:
            self._syncing = False
        if not matches:
            self.results_note.setText("No matching files. Try other text; * and ? work as wildcards.")
        elif result.get("truncated"):
            self.results_note.setText(f"Showing the first {len(matches)} matches — search for more of the name "
                                      "to narrow it down.")
        else:
            self.results_note.setText(f"{len(matches)} match{'es' if len(matches) != 1 else ''}.")
        self.pages.setCurrentIndex(1)
        self.back.show()
        self.sync(self._selected)

    def show_folders(self) -> None:
        self.pages.setCurrentIndex(0)
        self.back.hide()

    # -- Selection ---------------------------------------------------------------------

    def _items(self):
        for tree in (self.tree, self.results):
            stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
            while stack:
                item = stack.pop()
                yield item
                stack.extend(item.child(i) for i in range(item.childCount()))

    def sync(self, selected: list[str]) -> None:
        self._selected = list(selected)
        self._syncing = True
        try:
            for item in self._items():
                path = item.data(0, PATH_ROLE)
                if path is None:
                    continue
                covered = rm.covered_by(path, self._selected)
                checked = covered is not None or path in self._selected
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                flags = item.flags()
                if covered is not None:
                    item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip(0, f"Included with {covered}")
                else:
                    item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip(0, path)
        finally:
            self._syncing = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing or column != 0 or item.data(0, PATH_ROLE) is None:
            return
        self._on_toggle(item.data(0, PATH_ROLE), item.checkState(0) == Qt.CheckState.Checked)

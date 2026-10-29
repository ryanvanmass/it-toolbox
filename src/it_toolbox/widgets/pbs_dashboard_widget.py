"""Proxmox Backup Server dashboard -- the Infrastructure module's
"PBS: <host>" tab (see modules/infrastructure/pbs_product.py).

Read-only (phase 1): a host card, the datastores with usage and PBS's own
estimated full date, the scheduled jobs with their last result, and the
recent tasks with failures first. Every call goes through pbs_client on
async_utils' thread pool; nothing holds a connection open, so
close_session() only stops the refresh timer.
"""

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, pbs_client
from it_toolbox.core.pbs_models import DatastoreUsage, NodeStatus, PbsJob, PbsTask

# Backups change slowly; a faster refresh would only add load on the server.
REFRESH_MS = 30_000
# Datastore usage at or above this is flagged, matching the spec's 85%.
USAGE_WARNING = 0.85

FAILED_BRUSH = QBrush(QColor("#c0392b"))
WARNING_BRUSH = QBrush(QColor("#d68910"))

JOB_KIND_LABELS = {"sync": "Sync", "verify": "Verify", "prune": "Prune", "gc": "Garbage collection"}


def format_bytes(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "—"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "—"


def format_time(epoch: int | None) -> str:
    if not epoch:
        return "—"
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def format_age(epoch: int | None, now: float | None = None) -> str:
    """"3h ago" / "2d ago" -- for the tree's last-backup hint."""
    if not epoch:
        return "never"
    seconds = max(0, int((now if now is not None else time.time()) - epoch))
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def format_uptime(seconds: int) -> str:
    days, rest = divmod(max(0, seconds), 86400)
    hours, rest = divmod(rest, 3600)
    return f"{days}d {hours}h" if days else f"{hours}h {rest // 60}m"


def estimated_full_label(store: DatastoreUsage, now: float | None = None) -> str:
    """PBS's estimate, worded: none yet, not growing (a date in the past),
    or the date."""
    if store.estimated_full_date is None:
        return "Not enough data yet"
    if store.estimated_full_date <= (now if now is not None else time.time()):
        return "Not filling up"
    return datetime.fromtimestamp(store.estimated_full_date).strftime("%Y-%m-%d")


def table_item(text: str, sort_value=None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if sort_value is not None:
        item.setData(Qt.ItemDataRole.UserRole, sort_value)
    return item


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    return table


class PbsDashboardWidget(QWidget):
    def __init__(self, host, secret: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self._secret = secret
        self._tasks: list[PbsTask] = []
        self._loading = 0

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #c0392b;")
        self._error_label.hide()

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        self._updated_label = QLabel()
        top = QHBoxLayout()
        top.addWidget(self._updated_label, 1)
        top.addWidget(refresh_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._error_label)
        layout.addWidget(self._build_host_box())
        layout.addWidget(self._build_datastores_box(), 2)
        layout.addWidget(self._build_jobs_box(), 2)
        layout.addWidget(self._build_tasks_box(), 3)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start()

        self.refresh()

    # -- Layout ----------------------------------------------------------------

    def _build_host_box(self) -> QGroupBox:
        box = QGroupBox("Host")
        form = QFormLayout(box)
        self._host_fields = {
            key: QLabel("Loading…")
            for key in ("version", "cpu", "memory", "root", "uptime", "subscription")
        }
        form.addRow("Version:", self._host_fields["version"])
        form.addRow("CPU:", self._host_fields["cpu"])
        form.addRow("Memory:", self._host_fields["memory"])
        form.addRow("Root disk:", self._host_fields["root"])
        form.addRow("Uptime:", self._host_fields["uptime"])
        form.addRow("Subscription:", self._host_fields["subscription"])
        return box

    def _build_datastores_box(self) -> QGroupBox:
        box = QGroupBox("Datastores")
        self._datastores_table = make_table(
            ["Datastore", "Used", "Total", "Usage", "Estimated full", "Backend", "Status"]
        )
        QVBoxLayout(box).addWidget(self._datastores_table)
        return box

    def _build_jobs_box(self) -> QGroupBox:
        box = QGroupBox("Jobs")
        self._jobs_table = make_table(["Type", "Job", "Datastore", "Schedule", "Last run", "Result", "Next run"])
        QVBoxLayout(box).addWidget(self._jobs_table)
        return box

    def _build_tasks_box(self) -> QGroupBox:
        box = QGroupBox("Recent tasks")
        self._tasks_table = make_table(["Started", "Type", "Target", "User", "Status"])
        self._tasks_table.cellDoubleClicked.connect(self._show_task_log)
        hint = QLabel("Failures are listed first. Double-click a task to see its log.")
        hint.setStyleSheet("color: palette(placeholder-text);")
        layout = QVBoxLayout(box)
        layout.addWidget(self._tasks_table)
        layout.addWidget(hint)
        return box

    # -- Loading ---------------------------------------------------------------

    def _on_timer(self) -> None:
        # Only while the tab is actually on screen, like the GL.iNet dashboard.
        if self.isVisible() and self._loading == 0:
            self.refresh()

    def refresh(self) -> None:
        self._error_label.hide()
        self._load(lambda: pbs_client.get_node_status(self._host, self._secret), self._on_status)
        self._load(lambda: pbs_client.list_datastores(self._host, self._secret), self._on_datastores)
        self._load(lambda: pbs_client.list_jobs(self._host, self._secret), self._on_jobs)
        self._load(lambda: pbs_client.list_tasks(self._host, self._secret), self._on_tasks)

    def _load(self, fn, on_result) -> None:
        self._loading += 1

        def done(value) -> None:
            self._loading -= 1
            on_result(value)
            self._updated_label.setText(f"Updated {datetime.now().strftime('%H:%M:%S')}")

        def failed(error: Exception) -> None:
            self._loading -= 1
            self._on_error(error)

        async_utils.run_in_background(fn, on_result=done, on_error=failed)

    def _on_error(self, error: Exception) -> None:
        self._error_label.setText(str(error))
        self._error_label.show()

    def _on_status(self, status: NodeStatus) -> None:
        fields = self._host_fields
        fields["version"].setText(f"Proxmox Backup Server {status.version}" if status.version else "—")
        fields["cpu"].setText(f"{status.cpu * 100:.0f}% of {status.cpus} CPUs" if status.cpus else f"{status.cpu * 100:.0f}%")
        fields["memory"].setText(f"{format_bytes(status.memory_used)} of {format_bytes(status.memory_total)}")
        fields["root"].setText(f"{format_bytes(status.root_used)} of {format_bytes(status.root_total)}")
        fields["uptime"].setText(format_uptime(status.uptime))
        fields["subscription"].setText(status.subscription or "—")

    def _on_datastores(self, stores: list[DatastoreUsage]) -> None:
        table = self._datastores_table
        table.setRowCount(len(stores))
        for row, store in enumerate(stores):
            fraction = store.used_fraction
            usage = table_item(f"{fraction * 100:.1f}%" if fraction is not None else "—")
            if fraction is not None and fraction >= USAGE_WARNING:
                usage.setForeground(WARNING_BRUSH)
            status = store.error or (f"Maintenance: {store.maintenance}" if store.maintenance else "OK")
            status_item = table_item(status)
            if store.error:
                status_item.setForeground(FAILED_BRUSH)
            elif store.maintenance:
                status_item.setForeground(WARNING_BRUSH)
            name = table_item(store.store)
            if store.comment:
                name.setToolTip(store.comment)
            table.setItem(row, 0, name)
            table.setItem(row, 1, table_item(format_bytes(store.used)))
            table.setItem(row, 2, table_item(format_bytes(store.total)))
            table.setItem(row, 3, usage)
            table.setItem(row, 4, table_item(estimated_full_label(store)))
            table.setItem(row, 5, table_item("S3" if store.backend_type == "s3" else "Filesystem"))
            table.setItem(row, 6, status_item)

    def _on_jobs(self, jobs: list[PbsJob]) -> None:
        jobs = sorted(jobs, key=lambda j: (list(JOB_KIND_LABELS).index(j.kind), j.store, j.id))
        table = self._jobs_table
        table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            result = table_item(job.last_run_state or "Never run")
            if job.last_run_state and job.last_run_state != "OK":
                result.setForeground(FAILED_BRUSH)
                result.setToolTip(job.last_run_state)
            table.setItem(row, 0, table_item(JOB_KIND_LABELS.get(job.kind, job.kind)))
            table.setItem(row, 1, table_item(job.id if job.kind != "gc" else "—"))
            table.setItem(row, 2, table_item(job.target))
            table.setItem(row, 3, table_item(job.schedule or "Manual only"))
            table.setItem(row, 4, table_item(format_time(job.last_run_endtime)))
            table.setItem(row, 5, result)
            table.setItem(row, 6, table_item(format_time(job.next_run) if job.schedule else "—"))

    def _on_tasks(self, tasks: list[PbsTask]) -> None:
        # Failures first, then running, then the rest -- newest first within each.
        self._tasks = sorted(tasks, key=lambda t: (0 if t.failed else 1 if t.running else 2, -t.starttime))
        table = self._tasks_table
        table.setRowCount(len(self._tasks))
        for row, task in enumerate(self._tasks):
            status = table_item("Running" if task.running else task.status)
            if task.failed:
                status.setForeground(FAILED_BRUSH)
            elif task.status.startswith("WARNINGS"):
                status.setForeground(WARNING_BRUSH)
            table.setItem(row, 0, table_item(format_time(task.starttime)))
            table.setItem(row, 1, table_item(task.worker_type))
            table.setItem(row, 2, table_item(task.worker_id))
            table.setItem(row, 3, table_item(task.user))
            table.setItem(row, 4, status)

    def _show_task_log(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self._tasks):
            return
        task = self._tasks[row]

        def show(lines: list[str]) -> None:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Task log: {task.worker_type} {task.worker_id}".strip())
            view = QPlainTextEdit("\n".join(lines))
            view.setReadOnly(True)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(task.status or "Running"))
            layout.addWidget(view)
            layout.addWidget(buttons)
            dialog.resize(720, 420)
            dialog.exec()

        async_utils.run_in_background(
            lambda: pbs_client.get_task_log(self._host, self._secret, task.upid),
            on_result=show,
            on_error=self._on_error,
        )

    def close_session(self) -> None:
        self._timer.stop()

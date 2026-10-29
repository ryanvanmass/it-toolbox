"""A TrueNAS host's dashboard tab (Infrastructure module): Overview,
Storage, Datasets, Data protection, Shares, Apps and VMs, one sub-tab
each, over one websocket the tab opens and closes itself.

Every call runs in the background (core/async_utils) through _run/_job;
nothing here blocks the UI thread on the network. Live Overview figures
and app logs arrive on the client's reader thread and cross to the UI
thread through Qt signals.

Anything that changes the NAS asks first, naming what it touches.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import truenas_api as api
from it_toolbox.core import truenas_models as tm
from it_toolbox.core.truenas_client import TrueNasApiError, TrueNasConnection
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.remote_helper_widget import fill_table, make_table, selected_data

#: Sub-tab names, in order; also the tree's area items under a host.
AREAS = ("Overview", "Storage", "Datasets", "Data protection", "Shares", "Apps", "VMs")

DATA_ROLE = Qt.ItemDataRole.UserRole


def explain(error: Exception) -> str:
    """The message box text for a failed call."""
    if isinstance(error, TrueNasApiError) and error.is_permission_error:
        return (
            f"{error}\n\nThe API key's user doesn't have the role this needs. "
            "Viewing works with a read-only admin; changes need a full or sharing/storage admin."
        )
    return str(error)


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    answer = QMessageBox.question(parent, title, text)
    return answer == QMessageBox.StandardButton.Yes


def _row(*widgets: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch(1)
    return row


def _button(text: str, slot: Callable[[], None]) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(lambda _=False: slot())
    return button


def _yes(value: bool) -> str:
    return "Yes" if value else "No"


class LogDialog(QDialog):
    """A container's live log. Lines arrive on the client's reader thread."""

    line_received = Signal(str)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 520)
        self._stop: Callable[[], None] | None = None
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(buttons)
        self.line_received.connect(self.text.appendPlainText)

    def follow(self, stop: Callable[[], None]) -> None:
        self._stop = stop

    def done(self, result: int) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            async_utils.run_in_background(stop)
        super().done(result)


class TrueNasDashboardWidget(QWidget):
    stats_received = Signal(object)

    def __init__(
        self,
        name: str,
        open_connection: Callable[[], TrueNasConnection],
        web_url: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._open_connection = open_connection
        self._web_url = web_url.rstrip("/")
        self._connection: TrueNasConnection | None = None
        self._closed = False
        self._stop_realtime: Callable[[], None] | None = None
        self._log_dialogs: list[LogDialog] = []

        self._status = QLabel("Connecting…")
        self._status.setWordWrap(True)
        self._retry = _button("Retry", self.connect_to_nas)
        self._retry.setVisible(False)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_overview(), "Overview")
        self.tabs.addTab(self._build_storage(), "Storage")
        self.tabs.addTab(self._build_datasets(), "Datasets")
        self.tabs.addTab(self._build_protection(), "Data protection")
        self.tabs.addTab(self._build_shares(), "Shares")
        self.tabs.addTab(self._build_apps(), "Apps")
        self.tabs.addTab(self._build_vms(), "VMs")
        self.tabs.setEnabled(False)

        status_row = QHBoxLayout()
        status_row.addWidget(self._status, 1)
        status_row.addWidget(self._retry)
        layout = QVBoxLayout(self)
        layout.addLayout(status_row)
        layout.addWidget(self.tabs, 1)

        self.stats_received.connect(self._show_stats)
        self.connect_to_nas()

    # -- Connection --------------------------------------------------------------

    @property
    def connection(self) -> TrueNasConnection | None:
        return self._connection

    def show_area(self, area: str) -> None:
        if area in AREAS:
            self.tabs.setCurrentIndex(AREAS.index(area))

    def connect_to_nas(self) -> None:
        self._retry.setVisible(False)
        self._status.setText(f"Connecting to {self._name}…")

        def failed(error: Exception) -> None:
            if self._closed:
                return
            self._status.setText(f"Couldn't connect: {explain(error)}")
            self._retry.setVisible(True)

        async_utils.run_in_background(self._open_connection, on_result=self._on_connected, on_error=failed)

    def _on_connected(self, connection: TrueNasConnection) -> None:
        if self._closed:
            async_utils.run_in_background(connection.close)
            return
        self._connection = connection
        info = connection.system_info
        self._status.setText(f"Connected to {info.get('hostname') or self._name}, TrueNAS {info.get('version', '')}")
        self.tabs.setEnabled(True)
        self.reload_all()
        self._run(
            "",
            lambda c: api.follow_realtime(c, self.stats_received.emit),
            self._on_realtime_started,
            quiet=True,
        )

    def _on_realtime_started(self, stop: Callable[[], None]) -> None:
        if self._closed:
            async_utils.run_in_background(stop)
        else:
            self._stop_realtime = stop

    def reload_all(self) -> None:
        self._reload_overview()
        self._reload_storage()
        self._reload_datasets()
        self._reload_protection()
        self._reload_shares()
        self._reload_apps()
        self._reload_vms()

    def close_session(self) -> None:
        self._closed = True
        for dialog in self._log_dialogs:
            dialog.reject()
        connection, self._connection = self._connection, None
        stop, self._stop_realtime = self._stop_realtime, None

        def shut() -> None:
            if stop is not None:
                try:
                    stop()
                except Exception:  # noqa: BLE001 - closing anyway
                    pass
            if connection is not None:
                connection.close()

        async_utils.run_in_background(shut)

    def _run(self, message: str, fn, on_result=None, done: str = "", quiet: bool = False, on_error=None) -> None:
        """fn(connection) in the background, with a status bar message."""
        connection = self._connection
        if connection is None:
            return
        task = status_bar.begin(self, message) if message else None

        def ok(result) -> None:
            if task is not None:
                task.finish(done)
            if not self._closed and on_result is not None:
                on_result(result)

        def failed(error: Exception) -> None:
            if task is not None:
                task.finish()
            if self._closed:
                return
            if on_error is not None:
                on_error(error)
            if not quiet:
                QMessageBox.warning(self, f"TrueNAS: {self._name}", explain(error))

        async_utils.run_in_background(lambda: fn(connection), on_result=ok, on_error=failed)

    def _job(self, message: str, fn, on_result=None, done: str = "") -> None:
        """Like _run, for jobs: fn(connection, on_progress) drives the
        status bar's progress bar."""
        connection = self._connection
        if connection is None:
            return
        task = status_bar.begin(self, message)

        def progress(report) -> None:
            percent, description = report
            task.set_progress(percent)

        def ok(result) -> None:
            task.finish(done)
            if not self._closed and on_result is not None:
                on_result(result)

        def failed(error: Exception) -> None:
            task.finish()
            if not self._closed:
                QMessageBox.warning(self, f"TrueNAS: {self._name}", explain(error))

        async_utils.run_in_background_with_progress(
            lambda report: fn(connection, lambda p, d: report((p, d))),
            on_progress=progress,
            on_result=ok,
            on_error=failed,
        )

    # -- Overview ----------------------------------------------------------------

    def _build_overview(self) -> QWidget:
        widget = QWidget()
        self._info = {key: QLabel("") for key in ("hostname", "version", "model", "uptime", "cpu", "memory", "load")}
        info_form = QFormLayout()
        for key, label in (
            ("hostname", "Hostname:"),
            ("version", "Version:"),
            ("model", "Model:"),
            ("uptime", "Uptime:"),
            ("cpu", "CPU cores:"),
            ("memory", "Memory:"),
            ("load", "Load average:"),
        ):
            info_form.addRow(label, self._info[key])
        info_box = QGroupBox("System")
        info_box.setLayout(info_form)

        self._live = {key: QLabel("—") for key in ("cpu", "memory", "arc", "network", "disks")}
        live_form = QFormLayout()
        for key, label in (
            ("cpu", "CPU:"),
            ("memory", "Memory used:"),
            ("arc", "ZFS ARC:"),
            ("network", "Network:"),
            ("disks", "Disks:"),
        ):
            live_form.addRow(label, self._live[key])
        live_box = QGroupBox("Live")
        live_box.setLayout(live_form)

        self.alerts_table = make_table(["Level", "Alert", "Since"])
        self._dismiss_button = _button("Dismiss", self._dismiss_alert)

        layout = QVBoxLayout(widget)
        layout.addLayout(_row(info_box, live_box))
        layout.addWidget(QLabel("Alerts"))
        layout.addWidget(self.alerts_table, 1)
        layout.addLayout(_row(self._dismiss_button, _button("Refresh", self._reload_overview)))
        return widget

    def _reload_overview(self) -> None:
        self._run(
            "",
            lambda c: (api.get_overview(c), api.list_alerts(c)),
            self._show_overview,
            quiet=True,
            on_error=lambda e: self.alerts_table.setRowCount(0),
        )

    def _show_overview(self, result) -> None:
        overview, alerts = result
        self._info["hostname"].setText(overview.hostname)
        self._info["version"].setText(overview.version)
        self._info["model"].setText(overview.model)
        self._info["uptime"].setText(tm.format_duration(overview.uptime_seconds))
        self._info["cpu"].setText(str(overview.cores or ""))
        memory = tm.format_bytes(overview.physical_memory)
        if overview.ecc_memory is not None:
            memory += " (ECC)" if overview.ecc_memory else " (non-ECC)"
        self._info["memory"].setText(memory)
        self._info["load"].setText("  ".join(f"{x:.2f}" for x in overview.loadavg))
        self.alerts = alerts
        fill_table(
            self.alerts_table,
            [[a.level.title() + (" (dismissed)" if a.dismissed else ""), a.text, tm.format_time(a.when)] for a in alerts],
            alerts,
        )

    def _show_stats(self, stats: tm.RealtimeStats) -> None:
        if stats.cpu_percent is not None:
            self._live["cpu"].setText(f"{stats.cpu_percent:.0f}%")
        if stats.memory_used is not None:
            self._live["memory"].setText(
                f"{tm.format_bytes(stats.memory_used)} of {tm.format_bytes(stats.memory_total)}"
            )
        if stats.arc_size is not None:
            self._live["arc"].setText(tm.format_bytes(stats.arc_size))
        if stats.net_rx_bytes_per_sec is not None:
            self._live["network"].setText(
                f"↓ {tm.format_bytes(stats.net_rx_bytes_per_sec)}/s   ↑ {tm.format_bytes(stats.net_tx_bytes_per_sec)}/s"
            )
        if stats.disk_read_bytes_per_sec is not None:
            self._live["disks"].setText(
                f"read {tm.format_bytes(stats.disk_read_bytes_per_sec)}/s   "
                f"write {tm.format_bytes(stats.disk_write_bytes_per_sec)}/s"
            )

    def _dismiss_alert(self) -> None:
        alert = selected_data(self.alerts_table)
        if alert is None or alert.dismissed:
            return
        self._run("Dismissing alert…", lambda c: api.dismiss_alert(c, alert.uuid), lambda _: self._reload_overview())

    # -- Storage -----------------------------------------------------------------

    def _build_storage(self) -> QWidget:
        widget = QWidget()
        self.pools_table = make_table(["Pool", "Status", "Used", "Size", "Used %", "Last scrub", "Scrub errors"])
        self.pools_table.itemSelectionChanged.connect(self._show_topology)
        self.topology_tree = QTreeWidget()
        self.topology_tree.setHeaderLabels(["Device", "Type", "Status", "Read / write / checksum errors"])
        self.disks_table = make_table(["Disk", "Model", "Serial", "Size", "Type", "Pool", "Temp"])

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.pools_table)
        splitter.addWidget(self.topology_tree)
        splitter.addWidget(self.disks_table)

        layout = QVBoxLayout(widget)
        layout.addWidget(splitter, 1)
        layout.addLayout(
            _row(
                _button("Start Scrub", self._start_scrub),
                _button("Short SMART Test", lambda: self._smart_test("SHORT")),
                _button("Long SMART Test", lambda: self._smart_test("LONG")),
                _button("Refresh", self._reload_storage),
            )
        )
        return widget

    def _reload_storage(self) -> None:
        self._run("", lambda c: (api.list_pools(c), api.list_disks(c)), self._show_storage, quiet=True)

    def _show_storage(self, result) -> None:
        pools, disks = result
        self.pools = pools
        fill_table(
            self.pools_table,
            [
                [
                    p.name,
                    p.status,
                    tm.format_bytes(p.allocated),
                    tm.format_bytes(p.size),
                    f"{p.used_percent}%" if p.used_percent is not None else "",
                    tm.format_time(p.scan_end) if p.scan_function == "SCRUB" else "",
                    "" if p.scan_errors is None else str(p.scan_errors),
                ]
                for p in pools
            ],
            pools,
        )
        fill_table(
            self.disks_table,
            [
                [
                    d.name,
                    d.model,
                    d.serial,
                    tm.format_bytes(d.size),
                    d.kind,
                    d.pool,
                    f"{d.temperature} °C" if d.temperature is not None else "",
                ]
                for d in disks
            ],
            disks,
        )
        if pools:
            self.pools_table.selectRow(0)
        else:
            self.topology_tree.clear()

    def _show_topology(self) -> None:
        pool = selected_data(self.pools_table)
        self.topology_tree.clear()
        if pool is None:
            return

        def add(parent, device: tm.PoolDevice) -> None:
            errors = f"{device.read_errors} / {device.write_errors} / {device.checksum_errors}"
            item = QTreeWidgetItem([device.disk or device.name, device.kind.title(), device.status, errors])
            parent.addChild(item)
            for child in device.children:
                add(item, child)

        for role, vdevs in pool.topology.items():
            role_item = QTreeWidgetItem([role.title()])
            self.topology_tree.addTopLevelItem(role_item)
            for vdev in vdevs:
                add(role_item, vdev)
        self.topology_tree.expandAll()
        for column in range(4):
            self.topology_tree.resizeColumnToContents(column)

    def _start_scrub(self) -> None:
        pool = selected_data(self.pools_table)
        if pool is None:
            return
        if not _confirm(self, "Start Scrub", f"Start a scrub of pool {pool.name}? It reads every block and can take hours."):
            return
        self._job(
            f"Scrubbing {pool.name}…",
            lambda c, progress: api.start_scrub(c, pool.id, progress),
            lambda _: self._reload_storage(),
            done=f"Scrub of {pool.name} finished",
        )

    def _smart_test(self, kind: str) -> None:
        disk = selected_data(self.disks_table)
        if disk is None:
            return
        self._run(
            f"Starting {kind.lower()} SMART test on {disk.name}…",
            lambda c: api.run_smart_test(c, [disk.identifier], kind),
            done=f"{kind.title()} SMART test started on {disk.name}",
        )

    # -- Datasets ----------------------------------------------------------------

    def _build_datasets(self) -> QWidget:
        widget = QWidget()
        self.datasets_tree = QTreeWidget()
        self.datasets_tree.setHeaderLabels(["Dataset", "Used", "Available", "Quota", "Compression", "Encryption"])
        self.datasets_tree.itemSelectionChanged.connect(self._reload_snapshots)
        self.snapshots_table = make_table(["Snapshot", "Created", "Used", "Referenced"])
        self._snapshots_label = QLabel("Snapshots")

        snapshots = QWidget()
        snapshots_layout = QVBoxLayout(snapshots)
        snapshots_layout.setContentsMargins(0, 0, 0, 0)
        snapshots_layout.addWidget(self._snapshots_label)
        snapshots_layout.addWidget(self.snapshots_table, 1)
        snapshots_layout.addLayout(
            _row(
                _button("Take Snapshot…", self._take_snapshot),
                _button("Roll Back…", self._rollback_snapshot),
                _button("Clone…", self._clone_snapshot),
                _button("Delete…", self._delete_snapshot),
            )
        )

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.datasets_tree)
        splitter.addWidget(snapshots)

        layout = QVBoxLayout(widget)
        layout.addWidget(splitter, 1)
        layout.addLayout(_row(_button("Refresh", self._reload_datasets)))
        return widget

    def _reload_datasets(self) -> None:
        self._run("", api.list_datasets, self._show_datasets, quiet=True)

    def _show_datasets(self, datasets: list[tm.Dataset]) -> None:
        selected = self.selected_dataset()
        self.datasets_tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for dataset in datasets:
            if dataset.locked:
                encryption = "Locked"
            elif dataset.encrypted:
                encryption = "Unlocked"
            else:
                encryption = ""
            item = QTreeWidgetItem(
                [
                    dataset.short_name if dataset.parent in items else dataset.id,
                    tm.format_bytes(dataset.used),
                    tm.format_bytes(dataset.available),
                    tm.format_bytes(dataset.quota),
                    dataset.compression,
                    encryption,
                ]
            )
            item.setData(0, DATA_ROLE, dataset)
            item.setToolTip(0, dataset.mountpoint or dataset.id)
            parent = items.get(dataset.parent or "")
            if parent is not None:
                parent.addChild(item)
            else:
                self.datasets_tree.addTopLevelItem(item)
            items[dataset.id] = item
        self.datasets_tree.expandToDepth(0)
        for column in range(6):
            self.datasets_tree.resizeColumnToContents(column)
        if selected is not None and selected.id in items:
            self.datasets_tree.setCurrentItem(items[selected.id])

    def selected_dataset(self) -> tm.Dataset | None:
        item = self.datasets_tree.currentItem()
        return item.data(0, DATA_ROLE) if item is not None else None

    def _reload_snapshots(self) -> None:
        dataset = self.selected_dataset()
        if dataset is None:
            self.snapshots_table.setRowCount(0)
            self._snapshots_label.setText("Snapshots")
            return
        self._snapshots_label.setText(f"Snapshots of {dataset.id}")

        def show(snapshots: list[tm.Snapshot]) -> None:
            current = self.selected_dataset()
            if current is None or current.id != dataset.id:
                return  # selection moved on while loading
            fill_table(
                self.snapshots_table,
                [[s.name, tm.format_time(s.created), tm.format_bytes(s.used), tm.format_bytes(s.referenced)] for s in snapshots],
                snapshots,
            )

        self._run("", lambda c: api.list_snapshots(c, dataset.id), show, quiet=True)

    def _take_snapshot(self) -> None:
        dataset = self.selected_dataset()
        if dataset is None:
            return
        default = f"manual-{datetime.now():%Y-%m-%d_%H-%M}"
        name, ok = QInputDialog.getText(self, "Take Snapshot", f"Snapshot name for {dataset.id}:", text=default)
        name = name.strip()
        if not ok or not name:
            return
        self._run(
            f"Snapshotting {dataset.id}…",
            lambda c: api.create_snapshot(c, dataset.id, name),
            lambda _: self._reload_snapshots(),
            done=f"Took {dataset.id}@{name}",
        )

    def _rollback_snapshot(self) -> None:
        snapshot = selected_data(self.snapshots_table)
        if snapshot is None:
            return
        if not _confirm(
            self,
            "Roll Back",
            f"Roll {snapshot.dataset} back to {snapshot.name}?\n\n"
            "Every change made to the dataset since that snapshot is lost. "
            "TrueNAS refuses if newer snapshots exist; delete them first if you really mean it.",
        ):
            return
        self._run(
            f"Rolling {snapshot.dataset} back…",
            lambda c: api.rollback_snapshot(c, snapshot.id),
            lambda _: (self._reload_snapshots(), self._reload_datasets()),
            done=f"Rolled {snapshot.dataset} back to {snapshot.name}",
        )

    def _clone_snapshot(self) -> None:
        snapshot = selected_data(self.snapshots_table)
        if snapshot is None:
            return
        name, ok = QInputDialog.getText(
            self, "Clone Snapshot", f"New dataset for a clone of {snapshot.id}:", text=f"{snapshot.dataset}-clone"
        )
        name = name.strip()
        if not ok or not name:
            return
        self._run(
            f"Cloning {snapshot.id}…",
            lambda c: api.clone_snapshot(c, snapshot.id, name),
            lambda _: self._reload_datasets(),
            done=f"Cloned to {name}",
        )

    def _delete_snapshot(self) -> None:
        snapshot = selected_data(self.snapshots_table)
        if snapshot is None:
            return
        if not _confirm(self, "Delete Snapshot", f"Delete snapshot {snapshot.id}? This can't be undone."):
            return
        self._run(
            f"Deleting {snapshot.id}…",
            lambda c: api.delete_snapshot(c, snapshot.id),
            lambda _: self._reload_snapshots(),
            done=f"Deleted {snapshot.id}",
        )

    # -- Data protection ---------------------------------------------------------

    def _build_protection(self) -> QWidget:
        widget = QWidget()
        self.tasks_table = make_table(["Type", "Name", "What", "Schedule", "Enabled", "Last run", "Result"])
        self._missing_label = QLabel("")
        self._missing_label.setWordWrap(True)
        self.credentials_table = make_table(["Credential", "Type", "Target", "Used by"])

        tasks = QWidget()
        tasks_layout = QVBoxLayout(tasks)
        tasks_layout.setContentsMargins(0, 0, 0, 0)
        tasks_layout.addWidget(QLabel("Tasks"))
        tasks_layout.addWidget(self.tasks_table, 1)
        tasks_layout.addWidget(self._missing_label)
        tasks_layout.addLayout(
            _row(
                _button("Run Now", self._run_task),
                _button("Enable / Disable", self._toggle_task),
                _button("View Last Log", self._show_task_log),
            )
        )
        credentials = QWidget()
        credentials_layout = QVBoxLayout(credentials)
        credentials_layout.setContentsMargins(0, 0, 0, 0)
        credentials_layout.addWidget(QLabel("Remote credentials (SSH and cloud)"))
        credentials_layout.addWidget(self.credentials_table, 1)
        credentials_layout.addLayout(_row(_button("Test", self._test_credential)))

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(tasks)
        splitter.addWidget(credentials)

        layout = QVBoxLayout(widget)
        layout.addWidget(splitter, 1)
        layout.addLayout(_row(_button("Refresh", self._reload_protection)))
        return widget

    def _reload_protection(self) -> None:
        self._run(
            "",
            lambda c: (api.list_protection_tasks(c), api.list_credentials(c)),
            self._show_protection,
            quiet=True,
        )

    def _show_protection(self, result) -> None:
        (tasks, missing), credentials = result
        self.tasks = tasks
        fill_table(
            self.tasks_table,
            [
                [
                    t.kind_label,
                    t.name,
                    t.target,
                    t.schedule,
                    _yes(t.enabled),
                    tm.format_time(t.last_run),
                    (t.last_state.title() + (f": {t.last_error}" if t.last_error else "")) if t.last_state else "Never run",
                ]
                for t in tasks
            ],
            tasks,
        )
        self._missing_label.setText(
            f"Not available on this NAS: {', '.join(missing)}." if missing else ""
        )
        self._missing_label.setVisible(bool(missing))

        users: dict[tuple[str, int], list[str]] = {}
        for task in tasks:
            if task.credential_id is not None:
                source = "cloud" if task.kind in {"cloudsync", "cloud_backup"} else "keychain"
                users.setdefault((source, task.credential_id), []).append(task.name or task.kind_label)
        fill_table(
            self.credentials_table,
            [[c.name, c.kind, c.detail, ", ".join(users.get((c.source, c.id), []))] for c in credentials],
            credentials,
        )

    def _run_task(self) -> None:
        task = selected_data(self.tasks_table)
        if task is None:
            return
        if not task.can_run_now:
            QMessageBox.information(self, "Run Now", f"{task.kind_label} tasks only run on their schedule.")
            return
        if not _confirm(self, "Run Now", f"Run {task.kind_label.lower()} task {task.name!r} now?"):
            return
        self._run(
            f"Starting {task.name}…",
            lambda c: api.run_task(c, task),
            lambda _: self._reload_protection(),
            done=f"Started {task.name}",
        )

    def _toggle_task(self) -> None:
        task = selected_data(self.tasks_table)
        if task is None:
            return
        enable = not task.enabled
        verb = "Enable" if enable else "Disable"
        if not _confirm(self, f"{verb} Task", f"{verb} {task.kind_label.lower()} task {task.name!r}?"):
            return
        self._run(
            f"{verb[:-1]}ing {task.name}…",
            lambda c: api.set_task_enabled(c, task, enable),
            lambda _: self._reload_protection(),
            done=f"{verb}d {task.name}",
        )

    def _show_task_log(self) -> None:
        task = selected_data(self.tasks_table)
        if task is None:
            return
        if task.job_id is None:
            QMessageBox.information(self, "Last Log", f"{task.name} has no job in the NAS's history yet.")
            return

        def show(text: str) -> None:
            dialog = LogDialog(f"{task.kind_label}: {task.name}", self)
            dialog.text.setPlainText(text)
            dialog.show()

        self._run("Loading log…", lambda c: api.job_log(c, task.job_id), show)

    def _test_credential(self) -> None:
        credential = selected_data(self.credentials_table)
        if credential is None:
            return
        self._run(
            f"Testing {credential.name}…",
            lambda c: api.test_credential(c, credential),
            lambda verdict: QMessageBox.information(self, f"Test {credential.name}", verdict),
        )

    # -- Shares ------------------------------------------------------------------

    def _build_shares(self) -> QWidget:
        widget = QWidget()
        self.shares_table = make_table(["Protocol", "Share", "Path", "Enabled", "Comment"])
        self._services_label = QLabel("")
        layout = QVBoxLayout(widget)
        layout.addWidget(self.shares_table, 1)
        layout.addWidget(self._services_label)
        layout.addLayout(
            _row(
                _button("Enable / Disable", self._toggle_share),
                _button("Open in File Manager", self._open_share),
                _button("Restart SMB", lambda: self._restart_service("SMB")),
                _button("Restart NFS", lambda: self._restart_service("NFS")),
                _button("Refresh", self._reload_shares),
            )
        )
        return widget

    def _reload_shares(self) -> None:
        self._run("", api.list_shares, self._show_shares, quiet=True)

    def _show_shares(self, result) -> None:
        shares, services = result
        fill_table(
            self.shares_table,
            [[s.protocol, s.name, s.path, _yes(s.enabled), s.comment] for s in shares],
            shares,
        )
        parts = []
        for protocol, service_name in tm.SHARE_SERVICES.items():
            service = services.get(service_name)
            if service is not None:
                parts.append(f"{protocol} service: {'running' if service.running else 'stopped'}")
        self._services_label.setText("   ".join(parts))

    def _toggle_share(self) -> None:
        share = selected_data(self.shares_table)
        if share is None:
            return
        enable = not share.enabled
        verb = "Enable" if enable else "Disable"
        text = f"{verb} {share.protocol} share {share.name!r}?"
        if not enable:
            text += " Anyone using it is cut off."
        if not _confirm(self, f"{verb} Share", text):
            return
        self._run(
            f"{verb[:-1]}ing {share.name}…",
            lambda c: api.set_share_enabled(c, share, enable),
            lambda _: self._reload_shares(),
            done=f"{verb}d {share.name}",
        )

    def _open_share(self) -> None:
        share = selected_data(self.shares_table)
        if share is None:
            return
        host = QUrl(self._web_url).host() or self._name
        if share.protocol == "SMB":
            url = f"file://{host}/{share.name}" if sys.platform == "win32" else f"smb://{host}/{share.name}"
        else:
            url = f"nfs://{host}{share.path}"
        QDesktopServices.openUrl(QUrl(url))

    def _restart_service(self, protocol: str) -> None:
        service = tm.SHARE_SERVICES[protocol]
        if not _confirm(self, f"Restart {protocol}", f"Restart the {protocol} service? Open files on its shares are interrupted."):
            return
        self._job(
            f"Restarting {protocol}…",
            lambda c, progress: api.restart_service(c, service, progress),
            lambda _: self._reload_shares(),
            done=f"Restarted {protocol}",
        )

    # -- Apps --------------------------------------------------------------------

    def _build_apps(self) -> QWidget:
        widget = QWidget()
        self.apps_table = make_table(["App", "State", "Version", "Update", "Ports"])
        self.apps_table.itemDoubleClicked.connect(lambda _item: self._open_app())
        layout = QVBoxLayout(widget)
        layout.addWidget(self.apps_table, 1)
        layout.addLayout(
            _row(
                _button("Start", lambda: self._app_action("start")),
                _button("Stop", lambda: self._app_action("stop")),
                _button("Restart", lambda: self._app_action("restart")),
                _button("Update", self._update_app),
                _button("Logs…", self._app_logs),
                _button("Open Web UI", self._open_app),
                _button("Refresh", self._reload_apps),
            )
        )
        return widget

    def _reload_apps(self) -> None:
        self._run("", api.list_apps, self._show_apps, quiet=True)

    def _show_apps(self, apps: list[tm.App]) -> None:
        fill_table(
            self.apps_table,
            [
                [a.title, a.state.title(), a.version, "Available" if a.upgrade_available else "", ", ".join(a.ports)]
                for a in apps
            ],
            apps,
        )

    def _app_action(self, action: str) -> None:
        app = selected_data(self.apps_table)
        if app is None:
            return
        if action != "start" and not _confirm(self, action.title(), f"{action.title()} {app.title}?"):
            return
        verbs = {"start": "Starting", "stop": "Stopping", "restart": "Restarting"}
        self._job(
            f"{verbs[action]} {app.title}…",
            lambda c, progress: api.app_action(c, app.name, action, progress),
            lambda _: self._reload_apps(),
            done=f"{app.title}: {action} done",
        )

    def _update_app(self) -> None:
        app = selected_data(self.apps_table)
        if app is None:
            return
        if not app.upgrade_available:
            QMessageBox.information(self, "Update", f"{app.title} is up to date.")
            return
        if not _confirm(self, "Update", f"Update {app.title}? It restarts, and TrueNAS keeps a rollback snapshot."):
            return
        self._job(
            f"Updating {app.title}…",
            lambda c, progress: api.update_app(c, app.name, progress),
            lambda _: self._reload_apps(),
            done=f"Updated {app.title}",
        )

    def _app_logs(self) -> None:
        app = selected_data(self.apps_table)
        if app is None:
            return
        if not app.containers:
            QMessageBox.information(self, "Logs", f"{app.title} has no running containers.")
            return
        container = app.containers[0]
        if len(app.containers) > 1:
            labels = [f"{c.service} ({c.image})" for c in app.containers]
            label, ok = QInputDialog.getItem(self, "Logs", "Container:", labels, 0, False)
            if not ok:
                return
            container = app.containers[labels.index(label)]
        dialog = LogDialog(f"{app.title}: {container.service}", self)
        self._log_dialogs.append(dialog)
        dialog.finished.connect(lambda _r: self._log_dialogs.remove(dialog) if dialog in self._log_dialogs else None)
        dialog.show()

        def started(stop) -> None:
            if dialog.isVisible():
                dialog.follow(stop)
            else:
                async_utils.run_in_background(stop)

        self._run(
            "",
            lambda c: api.follow_app_logs(c, app.name, container.id, dialog.line_received.emit),
            started,
        )

    def _open_app(self) -> None:
        app = selected_data(self.apps_table)
        if app is None:
            return
        if not app.portals:
            QMessageBox.information(self, "Open Web UI", f"{app.title} doesn't publish a web UI.")
            return
        url = next(iter(app.portals.values()))
        # Portals often say 0.0.0.0 -- point them at the NAS instead.
        host = QUrl(self._web_url).host()
        if host:
            url = url.replace("0.0.0.0", host)
        QDesktopServices.openUrl(QUrl(url))

    # -- VMs ---------------------------------------------------------------------

    def _build_vms(self) -> QWidget:
        widget = QWidget()
        self.vms_table = make_table(["VM", "State", "vCPUs", "Memory", "Autostart", "Description"])
        layout = QVBoxLayout(widget)
        layout.addWidget(self.vms_table, 1)
        layout.addLayout(
            _row(
                _button("Start", lambda: self._vm_action("start")),
                _button("Shut Down", lambda: self._vm_action("stop")),
                _button("Power Off", lambda: self._vm_action("poweroff")),
                _button("Refresh", self._reload_vms),
            )
        )
        return widget

    def _reload_vms(self) -> None:
        self._run("", api.list_vms, self._show_vms, quiet=True)

    def _show_vms(self, vms: list[tm.Vm]) -> None:
        fill_table(
            self.vms_table,
            [
                [
                    v.name,
                    v.state.title(),
                    "" if v.vcpus is None else str(v.vcpus),
                    tm.format_bytes((v.memory_mib or 0) * 1024 * 1024) if v.memory_mib else "",
                    _yes(v.autostart),
                    v.description,
                ]
                for v in vms
            ],
            vms,
        )

    def _vm_action(self, action: str) -> None:
        vm = selected_data(self.vms_table)
        if vm is None:
            return
        if action == "stop" and not _confirm(self, "Shut Down", f"Shut down {vm.name}? The guest is asked to shut down cleanly."):
            return
        if action == "poweroff" and not _confirm(
            self, "Power Off", f"Power off {vm.name} immediately? Like pulling the plug: unsaved work in it is lost."
        ):
            return
        words = {"start": ("Starting", "Started"), "stop": ("Shutting down", "Shut down"), "poweroff": ("Powering off", "Powered off")}
        doing, did = words[action]
        self._job(
            f"{doing} {vm.name}…",
            lambda c, progress: api.vm_action(c, vm.id, action, progress),
            lambda _: self._reload_vms(),
            done=f"{did} {vm.name}",
        )

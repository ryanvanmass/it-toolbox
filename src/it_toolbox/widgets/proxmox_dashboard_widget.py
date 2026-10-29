"""Proxmox VE host dashboard and guest summary -- tabs opened from the
Infrastructure module's Proxmox root (see modules/infrastructure/proxmox.py).

Read-only (phase 1 of the Proxmox spec): every fetch goes through
core/proxmox_client.py in the background, nothing holds a connection
open, and the dashboard refreshes itself every REFRESH_MS while it is the
visible tab.
"""

import datetime

import shiboken6
from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import proxmox_client as pc
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.core.proxmox_models import (
    ClusterResources,
    GuestDetails,
    NodeStatus,
    ProxmoxGuest,
    ProxmoxTask,
    SdnOverview,
)

REFRESH_MS = 10_000


# -- Formatting ---------------------------------------------------------------


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_usage(used: int, total: int) -> str:
    if not total:
        return "—"
    return f"{format_bytes(used)} of {format_bytes(total)} ({used * 100 / total:.0f}%)"


def format_uptime(seconds: int) -> str:
    if not seconds:
        return "—"
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_time(timestamp: int | None) -> str:
    if not timestamp:
        return ""
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def format_cpu(fraction: float, cores: int) -> str:
    return f"{fraction * 100:.0f}% of {cores}" if cores else f"{fraction * 100:.0f}%"


STATE_LABELS = {"new": "new (pending)", "changed": "changed (pending)", "deleted": "deleted (pending)"}


SORT_ROLE = Qt.ItemDataRole.UserRole
KEY_ROLE = Qt.ItemDataRole.UserRole + 1


class _Table(QTableView):
    """A read-only, sortable table. Cells given as (text, sort value)
    sort by the value, so "1.5 GiB of 4.0 GiB" sorts by size. A Python
    QTableWidgetItem subclass would do the same but crashes PySide while
    sorting, hence a model + proxy."""

    def __init__(self, headers: list[str]) -> None:
        super().__init__()
        self._model = QStandardItemModel(0, len(headers))
        self._model.setHorizontalHeaderLabels(headers)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self.setModel(self._proxy)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)

    def rowCount(self) -> int:
        return self._proxy.rowCount()

    def item(self, row: int, column: int) -> QStandardItem:
        """The cell at a row as currently sorted."""
        return self._model.itemFromIndex(self._proxy.mapToSource(self._proxy.index(row, column)))

    def key(self, row: int):
        return self.item(row, 0).data(KEY_ROLE)

    def selected_key(self):
        rows = self.selectionModel().selectedRows()
        return self.key(rows[0].row()) if rows else None

    def fill(self, rows: list[list], keys: list | None = None) -> None:
        """Rows of cell values; a cell is a value or (text, sort value).
        `keys` (one per row) can be read back with key()/selected_key()."""
        self._model.setRowCount(0)
        for r, row in enumerate(rows):
            items = []
            for c, value in enumerate(row):
                text, sort = value if isinstance(value, tuple) else (value, value)
                item = QStandardItem("" if text is None else str(text))
                item.setData(sort, SORT_ROLE)
                if keys is not None and c == 0:
                    item.setData(keys[r], KEY_ROLE)
                items.append(item)
            self._model.appendRow(items)


def _table(headers: list[str]) -> _Table:
    return _Table(headers)


def _fill(table: _Table, rows: list[list], keys: list | None = None) -> None:
    table.fill(rows, keys)


class _LoadingMixin:
    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))


class ProxmoxDashboardWidget(QWidget, _LoadingMixin):
    """Summary (node + storage), Guests, Tasks and SDN tabs for one host."""

    def __init__(self, host: InfrastructureHost, secret: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self._secret = secret
        self._resources = ClusterResources()
        self._closed = False
        self._loading = False

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(lambda: self.reload())
        header = QHBoxLayout()
        self._title = QLabel(f"<b>{host.name}</b> — {host.url}")
        header.addWidget(self._title, 1)
        header.addWidget(refresh)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_summary_tab(), "Summary")
        self._tabs.addTab(self._build_guests_tab(), "Guests")
        self._tabs.addTab(self._build_tasks_tab(), "Tasks")
        self._tabs.addTab(self._build_sdn_tab(), "SDN")
        self._tabs.currentChanged.connect(lambda _i: self._reload_current_extra())

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._status)
        layout.addWidget(self._tabs, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start()
        self.reload()

    # -- Public ----------------------------------------------------------------

    def show_sdn(self) -> None:
        self._tabs.setCurrentWidget(self._sdn_tab)

    def close_session(self) -> None:
        self._closed = True
        self._timer.stop()

    def reload(self, automatic: bool = False) -> None:
        """`automatic` (the refresh timer) skips SDN, whose VNet-users
        column costs one config read per guest."""
        if self._loading or self._closed:
            return
        self._loading = True
        host, secret = self._host, self._secret

        def work():
            resources = pc.list_resources(host, secret)
            statuses = []
            for node in resources.nodes:
                if node.status == "online":
                    statuses.append(pc.get_node_status(host, secret, node.name))
            return resources, statuses

        async_utils.run_in_background(work, on_result=self._on_loaded, on_error=self._on_error)
        if not (automatic and self._tabs.currentWidget() is self._sdn_tab):
            self._reload_current_extra()

    # -- Loading ---------------------------------------------------------------

    def _alive(self) -> bool:
        return shiboken6.isValid(self) and not self._closed

    def _on_timer(self) -> None:
        if self.isVisible():
            self.reload(automatic=True)

    def _on_loaded(self, result) -> None:
        self._loading = False
        if not self._alive():
            return
        resources, statuses = result
        self._resources = resources
        self._set_status("")
        self._show_nodes(statuses)
        self._show_storage(resources)
        self._show_guests(resources)

    def _on_error(self, error: Exception) -> None:
        self._loading = False
        if self._alive():
            self._set_status(f"Couldn't load {self._host.name}: {error}")

    def _reload_current_extra(self) -> None:
        current = self._tabs.currentWidget()
        if current is self._tasks_tab:
            self._reload_tasks()
        elif current is self._sdn_tab:
            self._reload_sdn()

    # -- Summary ---------------------------------------------------------------

    def _build_summary_tab(self) -> QWidget:
        tab = QWidget()
        self._nodes_box = QVBoxLayout()
        self._storage_table = _table(["Storage", "Node", "Type", "Content", "Usage", "Status"])
        layout = QVBoxLayout(tab)
        layout.addLayout(self._nodes_box)
        layout.addWidget(QLabel("<b>Storage</b>"))
        layout.addWidget(self._storage_table, 1)
        return tab

    def _show_nodes(self, statuses: list[NodeStatus]) -> None:
        while self._nodes_box.count():
            widget = self._nodes_box.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        by_name = {s.node: s for s in statuses}
        for node in self._resources.nodes:
            self._nodes_box.addWidget(self._node_card(node.name, node.status, by_name.get(node.name)))

    @staticmethod
    def _bar(used: int, total: int) -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(used * 100 / total) if total else 0)
        bar.setFormat(format_usage(used, total))
        return bar

    def _node_card(self, name: str, state: str, status: NodeStatus | None) -> QGroupBox:
        box = QGroupBox(f"Node {name} — {state}")
        form = QFormLayout(box)
        if status is None:
            form.addRow(QLabel("No status (node offline)."))
            return box
        cpu = QProgressBar()
        cpu.setRange(0, 100)
        cpu.setValue(int(status.cpu * 100))
        cpu.setFormat(f"{status.cpu * 100:.0f}% of {status.cpus} CPUs")
        form.addRow("CPU:", cpu)
        form.addRow("Memory:", self._bar(status.mem_used, status.mem_total))
        form.addRow("Root disk:", self._bar(status.rootfs_used, status.rootfs_total))
        if status.swap_total:
            form.addRow("Swap:", self._bar(status.swap_used, status.swap_total))
        form.addRow("Load average:", QLabel(", ".join(status.loadavg)))
        form.addRow("Uptime:", QLabel(format_uptime(status.uptime)))
        form.addRow("Version:", QLabel(status.pve_version))
        form.addRow("Kernel:", QLabel(status.kernel))
        form.addRow("CPU model:", QLabel(status.cpu_model))
        return box

    def _show_storage(self, resources: ClusterResources) -> None:
        rows = [
            [
                s.storage,
                s.node,
                s.plugin,
                ", ".join(s.content),
                (format_usage(s.used, s.total), s.used / s.total if s.total else 0),
                s.status,
            ]
            for s in resources.storages
        ]
        _fill(self._storage_table, rows)

    # -- Guests ----------------------------------------------------------------

    def _build_guests_tab(self) -> QWidget:
        tab = QWidget()
        self._guest_table = _table(["ID", "Name", "Type", "Node", "Status", "CPU", "Memory", "Disk", "Uptime", "Tags"])
        layout = QVBoxLayout(tab)
        layout.addWidget(self._guest_table)
        return tab

    def _show_guests(self, resources: ClusterResources) -> None:
        rows = []
        for g in resources.guests:
            rows.append(
                [
                    g.vmid,
                    g.name,
                    ("template" if g.template else "CT" if g.is_container else "VM"),
                    g.node,
                    g.status,
                    (format_cpu(g.cpu, g.maxcpu), g.cpu),
                    (format_usage(g.mem, g.maxmem) if g.status == "running" else format_bytes(g.maxmem), g.mem),
                    (format_bytes(g.maxdisk), g.maxdisk),
                    (format_uptime(g.uptime), g.uptime),
                    "; ".join(g.tags),
                ]
            )
        _fill(self._guest_table, rows, keys=list(resources.guests))

    # -- Tasks -----------------------------------------------------------------

    def _build_tasks_tab(self) -> QWidget:
        self._tasks_tab = QWidget()
        self._task_table = _table(["Started", "Ended", "Node", "Type", "ID", "User", "Status"])
        self._task_table.selectionModel().selectionChanged.connect(lambda *_: self._on_task_selected())
        self._task_log = QPlainTextEdit()
        self._task_log.setReadOnly(True)
        self._task_log.setPlaceholderText("Select a task to see its log.")
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._task_table)
        splitter.addWidget(self._task_log)
        layout = QVBoxLayout(self._tasks_tab)
        layout.addWidget(splitter)
        return self._tasks_tab

    def _reload_tasks(self) -> None:
        host, secret = self._host, self._secret
        async_utils.run_in_background(
            lambda: pc.list_tasks(host, secret), on_result=self._on_tasks_loaded, on_error=self._on_error
        )

    def _on_tasks_loaded(self, tasks: list[ProxmoxTask]) -> None:
        if not self._alive():
            return
        rows = [
            [
                (format_time(t.starttime), t.starttime),
                (format_time(t.endtime) if t.endtime else "running", t.endtime or 0),
                t.node,
                t.type,
                t.id,
                t.user,
                "running" if t.running else t.status,
            ]
            for t in tasks
        ]
        _fill(self._task_table, rows, keys=tasks)
        self._task_table.sortByColumn(0, Qt.SortOrder.DescendingOrder)

    def _on_task_selected(self) -> None:
        task = self._task_table.selected_key()
        if task is None:
            return
        host, secret = self._host, self._secret
        self._task_log.setPlainText("Loading…")

        def shown(lines: list[str]) -> None:
            if self._alive():
                self._task_log.setPlainText("\n".join(lines))

        def failed(error: Exception) -> None:
            if self._alive():
                self._task_log.setPlainText(f"Couldn't load the log: {error}")

        async_utils.run_in_background(
            lambda: pc.get_task_log(host, secret, task.node, task.upid), on_result=shown, on_error=failed
        )

    # -- SDN -------------------------------------------------------------------

    def _build_sdn_tab(self) -> QWidget:
        self._sdn_tab = QWidget()
        self._sdn_pending = QLabel(
            "There are SDN changes that haven't been applied yet (marked pending below). "
            "Apply or revert them in the Proxmox web UI under Datacenter > SDN."
        )
        self._sdn_pending.setWordWrap(True)
        self._sdn_pending.setVisible(False)
        self._zone_table = _table(["Zone", "Type", "Bridge", "Node status", "State"])
        self._vnet_table = _table(["VNet", "Zone", "VLAN tag", "Alias", "Guests", "State"])
        self._subnet_table = _table(["Subnet", "VNet", "Gateway", "SNAT", "DHCP ranges", "State"])
        self._plugins = QLabel()
        self._plugins.setWordWrap(True)
        layout = QVBoxLayout(self._sdn_tab)
        layout.addWidget(self._sdn_pending)
        for title, table in (("Zones", self._zone_table), ("VNets", self._vnet_table), ("Subnets", self._subnet_table)):
            layout.addWidget(QLabel(f"<b>{title}</b>"))
            layout.addWidget(table, 1)
        layout.addWidget(self._plugins)
        return self._sdn_tab

    def _reload_sdn(self) -> None:
        host, secret = self._host, self._secret
        nodes = [n.name for n in self._resources.nodes if n.status == "online"]
        guests = list(self._resources.guests)

        def work():
            names = nodes or [n.name for n in pc.list_resources(host, secret).nodes]
            return pc.get_sdn(host, secret, names), pc.guests_by_bridge(host, secret, guests)

        async_utils.run_in_background(work, on_result=self._on_sdn_loaded, on_error=self._on_sdn_error)

    def _on_sdn_error(self, error: Exception) -> None:
        if self._alive():
            self._plugins.setText(f"Couldn't load SDN: {error}")

    def _on_sdn_loaded(self, result) -> None:
        if not self._alive():
            return
        sdn, users = result
        self.show_sdn_overview(sdn, users)

    def show_sdn_overview(self, sdn: SdnOverview, users: dict[str, list[str]]) -> None:
        self._sdn_pending.setVisible(sdn.has_pending)
        statuses: dict[str, list[str]] = {}
        for status in sdn.zone_status:
            statuses.setdefault(status.zone, []).append(f"{status.node}: {status.status}")
        _fill(
            self._zone_table,
            [[z.zone, z.type, z.bridge, ", ".join(statuses.get(z.zone, [])), STATE_LABELS.get(z.state, z.state)]
             for z in sdn.zones],
        )
        _fill(
            self._vnet_table,
            [[v.vnet, v.zone, ("", -1) if v.tag is None else v.tag, v.alias, ", ".join(users.get(v.vnet, [])),
              STATE_LABELS.get(v.state, v.state)] for v in sdn.vnets],
        )
        _fill(
            self._subnet_table,
            [[s.subnet, s.vnet, s.gateway, "yes" if s.snat else "", ", ".join(s.dhcp_ranges),
              STATE_LABELS.get(s.state, s.state)] for s in sdn.subnets],
        )
        parts = []
        for label, items, key in (("Controllers", sdn.controllers, "controller"), ("IPAMs", sdn.ipams, "ipam"),
                                  ("DNS", sdn.dns, "dns")):
            names = [f"{i.get(key, '?')} ({i.get('type', '?')})" for i in items]
            parts.append(f"{label}: {', '.join(names) if names else 'none'}")
        self._plugins.setText(" · ".join(parts) + " — read-only here; edit them in the Proxmox web UI.")


class ProxmoxGuestWidget(QWidget, _LoadingMixin):
    """One guest's summary: status, resources, config and IP addresses."""

    def __init__(self, host: InfrastructureHost, secret: str, guest: ProxmoxGuest, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self._secret = secret
        self._guest = guest
        self._closed = False

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(lambda: self.reload())
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>{guest.label}</b> on {guest.node}"), 1)
        header.addWidget(refresh)

        self._form = QFormLayout()
        self._interfaces = _table(["Interface", "MAC", "Addresses"])
        self._config = QPlainTextEdit()
        self._config.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._status)
        layout.addLayout(self._form)
        layout.addWidget(QLabel("<b>Network</b>"))
        layout.addWidget(self._interfaces, 1)
        layout.addWidget(QLabel("<b>Configuration</b>"))
        layout.addWidget(self._config, 2)
        self.reload()

    def close_session(self) -> None:
        self._closed = True

    def reload(self) -> None:
        host, secret, guest = self._host, self._secret, self._guest
        async_utils.run_in_background(
            lambda: pc.get_guest_details(host, secret, guest), on_result=self._on_loaded, on_error=self._on_error
        )

    def _on_error(self, error: Exception) -> None:
        if shiboken6.isValid(self) and not self._closed:
            self._set_status(f"Couldn't load {self._guest.label}: {error}")

    def _on_loaded(self, details: GuestDetails) -> None:
        if not shiboken6.isValid(self) or self._closed:
            return
        self._set_status("")
        self.show_details(details)

    def show_details(self, details: GuestDetails) -> None:
        g = details.guest
        while self._form.rowCount():
            self._form.removeRow(0)
        self._form.addRow("Status:", QLabel(g.status + (f" (locked: {g.lock})" if g.lock else "")))
        self._form.addRow("Type:", QLabel("Container (LXC)" if g.is_container else "Virtual machine (QEMU)"))
        self._form.addRow("CPU:", QLabel(format_cpu(g.cpu, g.maxcpu)))
        self._form.addRow("Memory:", QLabel(format_usage(g.mem, g.maxmem) if g.status == "running" else format_bytes(g.maxmem)))
        self._form.addRow("Uptime:", QLabel(format_uptime(g.uptime)))
        if not g.is_container:
            agent = {None: "not configured", True: "running", False: "not running"}[details.agent_running]
            self._form.addRow("Guest agent:", QLabel(agent))
            self._form.addRow("Display:", QLabel(str(details.config.get("vga", "default (VGA)"))))
            serial = details.config.get("serial0")
            self._form.addRow("Serial console:", QLabel(f"serial0: {serial}" if serial else "none"))
        if details.ipv4_addresses:
            ips = ", ".join(details.ipv4_addresses)
        elif not g.is_container and details.agent_running is not True:
            ips = "— (shown when the QEMU guest agent is running in the VM)"
        else:
            ips = details.interfaces_error or "—"
        self._form.addRow("IPv4:", QLabel(ips))
        _fill(self._interfaces, [[i.name, i.mac, ", ".join(i.addresses)] for i in details.interfaces])
        lines = [f"{k}: {v}" for k, v in sorted(details.config.items()) if k != "digest"]
        self._config.setPlainText("\n".join(lines))

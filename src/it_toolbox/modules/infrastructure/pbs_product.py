"""The Infrastructure module's "PBS" root: Proxmox Backup Server hosts.

Phase 1 is read-only. Under each host the tree mirrors PBS's own left
panel: datastores, then namespaces (only when a datastore has more than
the root one), then backup groups with their last backup's age.
Snapshots are too many for the tree, so a datastore opens its own tab
("PBS: <host> / <datastore>"); the host opens the dashboard.
"""

from dataclasses import dataclass

import shiboken6
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu, QTreeWidgetItem, QWidget

from it_toolbox.core import async_utils, pbs_client
from it_toolbox.core.pbs_models import BackupGroup, DatastoreUsage
from it_toolbox.modules.infrastructure.hosts import InfrastructureHost
from it_toolbox.modules.infrastructure.product import InfrastructureProduct
from it_toolbox.widgets.pbs_dashboard_widget import USAGE_WARNING, PbsDashboardWidget, format_age, format_bytes
from it_toolbox.widgets.pbs_datastore_widget import PbsDatastoreWidget

PLACEHOLDER = "Expand to load"


@dataclass(frozen=True)
class DatastoreNode:
    store: str


@dataclass(frozen=True)
class NamespaceNode:
    store: str
    ns: str


@dataclass(frozen=True)
class GroupNode:
    store: str
    ns: str
    label: str  # "vm/101"


@dataclass(frozen=True)
class TreeData:
    """Everything under one host, loaded in one background call."""

    datastores: list[DatastoreUsage]
    # (store, ns) -> groups; ns "" is the root namespace.
    groups: dict[tuple[str, str], list[BackupGroup]]
    # store -> namespaces, root first.
    namespaces: dict[str, list[str]]
    # store -> why its groups couldn't be listed.
    errors: dict[str, str]


def load_tree(host: InfrastructureHost, secret: str) -> TreeData:
    datastores = pbs_client.list_datastores(host, secret)
    groups: dict[tuple[str, str], list[BackupGroup]] = {}
    namespaces: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for store in datastores:
        if store.mount_status == "notmounted" or store.maintenance == "offline":
            continue  # PBS refuses reads; the tooltip says why
        try:
            names = pbs_client.list_namespaces(host, secret, store.store)
            namespaces[store.store] = names
            for ns in names:
                groups[(store.store, ns)] = pbs_client.list_groups(host, secret, store.store, ns)
        except pbs_client.PbsApiError as error:
            errors[store.store] = str(error)
    return TreeData(datastores, groups, namespaces, errors)


def datastore_label(store: DatastoreUsage) -> str:
    fraction = store.used_fraction
    return f"{store.store} ({fraction * 100:.0f}%)" if fraction is not None else store.store


def datastore_tooltip(store: DatastoreUsage) -> str:
    lines = [store.store]
    if store.comment:
        lines.append(store.comment)
    if store.used is not None and store.total:
        lines.append(f"{format_bytes(store.used)} of {format_bytes(store.total)} used")
    if store.backend_type == "s3":
        lines.append("S3 backend")
    if store.maintenance:
        lines.append(f"Maintenance mode: {store.maintenance}")
    if store.mount_status == "notmounted":
        lines.append("Removable datastore, not mounted")
    if store.error:
        lines.append(store.error)
    return "\n".join(lines)


def needs_attention(store: DatastoreUsage) -> bool:
    fraction = store.used_fraction
    return bool(store.error or store.maintenance or (fraction is not None and fraction >= USAGE_WARNING))


class PbsProduct(InfrastructureProduct):
    id = "pbs"
    display_name = "PBS"
    default_port = pbs_client.DEFAULT_PORT
    token_id_placeholder = "user@pbs!toolbox"
    url_placeholder = "https://pbs.lan:8007"
    token_help = (
        "Create the token in PBS under Configuration > Access Control > API Token. "
        "Read-only use needs DatastoreAudit on /datastore and Audit on /."
    )

    def __init__(self, view) -> None:
        super().__init__(view)
        # Host keys whose children are loading right now.
        self._loading: set[tuple] = set()

    def test_connection(self, host: InfrastructureHost, secret: str) -> str:
        return pbs_client.test_connection(host, secret)

    def create_dashboard(self, host: InfrastructureHost, secret: str) -> QWidget:
        return PbsDashboardWidget(host, secret)

    # -- Tree ------------------------------------------------------------------

    def fill_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        item.addChild(QTreeWidgetItem([PLACEHOLDER]))

    def on_host_expanded(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        # Load once per populate; Refresh forces a reload.
        if item.childCount() == 1 and item.child(0).text(0) == PLACEHOLDER:
            self._load(item, host)

    def refresh_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        self._load(item, host)

    def _load(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        if host.key in self._loading:
            return
        secret = self.view.secret_for(self, host)
        if secret is None:
            return
        self._loading.add(host.key)
        self._set_message(item, "Loading…")

        def done(data: TreeData) -> None:
            self._loading.discard(host.key)
            if shiboken6.isValid(item):
                self._fill(item, host, data)

        def failed(error: Exception) -> None:
            self._loading.discard(host.key)
            if shiboken6.isValid(item):
                self._set_message(item, f"Error: {error}")
                item.child(0).setToolTip(0, str(error))

        async_utils.run_in_background(lambda: load_tree(host, secret), on_result=done, on_error=failed)

    @staticmethod
    def _set_message(item: QTreeWidgetItem, text: str) -> None:
        item.takeChildren()
        item.addChild(QTreeWidgetItem([text]))

    def _fill(self, item: QTreeWidgetItem, host: InfrastructureHost, data: TreeData) -> None:
        item.takeChildren()
        if not data.datastores:
            item.addChild(QTreeWidgetItem(["(no datastores visible to this token)"]))
            return
        for store in data.datastores:
            store_item = self.view.make_item(self, host, datastore_label(store), DatastoreNode(store.store))
            store_item.setToolTip(0, datastore_tooltip(store))
            if needs_attention(store):
                store_item.setText(0, f"⚠ {store_item.text(0)}")
            item.addChild(store_item)
            if store.store in data.errors:
                store_item.addChild(QTreeWidgetItem([f"Error: {data.errors[store.store]}"]))
                continue
            names = data.namespaces.get(store.store, [""])
            if len(names) <= 1:
                self._add_groups(store_item, host, store.store, "", data.groups.get((store.store, ""), []))
                continue
            for ns in names:
                ns_item = self.view.make_item(self, host, ns or "(root)", NamespaceNode(store.store, ns))
                store_item.addChild(ns_item)
                self._add_groups(ns_item, host, store.store, ns, data.groups.get((store.store, ns), []))

    def _add_groups(self, parent: QTreeWidgetItem, host: InfrastructureHost, store: str, ns: str, groups: list[BackupGroup]) -> None:
        for group in groups:
            label = f"{group.label}  ·  {format_age(group.last_backup)}"
            if group.comment:
                label += f"  ·  {group.comment}"
            child = self.view.make_item(self, host, label, GroupNode(store, ns, group.label))
            child.setToolTip(
                0,
                f"{group.label}: {group.backup_count} snapshot{'s' if group.backup_count != 1 else ''}"
                + (f"\nOwner: {group.owner}" if group.owner else ""),
            )
            parent.addChild(child)

    # -- Actions ---------------------------------------------------------------

    def on_item_double_clicked(self, item: QTreeWidgetItem, host: InfrastructureHost, node) -> None:
        if isinstance(node, DatastoreNode):
            self.open_datastore(host, node.store)
        elif isinstance(node, NamespaceNode):
            self.open_datastore(host, node.store, node.ns)
        elif isinstance(node, GroupNode):
            self.open_datastore(host, node.store, node.ns, node.label)

    def add_item_actions(self, menu: QMenu, item: QTreeWidgetItem, host: InfrastructureHost, node) -> None:
        if isinstance(node, DatastoreNode):
            menu.addAction("Show Snapshots").triggered.connect(lambda: self.open_datastore(host, node.store))
            menu.addAction("Open Datastore in Web UI").triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl(datastore_web_url(host, node.store)))
            )
        elif isinstance(node, NamespaceNode):
            menu.addAction("Show Snapshots").triggered.connect(lambda: self.open_datastore(host, node.store, node.ns))
        elif isinstance(node, GroupNode):
            menu.addAction("Show Snapshots").triggered.connect(
                lambda: self.open_datastore(host, node.store, node.ns, node.label)
            )

    def open_datastore(self, host: InfrastructureHost, store: str, ns: str = "", search: str = "") -> None:
        secret = self.view.secret_for(self, host)
        if secret is None:
            return
        widget = self.view.open_tab(
            (self.id, host.key, "datastore", store),
            lambda: PbsDatastoreWidget(host, secret, store, ns, search),
            f"{self.display_name}: {host.name} / {store}",
            f"{host.url} — {store}",
        )
        # An already open tab is reused; point it at what was clicked.
        if isinstance(widget, PbsDatastoreWidget) and (widget.namespace != ns or search):
            widget.set_filter(ns, search)


def datastore_web_url(host: InfrastructureHost, store: str) -> str:
    """PBS's web UI routes by hash: #DataStore-<name> is that datastore's
    Summary/Content panel."""
    return f"{host.url.rstrip('/')}/#DataStore-{store}"

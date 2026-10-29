"""The Infrastructure module's Proxmox VE root.

Hosts are single nodes in practice, so guests sit directly under the
host; a host that turns out to be a cluster gets a node level instead.
Templates collect under one "Templates" child, and "SDN" opens the
dashboard's SDN tab. Phase 1 of the Proxmox spec is read-only: summaries,
the dashboard, and links into the Proxmox web UI.
"""

import shiboken6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu, QTreeWidgetItem

from it_toolbox.core import async_utils
from it_toolbox.core import proxmox_client as pc
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.core.proxmox_models import ClusterResources, ProxmoxGuest
from it_toolbox.modules.infrastructure.product import InfrastructureProduct
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.proxmox_dashboard_widget import ProxmoxDashboardWidget, ProxmoxGuestWidget

#: Tree node kinds (the first element of a child item's node tuple).
GUEST = "guest"
SDN = "sdn"
GROUP = "group"

#: Set on a host item once its guests are shown, so re-expanding doesn't reload.
LOADED_ROLE = Qt.ItemDataRole.UserRole + 90

STATUS_DOTS = {"running": "●", "paused": "◐", "suspended": "◐"}


class ProxmoxProduct(InfrastructureProduct):
    id = "proxmox"
    display_name = "Proxmox"
    default_port = pc.DEFAULT_PORT
    token_id_label = "Token ID:"
    token_id_placeholder = "root@pam!it-toolbox"
    secret_label = "Token secret:"
    url_placeholder = "https://pve1.lan:8006"
    token_help = (
        "Create the token under Datacenter > Permissions > API Tokens. Give it the PVEAuditor role "
        "on / for read-only use, or PVEVMAdmin on / to manage guests (plus PVESDNAdmin on /sdn for SDN)."
    )

    def __init__(self, view) -> None:
        super().__init__(view)
        self._loading: set[tuple] = set()

    # -- InfrastructureProduct -------------------------------------------------

    def test_connection(self, host: InfrastructureHost, secret: str) -> str:
        return pc.test_connection(host, secret)

    def create_dashboard(self, host: InfrastructureHost, secret: str):
        return ProxmoxDashboardWidget(host, secret)

    def fill_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        item.takeChildren()
        item.addChild(QTreeWidgetItem(["Expand to load guests"]))
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

    def on_host_expanded(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        if item.data(0, LOADED_ROLE):
            return
        self.load(item, host)

    def refresh_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        self.load(item, host)

    def on_item_double_clicked(self, item, host: InfrastructureHost, node) -> None:
        kind = node[0] if node else None
        if kind == GUEST:
            self.open_guest(host, node[1])
        elif kind == SDN:
            self.open_sdn(host)

    def add_item_actions(self, menu: QMenu, item, host: InfrastructureHost, node) -> None:
        kind = node[0] if node else None
        if kind == GUEST:
            guest: ProxmoxGuest = node[1]
            menu.addAction("Show Summary").triggered.connect(lambda: self.open_guest(host, guest))
            if not guest.template:
                menu.addAction("Open Console in Browser").triggered.connect(
                    lambda: QDesktopServices.openUrl(QUrl(pc.novnc_url(host, guest)))
                )
            menu.addAction("Open in Web UI").triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl(pc.guest_web_url(host, guest)))
            )
        elif kind == SDN:
            menu.addAction("Show SDN").triggered.connect(lambda: self.open_sdn(host))

    # -- Loading ---------------------------------------------------------------

    def load(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        if host.key in self._loading:
            return
        secret = self.view.secret_for(self, host)
        if secret is None:
            return
        self._loading.add(host.key)
        item.takeChildren()
        item.addChild(QTreeWidgetItem(["Loading…"]))
        task = status_bar.begin(self.view, f"Loading {host.name}…")

        def done(resources: ClusterResources) -> None:
            task.finish()
            self._loading.discard(host.key)
            target = self.view.host_item(self, host.key)
            if target is not None and shiboken6.isValid(target):
                self.show_resources(target, host, resources)

        def failed(error: Exception) -> None:
            task.finish()
            self._loading.discard(host.key)
            target = self.view.host_item(self, host.key)
            if target is None or not shiboken6.isValid(target):
                return
            target.takeChildren()
            error_item = QTreeWidgetItem([f"Couldn't connect: {error}"])
            error_item.setToolTip(0, str(error))
            target.addChild(error_item)

        async_utils.run_in_background(lambda: pc.list_resources(host, secret), on_result=done, on_error=failed)

    def show_resources(self, item: QTreeWidgetItem, host: InfrastructureHost, resources: ClusterResources) -> None:
        item.takeChildren()
        item.setData(0, LOADED_ROLE, True)
        clustered = len(resources.nodes) > 1
        parents: dict[str, QTreeWidgetItem] = {}
        for node in resources.nodes:
            if clustered:
                node_item = self.view.make_item(self, host, f"{node.name} ({node.status})", node=(GROUP, node.name))
                item.addChild(node_item)
                node_item.setExpanded(True)
                parents[node.name] = node_item
            else:
                parents[node.name] = item
        templates: dict[str, QTreeWidgetItem] = {}
        for guest in resources.guests:
            parent = parents.get(guest.node, item)
            if guest.template:
                group = templates.get(guest.node)
                if group is None:
                    group = self.view.make_item(self, host, "Templates", node=(GROUP, "templates"))
                    templates[guest.node] = group
                group.addChild(self._guest_item(host, guest))
                continue
            parent.addChild(self._guest_item(host, guest))
        for node_name, group in templates.items():
            parents.get(node_name, item).addChild(group)
        sdn = self.view.make_item(self, host, "SDN", node=(SDN, None))
        sdn.setToolTip(0, ", ".join(resources.sdn_zones) or "No SDN zones yet")
        item.addChild(sdn)
        if not resources.guests:
            item.insertChild(0, QTreeWidgetItem(["(no guests)"]))

    def _guest_item(self, host: InfrastructureHost, guest: ProxmoxGuest) -> QTreeWidgetItem:
        dot = STATUS_DOTS.get(guest.status, "○")
        label = guest.label if guest.template else f"{dot} {guest.label}"
        child = self.view.make_item(self, host, label, node=(GUEST, guest))
        tip = f"{guest.status}" + (f" · tags: {', '.join(guest.tags)}" if guest.tags else "")
        child.setToolTip(0, tip)
        return child

    # -- Tabs ------------------------------------------------------------------

    def open_guest(self, host: InfrastructureHost, guest: ProxmoxGuest) -> None:
        secret = self.view.secret_for(self, host)
        if secret is None:
            return
        self.view.open_tab(
            (self.id, host.key, GUEST, guest.key),
            lambda: ProxmoxGuestWidget(host, secret, guest),
            f"{self.display_name}: {guest.name}",
            f"{guest.label} on {host.name}",
        )

    def open_sdn(self, host: InfrastructureHost) -> None:
        dashboard = self.view.open_dashboard(self, host)
        if dashboard is not None:
            dashboard.show_sdn()


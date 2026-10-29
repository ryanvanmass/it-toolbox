"""What an Infrastructure product (Proxmox, TrueNAS, PBS, ...) plugs into
InfrastructureView.

The view owns everything the products have in common: the root item and
its "Add host…" child, the saved-host list, the add/edit dialog with
certificate pinning, the token prompt, and the host menu's Refresh / Open
web UI / Open SSH shell / Edit / Remove. A product only fills in what is
specific to it -- how to test a connection, what goes under a host, its
extra menu items, and its dashboard tab.

Products are listed in PRODUCT_CLASSES (modules/infrastructure/products.py),
in root order.
"""

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QMenu, QTreeWidgetItem, QWidget

from it_toolbox.core.infrastructure_hosts import InfrastructureHost

if TYPE_CHECKING:
    from it_toolbox.modules.infrastructure.ui.main_view import InfrastructureView


class InfrastructureProduct:
    #: Stable id: names the hosts file (<id>_hosts.json) and tags tree items.
    id: str
    #: Root label in the tree, and the tab-title prefix ("Proxmox: pve1").
    display_name: str
    #: Port assumed when a URL is typed without one.
    default_port: int = 443
    #: Add-host dialog labels. token_id_label None hides that field (TrueNAS).
    token_id_label: str | None = "Token ID:"
    token_id_placeholder: str = ""
    secret_label: str = "Token secret:"
    url_placeholder: str = "https://host"
    #: Shown under the dialog's fields, e.g. which role the token needs.
    token_help: str = ""

    def __init__(self, view: "InfrastructureView") -> None:
        self.view = view

    # -- Required --------------------------------------------------------------

    def test_connection(self, host: InfrastructureHost, secret: str) -> str:
        """Runs in the background. Returns a one-line summary for the
        dialog ("Proxmox VE 9.0.3, node pve1"); raises on failure."""
        raise NotImplementedError

    def create_dashboard(self, host: InfrastructureHost, secret: str) -> QWidget:
        """The host's dashboard tab. Its close_session() is called when
        the tab closes or the app quits."""
        raise NotImplementedError

    # -- Optional --------------------------------------------------------------

    def fill_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        """Adds placeholder children under a host item. Called on every
        repopulate; real content usually loads in on_host_expanded."""
        item.addChild(QTreeWidgetItem(["Expand to load"]))

    def on_host_expanded(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        """Called when the host item is expanded."""

    def refresh_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        """The host menu's Refresh. Defaults to reloading its children."""
        self.on_host_expanded(item, host)

    def on_item_double_clicked(self, item: QTreeWidgetItem, host: InfrastructureHost, node: Any) -> None:
        """A double-click on one of this product's own child items; `node`
        is whatever the product stored with view.make_item()."""

    def add_item_actions(self, menu: QMenu, item: QTreeWidgetItem, host: InfrastructureHost, node: Any) -> None:
        """Product-specific menu entries for a child item (or for the host
        itself, with node None) -- added above the shared host actions."""

    def close_all(self) -> None:
        """App is quitting; drop any live connections the product holds."""

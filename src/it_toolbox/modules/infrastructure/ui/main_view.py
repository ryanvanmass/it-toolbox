import shiboken6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import session_launcher, settings
from it_toolbox.modules.infrastructure.hosts import InfrastructureHost
from it_toolbox.modules.infrastructure.product import InfrastructureProduct
from it_toolbox.modules.infrastructure.products import PRODUCT_CLASSES
from it_toolbox.modules.infrastructure.ui.host_dialog import HostDialog

PRODUCT_ROLE = Qt.ItemDataRole.UserRole + 80
HOST_KEY_ROLE = Qt.ItemDataRole.UserRole + 81
IS_ADD_ITEM_ROLE = Qt.ItemDataRole.UserRole + 82
NODE_ROLE = Qt.ItemDataRole.UserRole + 83


class InfrastructureView(QWidget):
    """Appliances reached over their own HTTPS API -- Proxmox VE, TrueNAS,
    Proxmox Backup Server. One tree root per product (see products.py),
    each with an "Add host…" child and one node per saved host, laid out
    like the Cockpit module's machines. A host's dashboard, and anything
    else a product opens, goes into the shared session-tab pane.
    """

    def __init__(self, parent: QWidget | None = None, tabs: QTabWidget | None = None) -> None:
        super().__init__(parent)

        # Same shared/own tabs arrangement as CockpitView.
        self._owns_tabs = tabs is None
        self._tabs = tabs if tabs is not None else QTabWidget()
        if self._owns_tabs:
            self._tabs.setTabsClosable(True)
            self._tabs.tabCloseRequested.connect(
                lambda index: self.try_close_tab(self._tabs.widget(index))
            )

        self.products: list[InfrastructureProduct] = [cls(self) for cls in PRODUCT_CLASSES]
        # Secrets typed this session for hosts with none stored (never saved).
        self._session_secrets: dict[tuple[str, tuple], str] = {}
        self._open_tabs: dict[tuple, QWidget] = {}

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Infrastructure"])
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        layout = QVBoxLayout(self)
        if self._owns_tabs:
            layout.addWidget(self._tabs, 1)

        self.populate()

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close_all_sessions)

    @property
    def sidebar_tree(self) -> QTreeWidget:
        return self._tree

    @property
    def tabs(self) -> QTabWidget:
        return self._tabs

    def product(self, product_id: str) -> InfrastructureProduct | None:
        return next((p for p in self.products if p.id == product_id), None)

    # -- Saved hosts -------------------------------------------------------------

    def hosts(self, product: InfrastructureProduct) -> list[InfrastructureHost]:
        loaded = (InfrastructureHost.from_dict(d) for d in settings.load_infrastructure_hosts(product.id))
        return [host for host in loaded if host is not None]

    def host(self, product: InfrastructureProduct, key: tuple) -> InfrastructureHost | None:
        return next((h for h in self.hosts(product) if h.key == key), None)

    def _save(self, product: InfrastructureProduct, hosts: list[InfrastructureHost]) -> None:
        settings.save_infrastructure_hosts(product.id, [h.to_dict() for h in hosts])
        self.populate()

    def _with_secret(self, host: InfrastructureHost, secret: str | None) -> InfrastructureHost | None:
        """`host` with `secret` encrypted into it. With no SSH key to
        encrypt to, the secret is kept for this session only."""
        if secret is None:
            return host
        try:
            return host.with_changes(secret_encrypted=settings.encrypt_infrastructure_secret(secret))
        except settings.SecretDecryptionError as error:
            QMessageBox.warning(
                self,
                "Token Not Saved",
                f"{error}\n\nThe token will be used for this session only and asked for again next time.",
            )
            return host.with_changes(secret_encrypted=None)

    def add_host(self, product: InfrastructureProduct) -> None:
        dialog = HostDialog(product, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host = dialog.host()
        hosts = self.hosts(product)
        if any(h.key == host.key for h in hosts):
            QMessageBox.information(self, "Add Host", f"{host.url} is already in the list.")
            return
        saved = self._with_secret(host, dialog.secret())
        if saved.secret_encrypted is None and dialog.secret():
            self._session_secrets[(product.id, saved.key)] = dialog.secret()
        self._save(product, [*hosts, saved])
        item = self.host_item(product, saved.key)
        if item is not None:
            self._tree.setCurrentItem(item)

    def edit_host(self, product: InfrastructureProduct, key: tuple) -> None:
        hosts = self.hosts(product)
        index = next((i for i, h in enumerate(hosts) if h.key == key), None)
        if index is None:
            return
        old = hosts[index]
        dialog = HostDialog(product, old, stored_secret=lambda: self.secret_for(product, old), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = self._with_secret(dialog.host(), dialog.secret())
        if dialog.secret() and edited.secret_encrypted is None:
            self._session_secrets[(product.id, edited.key)] = dialog.secret()
        hosts[index] = edited
        self._save(product, hosts)

    def remove_host(self, product: InfrastructureProduct, key: tuple) -> None:
        hosts = self.hosts(product)
        host = next((h for h in hosts if h.key == key), None)
        if host is None:
            return
        confirmed = QMessageBox.question(
            self, "Remove Host", f"Remove {host.name}? Nothing on the host changes."
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._session_secrets.pop((product.id, key), None)
        self._save(product, [h for h in hosts if h.key != key])

    def secret_for(self, product: InfrastructureProduct, host: InfrastructureHost) -> str | None:
        """The host's token: decrypted from storage, else typed earlier this
        session, else asked for now. None if the user cancels."""
        cache_key = (product.id, host.key)
        if cache_key in self._session_secrets:
            return self._session_secrets[cache_key]
        if host.secret_encrypted is not None:
            try:
                secret = settings.decrypt_infrastructure_secret(host.secret_encrypted)
            except settings.SecretDecryptionError:
                pass  # fall through to the prompt
            else:
                self._session_secrets[cache_key] = secret
                return secret
        secret, ok = QInputDialog.getText(
            self,
            f"{product.display_name} Token",
            f"{product.secret_label} for {host.name}:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not secret.strip():
            return None
        self._session_secrets[cache_key] = secret.strip()
        return secret.strip()

    # -- Tree ------------------------------------------------------------------

    def populate(self) -> None:
        expanded = self._expanded_keys()
        self._tree.clear()
        if not self.products:
            self._tree.addTopLevelItem(QTreeWidgetItem(["(no products available yet)"]))
            return
        for product in self.products:
            root = QTreeWidgetItem([product.display_name])
            root.setData(0, PRODUCT_ROLE, product.id)
            self._tree.addTopLevelItem(root)
            add_item = QTreeWidgetItem(["Add host…"])
            add_item.setData(0, PRODUCT_ROLE, product.id)
            add_item.setData(0, IS_ADD_ITEM_ROLE, True)
            root.addChild(add_item)
            for host in self.hosts(product):
                item = QTreeWidgetItem([host.name])
                item.setToolTip(0, host.url)
                item.setData(0, PRODUCT_ROLE, product.id)
                item.setData(0, HOST_KEY_ROLE, host.key)
                root.addChild(item)
                product.fill_host(item, host)
                if (product.id, host.key) in expanded:
                    item.setExpanded(True)
            root.setExpanded(True)

    def _expanded_keys(self) -> set[tuple]:
        keys = set()
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            for j in range(root.childCount()):
                child = root.child(j)
                if child.isExpanded() and child.data(0, HOST_KEY_ROLE) is not None:
                    keys.add((child.data(0, PRODUCT_ROLE), child.data(0, HOST_KEY_ROLE)))
        return keys

    def host_item(self, product: InfrastructureProduct, key: tuple) -> QTreeWidgetItem | None:
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            if root.data(0, PRODUCT_ROLE) != product.id:
                continue
            for j in range(root.childCount()):
                child = root.child(j)
                if child.data(0, HOST_KEY_ROLE) == key:
                    return child
        return None

    @staticmethod
    def make_item(product: InfrastructureProduct, host: InfrastructureHost, label: str, node=None) -> QTreeWidgetItem:
        """A child item under a host, tagged so double-clicks and menus on
        it reach `product` with `node` (any value the product chooses)."""
        item = QTreeWidgetItem([label])
        item.setData(0, PRODUCT_ROLE, product.id)
        item.setData(0, HOST_KEY_ROLE, host.key)
        item.setData(0, NODE_ROLE, node)
        return item

    def _resolve(self, item: QTreeWidgetItem | None):
        """(product, host, node) for an item; any of them None."""
        if item is None or not shiboken6.isValid(item):
            return None, None, None
        product = self.product(item.data(0, PRODUCT_ROLE) or "")
        key = item.data(0, HOST_KEY_ROLE)
        host = self.host(product, key) if product is not None and key is not None else None
        return product, host, item.data(0, NODE_ROLE)

    def _is_host_item(self, item: QTreeWidgetItem) -> bool:
        return item.data(0, HOST_KEY_ROLE) is not None and item.data(0, NODE_ROLE) is None and (
            item.parent() is not None and item.parent().parent() is None
        )

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        product, host, _node = self._resolve(item)
        if product is not None and host is not None and self._is_host_item(item):
            product.on_host_expanded(item, host)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        product, host, node = self._resolve(item)
        if product is None:
            return
        if item.data(0, IS_ADD_ITEM_ROLE):
            self.add_host(product)
        elif host is not None and self._is_host_item(item):
            self.open_dashboard(product, host)
        elif host is not None:
            product.on_item_double_clicked(item, host, node)

    # -- Menus -------------------------------------------------------------------

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking the module's entry in the app sidebar."""
        menu = QMenu(parent)
        for product in self.products:
            menu.addAction(f"Add {product.display_name} Host…").triggered.connect(
                lambda _=False, p=product: self.add_host(p)
            )
        return menu

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        product, host, node = self._resolve(item)
        if product is None:
            return
        menu = QMenu(self)
        if host is not None:
            before = len(menu.actions())
            product.add_item_actions(menu, item, host, None if self._is_host_item(item) else node)
            if len(menu.actions()) > before:
                menu.addSeparator()
            self.add_host_actions(menu, product, host)
            menu.addSeparator()
        menu.addAction("Add host…").triggered.connect(lambda: self.add_host(product))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def add_host_actions(self, menu: QMenu, product: InfrastructureProduct, host: InfrastructureHost) -> None:
        menu.addAction("Open Dashboard").triggered.connect(lambda: self.open_dashboard(product, host))
        menu.addAction("Refresh").triggered.connect(lambda: self._refresh(product, host))
        menu.addAction("Open Web UI").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(host.url))
        )
        menu.addAction("Open SSH Shell").triggered.connect(lambda: self.open_ssh_shell(host))
        menu.addSeparator()
        menu.addAction("Edit…").triggered.connect(lambda: self.edit_host(product, host.key))
        menu.addAction("Remove").triggered.connect(lambda: self.remove_host(product, host.key))

    def _refresh(self, product: InfrastructureProduct, host: InfrastructureHost) -> None:
        item = self.host_item(product, host.key)
        if item is not None:
            product.refresh_host(item, host)
            item.setExpanded(True)

    def open_ssh_shell(self, host: InfrastructureHost) -> None:
        try:
            session_launcher.launch_ssh(host.hostname, 22, host.ssh_username)
        except (session_launcher.SessionLaunchError, OSError) as error:
            QMessageBox.warning(self, "Open SSH Shell", str(error))

    # -- Tabs ------------------------------------------------------------------

    def open_dashboard(self, product: InfrastructureProduct, host: InfrastructureHost) -> QWidget | None:
        secret = self.secret_for(product, host)
        if secret is None:
            return None
        return self.open_tab(
            (product.id, host.key, "dashboard"),
            lambda: product.create_dashboard(host, secret),
            f"{product.display_name}: {host.name}",
            host.url,
        )

    def open_tab(self, tab_key: tuple, create, title: str, tooltip: str = "") -> QWidget:
        """Opens (or switches to) a tab. `create` builds the widget, which
        must have close_session()."""
        existing = self._open_tabs.get(tab_key)
        if existing is not None and shiboken6.isValid(existing):
            self._tabs.setCurrentWidget(existing)
            return existing
        widget = create()
        self._open_tabs[tab_key] = widget
        index = self._tabs.addTab(widget, title)
        if tooltip:
            self._tabs.setTabToolTip(index, tooltip)
        self._tabs.setCurrentIndex(index)
        return widget

    def try_close_tab(self, widget: QWidget) -> bool:
        """See ToolModule.try_close_tab."""
        tab_key = next((k for k, w in self._open_tabs.items() if w is widget), None)
        if tab_key is None:
            return False
        index = self._tabs.indexOf(widget)
        if index != -1:
            self._tabs.removeTab(index)
        del self._open_tabs[tab_key]
        widget.close_session()
        widget.deleteLater()
        return True

    def close_all_sessions(self) -> None:
        for widget in list(self._open_tabs.values()):
            if shiboken6.isValid(widget):
                widget.close_session()
        for product in self.products:
            product.close_all()

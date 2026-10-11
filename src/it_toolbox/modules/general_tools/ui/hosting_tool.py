from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QMenu,
    QMessageBox,
    QTabWidget,
    QTreeWidgetItem,
    QWidget,
)

from it_toolbox.core import settings
from it_toolbox.core.hosting_manager import HostingServer
from it_toolbox.widgets.hosting_manager_widget import HostingManagerWidget
from it_toolbox.widgets.remote_helper_widget import ServerDialog

SERVER_INDEX_ROLE = Qt.ItemDataRole.UserRole + 30
IS_ADD_ITEM_ROLE = Qt.ItemDataRole.UserRole + 31


class HostingTool:
    """The Hosting Manager entry under General Tools: its sidebar node
    lists "Add Server…" and the saved servers, and each opened server gets
    a manager tab in the shared session-tab pane (opening one that's
    already open switches to it). Works alongside the cockpit-hosting
    Cockpit module on the same server -- see core/hosting_manager.py.
    """

    name = "Hosting Manager"

    def __init__(self, view: QWidget, tabs: QTabWidget) -> None:
        self._view = view
        self._tabs = tabs
        self._owned_tab_widgets: set[HostingManagerWidget] = set()
        self.item = QTreeWidgetItem([self.name])
        self.refresh_servers()

    # -- Saved servers ----------------------------------------------------

    def servers(self) -> list[HostingServer]:
        loaded = (HostingServer.from_dict(d) for d in settings.load_hosting_servers())
        return [server for server in loaded if server is not None]

    def _save(self, servers: list[HostingServer]) -> None:
        settings.save_hosting_servers([server.to_dict() for server in servers])
        self.refresh_servers()

    def refresh_servers(self) -> None:
        self.item.takeChildren()
        add_item = QTreeWidgetItem(["Add Server…"])
        add_item.setData(0, IS_ADD_ITEM_ROLE, True)
        self.item.addChild(add_item)
        for index, server in enumerate(self.servers()):
            item = QTreeWidgetItem([server.name])
            item.setToolTip(0, server.target)
            item.setData(0, SERVER_INDEX_ROLE, index)
            self.item.addChild(item)

    def _dialog(self, server: HostingServer | None = None) -> ServerDialog:
        return ServerDialog(self.name, HostingServer, server, parent=self._view)

    def add_server(self) -> None:
        dialog = self._dialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        server = dialog.server()
        self._save([*self.servers(), server])
        self.open_server(server)

    def _edit_server(self, index: int) -> None:
        servers = self.servers()
        dialog = self._dialog(servers[index])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        servers[index] = dialog.server()
        self._save(servers)

    def _remove_server(self, index: int) -> None:
        servers = self.servers()
        confirmed = QMessageBox.question(
            self._view,
            "Remove Server",
            f"Remove {servers[index].name} from the Hosting Manager? Nothing on the server changes.",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        del servers[index]
        self._save(servers)

    # -- Sidebar ----------------------------------------------------------

    def add_category_actions(self, menu: QMenu) -> None:
        """Actions for this tool's own node, and for the General Tools
        entry's context menu."""
        menu.addAction("Add Hosting Server…").triggered.connect(self.add_server)

    def add_item_actions(self, menu: QMenu, item: QTreeWidgetItem) -> None:
        index = item.data(0, SERVER_INDEX_ROLE)
        if index is not None:
            menu.addAction("Open").triggered.connect(lambda: self.open_server(self.servers()[index]))
            menu.addAction("Edit…").triggered.connect(lambda: self._edit_server(index))
            menu.addAction("Remove").triggered.connect(lambda: self._remove_server(index))
            menu.addSeparator()
        self.add_category_actions(menu)

    def activate(self, item: QTreeWidgetItem) -> None:
        if item.data(0, IS_ADD_ITEM_ROLE):
            self.add_server()
            return
        index = item.data(0, SERVER_INDEX_ROLE)
        if index is not None:
            self.open_server(self.servers()[index])

    # -- Tabs -------------------------------------------------------------

    def open_server(self, server: HostingServer) -> HostingManagerWidget:
        for widget in self._owned_tab_widgets:
            if widget.server == server:
                self._tabs.setCurrentWidget(widget)
                return widget
        manager = HostingManagerWidget(server)
        self._owned_tab_widgets.add(manager)
        index = self._tabs.addTab(manager, f"Hosting: {server.name}")
        self._tabs.setTabToolTip(index, server.target)
        self._tabs.setCurrentIndex(index)
        return manager

    def try_close_tab(self, widget: QWidget) -> bool:
        if widget not in self._owned_tab_widgets:
            return False
        index = self._tabs.indexOf(widget)
        if index != -1:
            self._tabs.removeTab(index)
        self._owned_tab_widgets.discard(widget)
        widget.close_session()
        widget.deleteLater()
        return True

    def close_all_sessions(self) -> None:
        for widget in list(self._owned_tab_widgets):
            widget.close_session()

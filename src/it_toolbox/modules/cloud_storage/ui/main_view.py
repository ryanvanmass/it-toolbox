from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMenu,
    QMessageBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, rclone_client
from it_toolbox.modules.cloud_storage.models import RemoteConfig

REMOTE_ROLE = Qt.ItemDataRole.UserRole
IS_REMOTES_ROOT_ROLE = Qt.ItemDataRole.UserRole + 1


class CloudStorageView(QWidget):
    """Configures and browses rclone remotes — the third connection
    family alongside Connection Manager's gcloud tree and Shell
    Launcher's local shells. Mirrors ConnectionManagerView's shape: a
    sidebar tree (here, a single "Remotes" root since there's only one
    connection family) and browse tabs in the shared session-tab pane.
    """

    def __init__(self, parent: QWidget | None = None, tabs: QTabWidget | None = None) -> None:
        super().__init__(parent)

        # A shared tabs widget (injected by CloudStorageModule/MainWindow
        # in the real app) is owned and wired up centrally — see
        # MainWindow._on_session_tab_close_requested / _changed.
        # Standalone/test usage (tabs=None) stays fully self-contained.
        self._owns_tabs = tabs is None
        self._tabs = tabs if tabs is not None else QTabWidget()
        if self._owns_tabs:
            self._tabs.setTabsClosable(True)
            self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
            self._tabs.currentChanged.connect(self._on_tab_changed)
        self._owned_tab_widgets: set[QWidget] = set()

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Remotes"])
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        layout = QVBoxLayout(self)
        if self._owns_tabs:
            layout.addWidget(self._tabs, 1)

        self._remotes_root = QTreeWidgetItem(["Remotes"])
        self._remotes_root.setData(0, IS_REMOTES_ROOT_ROLE, True)
        self._tree.addTopLevelItem(self._remotes_root)
        self._remotes_root.setExpanded(True)

        self.refresh_remotes()

    @property
    def sidebar_tree(self) -> QTreeWidget:
        """The remotes browser, hosted in the app sidebar nested under
        this module's entry — see CloudStorageModule.create_sidebar_widget().
        """
        return self._tree

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking this module's entry in the app
        sidebar — see CloudStorageModule.build_context_menu().
        """
        menu = QMenu(parent)
        menu.addAction("Refresh").triggered.connect(self.refresh_remotes)
        return menu

    # -- Remotes tree ---------------------------------------------------

    def refresh_remotes(self) -> None:
        if not rclone_client.is_available():
            self._remotes_root.takeChildren()
            placeholder = QTreeWidgetItem(
                [f"rclone CLI not found — install it from {rclone_client.INSTALL_URL}"]
            )
            self._remotes_root.addChild(placeholder)
            return
        async_utils.run_in_background(
            rclone_client.list_remotes,
            on_result=self._populate_remotes,
            on_error=self._on_load_error,
        )

    def _populate_remotes(self, remotes: list[RemoteConfig]) -> None:
        self._remotes_root.takeChildren()
        for remote in remotes:
            item = QTreeWidgetItem([f"{remote.name} ({remote.type})"])
            item.setData(0, REMOTE_ROLE, remote)
            self._remotes_root.addChild(item)

    def _on_load_error(self, error: Exception) -> None:
        QMessageBox.warning(self, "Failed to load remotes", str(error))

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return

        if item.data(0, IS_REMOTES_ROOT_ROLE):
            menu = QMenu(self)
            menu.addAction("Refresh").triggered.connect(self.refresh_remotes)
            menu.exec(self._tree.viewport().mapToGlobal(pos))
            return

        remote = item.data(0, REMOTE_ROLE)
        if remote is None:
            return
        menu = QMenu(self)
        remove_action = menu.addAction("Remove")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is remove_action:
            self._remove_remote(remote)

    def _remove_remote(self, remote: RemoteConfig) -> None:
        confirmed = QMessageBox.question(
            self,
            "Remove Remote",
            f'Remove the remote "{remote.name}"? This only removes it from '
            "rclone's configuration — no data is deleted.",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        async_utils.run_in_background(
            lambda: rclone_client.delete_remote(remote.name),
            on_result=lambda _: self.refresh_remotes(),
            on_error=self._on_load_error,
        )

    # -- Tabs -------------------------------------------------------------

    def try_close_tab(self, widget: QWidget) -> bool:
        """Tear down `widget` if this view added it to (possibly shared)
        self._tabs, and report whether it did — see ToolModule.try_close_tab
        and MainWindow._on_session_tab_close_requested.
        """
        if widget not in self._owned_tab_widgets:
            return False
        index = self._tabs.indexOf(widget)
        if index != -1:
            self._tabs.removeTab(index)
        self._owned_tab_widgets.discard(widget)
        widget.deleteLater()
        return True

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self.try_close_tab(widget)

    def _on_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if widget is not None:
            widget.setFocus()

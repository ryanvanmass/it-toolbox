from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QMenu,
    QMessageBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, rclone_client, settings
from it_toolbox.modules.cloud_storage.models import RemoteConfig
from it_toolbox.modules.cloud_storage.ui.add_remote_dialog import AddRemoteDialog
from it_toolbox.widgets.rclone_browser_widget import RcloneBrowserWidget

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
        self._tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)

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
        override = settings.load_rclone_path()
        label = "Change rclone Location…" if override else "Set rclone Location…"
        menu.addAction(label).triggered.connect(self._on_set_rclone_path_clicked)
        if override:
            menu.addAction("Use rclone from PATH").triggered.connect(
                self._on_clear_rclone_path_clicked
            )
        menu.addAction("Refresh").triggered.connect(self.refresh_remotes)
        return menu

    def _on_set_rclone_path_clicked(self) -> None:
        current = settings.load_rclone_path() or ""
        path, _ = QFileDialog.getOpenFileName(self, "Locate the rclone executable", current)
        if not path:
            return
        settings.save_rclone_path(path)
        self.refresh_remotes()

    def _on_clear_rclone_path_clicked(self) -> None:
        settings.save_rclone_path(None)
        self.refresh_remotes()

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
        # list_remotes() already sorts by name case-insensitively, so
        # grouping preserves that order within each type's children —
        # only the type-category order below needs its own sort.
        by_type: dict[str, list[RemoteConfig]] = {}
        for remote in remotes:
            by_type.setdefault(remote.type, []).append(remote)
        for remote_type in sorted(by_type, key=str.lower):
            category_item = QTreeWidgetItem([remote_type])
            self._remotes_root.addChild(category_item)
            category_item.setExpanded(True)
            for remote in by_type[remote_type]:
                item = QTreeWidgetItem([remote.name])
                item.setData(0, REMOTE_ROLE, remote)
                category_item.addChild(item)

    def _on_load_error(self, error: Exception) -> None:
        QMessageBox.warning(self, "Failed to load remotes", str(error))

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return

        if item.data(0, IS_REMOTES_ROOT_ROLE):
            menu = QMenu(self)
            menu.addAction("Add Remote…").triggered.connect(self._on_add_remote_clicked)
            menu.addAction("Refresh").triggered.connect(self.refresh_remotes)
            menu.exec(self._tree.viewport().mapToGlobal(pos))
            return

        remote = item.data(0, REMOTE_ROLE)
        if remote is None:
            return
        menu = QMenu(self)
        browse_action = menu.addAction("Browse")
        remove_action = menu.addAction("Remove")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is browse_action:
            self._open_browser(remote)
        elif chosen is remove_action:
            self._remove_remote(remote)

    def _on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        remote = item.data(0, REMOTE_ROLE)
        if remote is not None:
            self._open_browser(remote)

    def _open_browser(self, remote: RemoteConfig) -> None:
        browser = RcloneBrowserWidget(remote.name)
        self._owned_tab_widgets.add(browser)
        index = self._tabs.addTab(browser, remote.name)
        self._tabs.setCurrentIndex(index)

    def _on_add_remote_clicked(self) -> None:
        if not rclone_client.is_available():
            QMessageBox.warning(
                self,
                "rclone CLI not found",
                f"Install it from {rclone_client.INSTALL_URL} and relaunch.",
            )
            return
        dialog = AddRemoteDialog(parent=self)
        if dialog.exec() == AddRemoteDialog.DialogCode.Accepted:
            self.refresh_remotes()

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

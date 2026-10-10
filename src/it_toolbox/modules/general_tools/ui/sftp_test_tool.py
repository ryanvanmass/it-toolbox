from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QInputDialog,
    QMenu,
    QMessageBox,
    QTabWidget,
    QTreeWidgetItem,
    QWidget,
)

from it_toolbox.core import settings
from it_toolbox.widgets.sftp_server_test_widget import SftpServerTestWidget

IS_NEW_TEST_ITEM_ROLE = Qt.ItemDataRole.UserRole + 30
SAVED_TEST_NAME_ROLE = Qt.ItemDataRole.UserRole + 31


class SftpTestTool:
    """The SFTP Server Test entry under General Tools: "New Test…" opens a
    test tab in the shared session-tab pane, prefilled with the last test's
    server details. Several tabs can run at once (e.g. against two servers).
    Tests saved from a tab ("Save Test…") are listed under it, the way VMs
    are in Connection Manager: double-click one to open it in a new tab.
    """

    name = "SFTP Server Test"

    def __init__(self, view: QWidget, tabs: QTabWidget) -> None:
        self._view = view
        self._tabs = tabs
        self._owned_tab_widgets: set[SftpServerTestWidget] = set()
        self.item = QTreeWidgetItem([self.name])
        new_item = QTreeWidgetItem(["New Test…"])
        new_item.setData(0, IS_NEW_TEST_ITEM_ROLE, True)
        self.item.addChild(new_item)
        self.refresh_saved_tests()

    # -- Sidebar ----------------------------------------------------------

    def add_category_actions(self, menu: QMenu) -> None:
        """Actions for this tool's own node, and for the General Tools
        entry's context menu."""
        menu.addAction("New SFTP Server Test…").triggered.connect(self.new_test)

    def add_item_actions(self, menu: QMenu, item: QTreeWidgetItem) -> None:
        name = item.data(0, SAVED_TEST_NAME_ROLE)
        if name is None:
            self.add_category_actions(menu)
            return
        menu.addAction("Open").triggered.connect(lambda: self.open_saved_test(name))
        menu.addAction("Rename…").triggered.connect(lambda: self.rename_saved_test(name))
        menu.addAction("Delete…").triggered.connect(lambda: self.delete_saved_test(name))

    def activate(self, item: QTreeWidgetItem) -> None:
        if item.data(0, IS_NEW_TEST_ITEM_ROLE):
            self.new_test()
        elif (name := item.data(0, SAVED_TEST_NAME_ROLE)) is not None:
            self.open_saved_test(name)

    def refresh_saved_tests(self) -> None:
        """Re-lists the saved tests under "New Test…"."""
        while self.item.childCount() > 1:
            self.item.removeChild(self.item.child(1))
        configs = settings.load_sftp_server_test_configs()
        for name in sorted(configs, key=str.casefold):
            values = configs[name]
            child = QTreeWidgetItem([name])
            child.setData(0, SAVED_TEST_NAME_ROLE, name)
            target = f"{values.get('username', '')}@{values.get('host', '')}:{values.get('port', 22)}"
            child.setToolTip(0, f"{target}\nDouble-click to open in a new test tab.")
            self.item.addChild(child)

    # -- Saved tests --------------------------------------------------------

    def open_saved_test(self, name: str) -> SftpServerTestWidget | None:
        if name not in settings.load_sftp_server_test_configs():
            self.refresh_saved_tests()
            return None
        widget = self.new_test()
        widget.load_saved_test(name)
        return widget

    def rename_saved_test(self, name: str) -> None:
        new_name, ok = QInputDialog.getText(self._view, "Rename Saved Test", "New name:", text=name)
        new_name = new_name.strip()
        if not ok or not new_name or new_name == name:
            return
        configs = settings.load_sftp_server_test_configs()
        if name not in configs:
            self.refresh_saved_tests()
            return
        if new_name in configs:
            QMessageBox.warning(self._view, "Rename Saved Test", f"There's already a saved test called “{new_name}”.")
            return
        configs[new_name] = configs.pop(name)
        settings.save_sftp_server_test_configs(configs)
        for widget in self._owned_tab_widgets:
            if widget.saved_name == name:
                widget.saved_name = new_name
        self.refresh_saved_tests()

    def delete_saved_test(self, name: str) -> None:
        answer = QMessageBox.question(self._view, "Delete Saved Test", f"Delete the saved test “{name}”?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        configs = settings.load_sftp_server_test_configs()
        configs.pop(name, None)
        settings.save_sftp_server_test_configs(configs)
        for widget in self._owned_tab_widgets:
            if widget.saved_name == name:
                widget.saved_name = None
        self.refresh_saved_tests()

    # -- Tabs -------------------------------------------------------------

    def new_test(self) -> SftpServerTestWidget:
        widget = SftpServerTestWidget()
        self._owned_tab_widgets.add(widget)
        index = self._tabs.addTab(widget, self.name)
        self._tabs.setCurrentIndex(index)
        widget.title_changed.connect(lambda title: self._retitle(widget, title))
        widget.saved_tests_changed.connect(self.refresh_saved_tests)
        return widget

    def _retitle(self, widget: SftpServerTestWidget, title: str) -> None:
        index = self._tabs.indexOf(widget)
        if index != -1:
            self._tabs.setTabText(index, title)

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

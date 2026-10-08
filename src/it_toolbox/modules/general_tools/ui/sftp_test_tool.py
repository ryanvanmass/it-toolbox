from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTabWidget, QTreeWidgetItem, QWidget

from it_toolbox.widgets.sftp_server_test_widget import SftpServerTestWidget

IS_NEW_TEST_ITEM_ROLE = Qt.ItemDataRole.UserRole + 30


class SftpTestTool:
    """The SFTP Server Test entry under General Tools: "New Test…" opens a
    test tab in the shared session-tab pane, prefilled with the last test's
    server details. Several tabs can run at once (e.g. against two servers).
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

    # -- Sidebar ----------------------------------------------------------

    def add_category_actions(self, menu: QMenu) -> None:
        """Actions for this tool's own node, and for the General Tools
        entry's context menu."""
        menu.addAction("New SFTP Server Test…").triggered.connect(self.new_test)

    def add_item_actions(self, menu: QMenu, item: QTreeWidgetItem) -> None:
        self.add_category_actions(menu)

    def activate(self, item: QTreeWidgetItem) -> None:
        if item.data(0, IS_NEW_TEST_ITEM_ROLE):
            self.new_test()

    # -- Tabs -------------------------------------------------------------

    def new_test(self) -> SftpServerTestWidget:
        widget = SftpServerTestWidget()
        self._owned_tab_widgets.add(widget)
        index = self._tabs.addTab(widget, self.name)
        self._tabs.setCurrentIndex(index)
        widget.title_changed.connect(lambda title: self._retitle(widget, title))
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

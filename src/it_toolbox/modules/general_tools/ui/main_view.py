from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules.general_tools.ui.mbox_tool import MboxTool
from it_toolbox.modules.general_tools.ui.sftp_test_tool import SftpTestTool


class GeneralToolsView(QWidget):
    """Home for small standalone utilities that don't belong to a
    connection family (the Mbox Browser and the SFTP Server Test). Each tool is a
    top-level node in the sidebar tree with its own entries beneath it,
    and opens its tabs in the shared session-tab pane.

    A tool is an object with `name`, `item` (its sidebar node),
    `activate(item)`, `add_category_actions(menu)`,
    `add_item_actions(menu, item)`, `try_close_tab(widget)` and
    `close_all_sessions()` — see MboxTool.
    """

    def __init__(self, parent: QWidget | None = None, tabs: QTabWidget | None = None) -> None:
        super().__init__(parent)

        # A shared tabs widget (injected by GeneralToolsModule/MainWindow
        # in the real app) is owned and wired up centrally — see
        # MainWindow._on_session_tab_close_requested / _changed.
        # Standalone/test usage (tabs=None) stays fully self-contained.
        self._owns_tabs = tabs is None
        self._tabs = tabs if tabs is not None else QTabWidget()
        if self._owns_tabs:
            self._tabs.setTabsClosable(True)
            self._tabs.tabCloseRequested.connect(
                lambda index: self.try_close_tab(self._tabs.widget(index))
            )

        self.mbox = MboxTool(self, self._tabs)
        self.sftp_test = SftpTestTool(self, self._tabs)
        self._tools = [self.mbox, self.sftp_test]

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Tools"])
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        for tool in self._tools:
            self._tree.addTopLevelItem(tool.item)
            tool.item.setExpanded(True)

        layout = QVBoxLayout(self)
        if self._owns_tabs:
            layout.addWidget(self._tabs, 1)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._close_all_sessions)

    @property
    def sidebar_tree(self) -> QTreeWidget:
        """Hosted in the app sidebar nested under this module's entry —
        see GeneralToolsModule.create_sidebar_widget().
        """
        return self._tree

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking this module's entry in the app sidebar."""
        menu = QMenu(parent)
        for tool in self._tools:
            tool.add_category_actions(menu)
        return menu

    def _tool_for(self, item: QTreeWidgetItem):
        top = item
        while top.parent() is not None:
            top = top.parent()
        return next((tool for tool in self._tools if tool.item is top), None)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        tool = self._tool_for(item)
        if tool is not None and item is not tool.item:
            tool.activate(item)

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        tool = self._tool_for(item) if item is not None else None
        if tool is None:
            return
        menu = QMenu(self)
        if item is tool.item:
            tool.add_category_actions(menu)
        else:
            tool.add_item_actions(menu, item)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def try_close_tab(self, widget: QWidget) -> bool:
        """See ToolModule.try_close_tab."""
        return any(tool.try_close_tab(widget) for tool in self._tools)

    def _close_all_sessions(self) -> None:
        for tool in self._tools:
            tool.close_all_sessions()

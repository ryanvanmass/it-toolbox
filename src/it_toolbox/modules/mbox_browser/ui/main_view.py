from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import settings
from it_toolbox.widgets.mbox_browser_widget import MboxBrowserWidget

PATH_ROLE = Qt.ItemDataRole.UserRole
IS_OPEN_ITEM_ROLE = Qt.ItemDataRole.UserRole + 1

MBOX_FILE_FILTER = "Mbox files (*.mbox *.mbx *.mbs);;All files (*)"


class MboxBrowserView(QWidget):
    """Opens mbox mail archives into browse tabs in the shared session-tab
    pane. The sidebar lists recently opened files (persisted across runs)
    under an "Open Mbox File…" entry, like Shell Launcher's shells list.
    Opening a file that already has a tab just switches to it.
    """

    def __init__(self, parent: QWidget | None = None, tabs: QTabWidget | None = None) -> None:
        super().__init__(parent)

        # A shared tabs widget (injected by MboxBrowserModule/MainWindow in
        # the real app) is owned and wired up centrally — see
        # MainWindow._on_session_tab_close_requested / _changed.
        # Standalone/test usage (tabs=None) stays fully self-contained.
        self._owns_tabs = tabs is None
        self._tabs = tabs if tabs is not None else QTabWidget()
        if self._owns_tabs:
            self._tabs.setTabsClosable(True)
            self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._owned_tab_widgets: set[MboxBrowserWidget] = set()

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Mbox Files"])
        self._tree.setRootIsDecorated(False)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        layout = QVBoxLayout(self)
        if self._owns_tabs:
            layout.addWidget(self._tabs, 1)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._close_all_sessions)

        self.refresh_recent_files()

    @property
    def sidebar_tree(self) -> QTreeWidget:
        """Hosted in the app sidebar nested under this module's entry —
        see MboxBrowserModule.create_sidebar_widget().
        """
        return self._tree

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking this module's entry in the app sidebar."""
        menu = QMenu(parent)
        menu.addAction("Open Mbox File…").triggered.connect(self.prompt_open_file)
        clear_action = menu.addAction("Clear Recent Files")
        clear_action.setEnabled(bool(settings.load_recent_mbox_files()))
        clear_action.triggered.connect(self._clear_recent_files)
        return menu

    # -- Recent files -----------------------------------------------------

    def refresh_recent_files(self) -> None:
        self._tree.clear()
        open_item = QTreeWidgetItem(["Open Mbox File…"])
        open_item.setData(0, IS_OPEN_ITEM_ROLE, True)
        self._tree.addTopLevelItem(open_item)
        for path in settings.load_recent_mbox_files():
            item = QTreeWidgetItem([Path(path).name])
            item.setToolTip(0, path)
            item.setData(0, PATH_ROLE, path)
            if not Path(path).is_file():
                item.setDisabled(True)
                item.setToolTip(0, f"{path} (not found)")
            self._tree.addTopLevelItem(item)

    def _remember(self, path: str) -> None:
        recent = [p for p in settings.load_recent_mbox_files() if p != path]
        settings.save_recent_mbox_files([path, *recent])
        self.refresh_recent_files()

    def _forget(self, path: str) -> None:
        settings.save_recent_mbox_files(
            [p for p in settings.load_recent_mbox_files() if p != path]
        )
        self.refresh_recent_files()

    def _clear_recent_files(self) -> None:
        settings.save_recent_mbox_files([])
        self.refresh_recent_files()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, IS_OPEN_ITEM_ROLE):
            self.prompt_open_file()
            return
        path = item.data(0, PATH_ROLE)
        if path is not None and Path(path).is_file():
            self.open_file(path)

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        path = item.data(0, PATH_ROLE) if item is not None else None
        if path is not None:
            open_action = menu.addAction("Open")
            open_action.setEnabled(Path(path).is_file())
            open_action.triggered.connect(lambda: self.open_file(path))
            menu.addAction("Remove from List").triggered.connect(lambda: self._forget(path))
            menu.addSeparator()
        menu.addAction("Open Mbox File…").triggered.connect(self.prompt_open_file)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # -- Tabs -------------------------------------------------------------

    def prompt_open_file(self) -> None:
        recent = settings.load_recent_mbox_files()
        start_dir = str(Path(recent[0]).parent) if recent else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open Mbox File", start_dir, MBOX_FILE_FILTER)
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> MboxBrowserWidget:
        path = str(Path(path).resolve())
        for widget in self._owned_tab_widgets:
            if str(widget.path) == path:
                self._tabs.setCurrentWidget(widget)
                self._remember(path)
                return widget
        browser = MboxBrowserWidget(path)
        self._owned_tab_widgets.add(browser)
        index = self._tabs.addTab(browser, Path(path).name)
        self._tabs.setTabToolTip(index, path)
        self._tabs.setCurrentIndex(index)
        self._remember(path)
        return browser

    def try_close_tab(self, widget: QWidget) -> bool:
        """See ToolModule.try_close_tab."""
        if widget not in self._owned_tab_widgets:
            return False
        index = self._tabs.indexOf(widget)
        if index != -1:
            self._tabs.removeTab(index)
        self._owned_tab_widgets.discard(widget)
        widget.close_session()
        widget.deleteLater()
        return True

    def _on_tab_close_requested(self, index: int) -> None:
        self.try_close_tab(self._tabs.widget(index))

    def _close_all_sessions(self) -> None:
        for widget in list(self._owned_tab_widgets):
            widget.close_session()

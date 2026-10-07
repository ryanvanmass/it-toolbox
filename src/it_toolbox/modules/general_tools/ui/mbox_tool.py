from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMenu, QTabWidget, QTreeWidgetItem, QWidget

from it_toolbox.core import settings
from it_toolbox.widgets.mbox_browser_widget import MboxBrowserWidget

PATH_ROLE = Qt.ItemDataRole.UserRole + 10
IS_OPEN_ITEM_ROLE = Qt.ItemDataRole.UserRole + 11

MBOX_FILE_FILTER = "Mbox files (*.mbox *.mbx *.mbs);;All files (*)"


class MboxTool:
    """The Mbox Browser entry under General Tools: its sidebar node lists
    "Open Mbox File…" and recently opened files (persisted across runs),
    and each opened file gets a browse tab in the shared session-tab pane.
    Opening a file that already has a tab just switches to it.
    """

    name = "Mbox Browser"

    def __init__(self, view: QWidget, tabs: QTabWidget) -> None:
        self._view = view
        self._tabs = tabs
        self._owned_tab_widgets: set[MboxBrowserWidget] = set()
        self.item = QTreeWidgetItem([self.name])
        self.refresh_recent_files()

    # -- Sidebar ----------------------------------------------------------

    def refresh_recent_files(self) -> None:
        self.item.takeChildren()
        open_item = QTreeWidgetItem(["Open Mbox File…"])
        open_item.setData(0, IS_OPEN_ITEM_ROLE, True)
        self.item.addChild(open_item)
        for path in settings.load_recent_mbox_files():
            item = QTreeWidgetItem([Path(path).name])
            item.setToolTip(0, path)
            item.setData(0, PATH_ROLE, path)
            if not Path(path).is_file():
                item.setDisabled(True)
                item.setToolTip(0, f"{path} (not found)")
            self.item.addChild(item)

    def add_category_actions(self, menu: QMenu) -> None:
        """Actions for this tool's own node, and for the General Tools
        entry's context menu."""
        menu.addAction("Open Mbox File…").triggered.connect(self.prompt_open_file)
        clear_action = menu.addAction("Clear Recent Mbox Files")
        clear_action.setEnabled(bool(settings.load_recent_mbox_files()))
        clear_action.triggered.connect(self._clear_recent_files)

    def add_item_actions(self, menu: QMenu, item: QTreeWidgetItem) -> None:
        path = item.data(0, PATH_ROLE)
        if path is not None:
            open_action = menu.addAction("Open")
            open_action.setEnabled(Path(path).is_file())
            open_action.triggered.connect(lambda: self.open_file(path))
            menu.addAction("Remove from List").triggered.connect(lambda: self._forget(path))
            menu.addSeparator()
        self.add_category_actions(menu)

    def activate(self, item: QTreeWidgetItem) -> None:
        if item.data(0, IS_OPEN_ITEM_ROLE):
            self.prompt_open_file()
            return
        path = item.data(0, PATH_ROLE)
        if path is not None and Path(path).is_file():
            self.open_file(path)

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

    # -- Tabs -------------------------------------------------------------

    def prompt_open_file(self) -> None:
        recent = settings.load_recent_mbox_files()
        start_dir = str(Path(recent[0]).parent) if recent else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self._view, "Open Mbox File", start_dir, MBOX_FILE_FILTER
        )
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

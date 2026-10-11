from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMenu, QTabWidget, QTreeWidgetItem, QWidget

PATH_ROLE = Qt.ItemDataRole.UserRole + 10
IS_OPEN_ITEM_ROLE = Qt.ItemDataRole.UserRole + 11


class RecentFilesTool:
    """A General Tools entry that opens files into tabs: its sidebar node
    lists an "Open … File…" item and recently opened files (persisted
    across runs), and each opened file gets a tab in the shared
    session-tab pane. Opening a file that already has a tab just switches
    to it.

    Subclasses set `name`, `file_kind` (as in "Open Mbox File…"),
    `file_filter`, `load_recent`/`save_recent` (settings functions) and
    `create_widget(path)`, which returns a widget with `path` and
    `close_session()`.
    """

    name: str
    file_kind: str
    file_filter: str
    load_recent: Callable[[], list[str]]
    save_recent: Callable[[list[str]], None]

    def __init__(self, view: QWidget, tabs: QTabWidget) -> None:
        self._view = view
        self._tabs = tabs
        self._owned_tab_widgets: set[QWidget] = set()
        self.item = QTreeWidgetItem([self.name])
        self.refresh_recent_files()

    def create_widget(self, path: str) -> QWidget:
        raise NotImplementedError

    @property
    def _open_label(self) -> str:
        return f"Open {self.file_kind} File…"

    # -- Sidebar ----------------------------------------------------------

    def refresh_recent_files(self) -> None:
        self.item.takeChildren()
        open_item = QTreeWidgetItem([self._open_label])
        open_item.setData(0, IS_OPEN_ITEM_ROLE, True)
        self.item.addChild(open_item)
        for path in self.load_recent():
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
        menu.addAction(self._open_label).triggered.connect(self.prompt_open_file)
        clear_action = menu.addAction(f"Clear Recent {self.file_kind} Files")
        clear_action.setEnabled(bool(self.load_recent()))
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
        recent = [p for p in self.load_recent() if p != path]
        self.save_recent([path, *recent])
        self.refresh_recent_files()

    def _forget(self, path: str) -> None:
        self.save_recent([p for p in self.load_recent() if p != path])
        self.refresh_recent_files()

    def _clear_recent_files(self) -> None:
        self.save_recent([])
        self.refresh_recent_files()

    # -- Tabs -------------------------------------------------------------

    def prompt_open_file(self) -> None:
        recent = self.load_recent()
        start_dir = str(Path(recent[0]).parent) if recent else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self._view, self._open_label.rstrip("…"), start_dir, self.file_filter
        )
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> QWidget:
        path = str(Path(path).resolve())
        for widget in self._owned_tab_widgets:
            if str(widget.path) == path:
                self._tabs.setCurrentWidget(widget)
                self._remember(path)
                return widget
        widget = self.create_widget(path)
        self._owned_tab_widgets.add(widget)
        index = self._tabs.addTab(widget, Path(path).name)
        self._tabs.setTabToolTip(index, path)
        self._tabs.setCurrentIndex(index)
        self._remember(path)
        return widget

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

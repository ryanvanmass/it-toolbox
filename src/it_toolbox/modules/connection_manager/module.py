from PySide6.QtWidgets import QMenu, QTabWidget, QWidget

from it_toolbox.modules import ToolModule
from it_toolbox.modules.connection_manager.ui.main_view import ConnectionManagerView


class ConnectionManagerModule(ToolModule):
    id = "connection_manager"
    display_name = "Connection Manager"

    def __init__(self, tabs: QTabWidget) -> None:
        self._tabs = tabs
        self._widget: ConnectionManagerView | None = None

    def create_widget(self) -> QWidget:
        if self._widget is None:
            self._widget = ConnectionManagerView(tabs=self._tabs)
        return self._widget

    def create_sidebar_widget(self) -> QWidget | None:
        return self.create_widget().sidebar_tree

    def build_context_menu(self, parent: QWidget) -> QMenu | None:
        return self.create_widget().build_context_menu(parent)

    def try_close_tab(self, widget: QWidget) -> bool:
        return self.create_widget().try_close_tab(widget)

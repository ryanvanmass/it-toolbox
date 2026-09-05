from PySide6.QtWidgets import QMenu, QWidget

from it_toolbox.modules import ToolModule
from it_toolbox.modules.identity_management.ui.main_view import IdentityManagementView


class IdentityManagementModule(ToolModule):
    id = "identity_management"
    display_name = "Identity Management"

    def __init__(self) -> None:
        self._widget: IdentityManagementView | None = None

    def create_widget(self) -> QWidget:
        if self._widget is None:
            self._widget = IdentityManagementView()
        return self._widget

    def build_context_menu(self, parent: QWidget) -> QMenu:
        return self.create_widget().build_context_menu(parent)

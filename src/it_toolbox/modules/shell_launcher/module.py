from PySide6.QtWidgets import QMenu, QWidget

from it_toolbox.modules import ToolModule
from it_toolbox.modules.shell_launcher.ui.main_view import ShellLauncherView


class ShellLauncherModule(ToolModule):
    id = "shell_launcher"
    display_name = "Shell Launcher"

    def __init__(self) -> None:
        self._widget: ShellLauncherView | None = None

    def create_widget(self) -> QWidget:
        if self._widget is None:
            self._widget = ShellLauncherView()
        return self._widget

    def create_sidebar_widget(self) -> QWidget | None:
        return self.create_widget().sidebar_widget

    def build_context_menu(self, parent: QWidget) -> QMenu | None:
        return self.create_widget().build_context_menu(parent)

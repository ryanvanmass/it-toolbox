from PySide6.QtWidgets import QWidget

from it_toolbox.modules import ToolModule
from it_toolbox.modules.settings.ui.main_view import SettingsView


class SettingsModule(ToolModule):
    id = "settings"
    display_name = "Settings"

    def __init__(self) -> None:
        self._widget: SettingsView | None = None

    def create_widget(self) -> QWidget:
        if self._widget is None:
            self._widget = SettingsView()
        return self._widget

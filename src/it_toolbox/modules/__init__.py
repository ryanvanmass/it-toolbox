from abc import ABC, abstractmethod

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget


class ToolModule(ABC):
    """Base class for a pluggable tool module shown in the sidebar."""

    #: Stable identifier, used for settings/state keys — never shown to the user.
    id: str

    #: Label shown in the sidebar.
    display_name: str

    @property
    def icon(self) -> QIcon:
        """Sidebar icon. Defaults to no icon; override to customize."""
        return QIcon()

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Build (or return a cached) widget for this module's main view."""

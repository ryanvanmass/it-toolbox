from abc import ABC, abstractmethod

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QWidget


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

    def create_sidebar_widget(self) -> QWidget | None:
        """Optional extra navigation content shown nested under this
        module's entry in the sidebar (e.g. a resource browser tree).
        Return None (the default) if the module has none.
        """
        return None

    def build_context_menu(self, parent: QWidget) -> QMenu | None:
        """Optional context menu shown when right-clicking this module's
        entry in the sidebar. Return None (the default) for no menu.
        """
        return None

    def try_close_tab(self, widget: QWidget) -> bool:
        """Called by the shared session-tab pane when its close button is
        clicked, for each module in turn, until one claims the tab.
        Return True if `widget` belongs to this module and has been torn
        down; False (the default) if it doesn't recognize `widget`.
        """
        return False

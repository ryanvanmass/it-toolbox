from abc import ABC, abstractmethod

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QWidget

from it_toolbox.ui import theme


class ToolModule(ABC):
    """Base class for a pluggable tool module shown in the sidebar."""

    #: Stable identifier, used for settings/state keys — never shown to the user.
    id: str

    #: Label shown in the sidebar.
    display_name: str

    #: Whether this module ever puts anything into the shared session-tab
    #: pane below its main view. False for modules with nothing tab-based
    #: (e.g. Settings) — MainWindow hides the (otherwise permanently empty)
    #: pane for those and gives the module's own view the space instead.
    uses_shared_tabs: bool = True

    #: Bundled line icon (resources/icons/ui/<icon_name>.svg) shown beside
    #: the sidebar entry, tinted to the current theme. Empty for none.
    icon_name: str = ""

    #: One-line hint shown in the empty session-tab pane while this module
    #: is selected and nothing is open yet.
    empty_hint: str = "Pick something from the sidebar to open it here."

    @property
    def icon(self) -> QIcon:
        """Sidebar icon, from icon_name. Override to customize."""
        return theme.icon(self.icon_name) if self.icon_name else QIcon()

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

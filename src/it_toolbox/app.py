import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import settings
from it_toolbox.modules import ToolModule
from it_toolbox.modules.registry import load_modules
from it_toolbox.widgets.manage_automations_dialog import SHELL_ANY, Automation, display_name
from it_toolbox.widgets.terminal_widget import TerminalWidget

try:
    # RdpWidget loads the FreeRDP native libraries at import time and
    # raises OSError if they're missing (always the case on a fresh
    # Windows install until Settings fetches them) -- same guard as
    # connection_manager/ui/main_view.py, since an unguarded import here
    # stops the whole app launching, not just RDP.
    from it_toolbox.widgets.rdp_widget import RdpWidget
except (ImportError, OSError):
    RdpWidget = None

# Windows' native window/taskbar chrome only ever renders a raster icon
# (no SVG rasterizer in the picture at all) -- .ico is also a Qt-supported
# QIcon source everywhere else, but .svg scales more cleanly on Linux
# desktops that render it larger than any single baked-in .ico resolution,
# so this still picks per-platform rather than standardizing on one.
_ICON_NAME = "it-toolbox.ico" if sys.platform == "win32" else "it-toolbox.svg"
_ICON_PATH = Path(__file__).resolve().parent / "resources" / "icons" / _ICON_NAME

# Which declared automation shells fit each kind of session tab -- see
# _build_session_tab_menu.
_RDP_SHELLS = frozenset({SHELL_ANY, "PowerShell", "cmd"})
_TERMINAL_SHELLS = frozenset({SHELL_ANY, "Bash"})


class _CurrentPageStackedWidget(QStackedWidget):
    """QStackedWidget.sizeHint()/minimumSizeHint() default to the largest
    size among *all* pages (via its internal QStackedLayout), not just the
    current one. For self._stack, whose pages are wildly different sizes
    (Connection Manager's thin sign-in toolbar vs. Settings' full
    scrollable content), that meant every module's layout row claimed
    space sized for the *tallest* page regardless of which one was
    actually showing -- e.g. Connection Manager's own page only needs
    ~43px but the row was always ~408px, starving self._session_tabs
    below it. Report only the current page's size instead.
    """

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget is not None else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget is not None else super().minimumSizeHint()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("IT Toolbox")
        # Never previously set at all -- every window (and the taskbar/
        # Alt-Tab entry) fell back to Qt/the OS's own generic placeholder
        # icon instead of this app's actual logo.
        if _ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(_ICON_PATH)))
        self.resize(1000, 650)

        # One tab pane shared by every module, so sessions/terminals
        # opened from any tool stay visible and switchable regardless of
        # which module is selected in the sidebar below.
        self._session_tabs = QTabWidget()
        self._session_tabs.setTabsClosable(True)
        self._session_tabs.tabCloseRequested.connect(self._on_session_tab_close_requested)
        self._session_tabs.currentChanged.connect(self._on_session_tab_changed)
        self._session_tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._session_tabs.tabBar().customContextMenuRequested.connect(
            self._on_session_tab_context_menu
        )

        self._modules: list[ToolModule] = load_modules(self._session_tabs)

        self._module_list = QListWidget()
        self._module_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._module_list.customContextMenuRequested.connect(self._on_module_context_menu)
        # Each module's own navigation content (e.g. a resource browser
        # tree) is nested directly beneath its entry, switching in sync
        # with which module is selected above.
        self._sidebar_extras = QStackedWidget()
        # Each module's own small header/toolbar area (e.g. Connection
        # Manager's sign-in status bar) — swaps per module, sitting above
        # the shared, never-swapped self._session_tabs below it.
        self._stack = _CurrentPageStackedWidget()

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(self._module_list)
        sidebar_layout.addWidget(self._sidebar_extras, 1)

        for module in self._modules:
            item = QListWidgetItem(module.icon, module.display_name)
            self._module_list.addItem(item)
            self._stack.addWidget(module.create_widget())
            self._sidebar_extras.addWidget(module.create_sidebar_widget() or QWidget())

        # QListWidget's sizeHint() is a fixed Qt default (256x192) that
        # ignores how many rows it actually has, so without this the list
        # claims a chunk of the sidebar column no matter how few modules
        # are registered, leaving a dead gap above self._sidebar_extras.
        if self._module_list.count():
            row_height = self._module_list.sizeHintForRow(0)
            frame = 2 * self._module_list.frameWidth()
            self._module_list.setMaximumHeight(row_height * self._module_list.count() + frame)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addWidget(self._stack)
        self._content_layout.addWidget(self._session_tabs, 1)

        self._module_list.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._module_list.currentRowChanged.connect(self._sidebar_extras.setCurrentIndex)
        self._module_list.currentRowChanged.connect(self._on_module_changed)
        if self._module_list.count():
            self._module_list.setCurrentRow(0)

        splitter = QSplitter()
        splitter.addWidget(sidebar)
        splitter.addWidget(content)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 750])

        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

    def _on_module_changed(self, index: int) -> None:
        # self._session_tabs is permanently empty for a module that never
        # puts anything into it (e.g. Settings) -- hiding it and handing
        # its stretch to self._stack instead lets that module's own view
        # use the space, rather than leaving a big empty pane below it.
        module = self._modules[index]
        self._session_tabs.setVisible(module.uses_shared_tabs)
        self._content_layout.setStretch(0, 0 if module.uses_shared_tabs else 1)
        self._content_layout.setStretch(1, 1 if module.uses_shared_tabs else 0)
        # Qt caches sizeHint()/minimumSizeHint() and only re-queries a
        # widget's layout on updateGeometry() -- without this, switching
        # pages wouldn't pick up _CurrentPageStackedWidget's now-different
        # sizeHint() for the new current page.
        self._stack.updateGeometry()

    def _on_module_context_menu(self, pos) -> None:
        item = self._module_list.itemAt(pos)
        if item is None:
            return
        module = self._modules[self._module_list.row(item)]
        menu = module.build_context_menu(self)
        if menu is not None:
            menu.exec(self._module_list.viewport().mapToGlobal(pos))

    def _on_session_tab_close_requested(self, index: int) -> None:
        widget = self._session_tabs.widget(index)
        for module in self._modules:
            if module.try_close_tab(widget):
                return
        # No module claimed it — a stray tab with nothing to tear down.
        self._session_tabs.removeTab(index)
        widget.deleteLater()

    def _on_session_tab_changed(self, index: int) -> None:
        widget = self._session_tabs.widget(index)
        if widget is not None:
            widget.setFocus()

    def _build_session_tab_menu(self, index: int) -> QMenu | None:
        """Split out from _on_session_tab_context_menu so tests can check
        the built menu's actions without ever calling QMenu.exec() (which
        opens a real, blocking popup with nothing to dismiss it headless).
        Returns None where there's no tab at all, or the tab isn't a kind
        with any actions to offer.
        """
        if index == -1:
            return None
        widget = self._session_tabs.widget(index)
        is_rdp = RdpWidget is not None and isinstance(widget, RdpWidget)
        if not is_rdp and not isinstance(widget, TerminalWidget):
            return None
        menu = QMenu(self)
        if is_rdp:
            menu.addAction("Refresh Resolution").triggered.connect(widget.refresh_resolution)
        automations = [Automation.from_dict(a) for a in settings.load_automations()]
        if automations:
            submenu = menu.addMenu("Run Automation")
            tab_title = self._session_tabs.tabText(index)
            # Automations declared for this kind of tab's usual shell come
            # first; the rest stay available below a separator (an SSH
            # host can run PowerShell, an RDP host can be Linux).
            fitting_shells = _RDP_SHELLS if is_rdp else _TERMINAL_SHELLS
            fitting = [a for a in automations if a.shell in fitting_shells]
            others = [a for a in automations if a.shell not in fitting_shells]
            for group in (fitting, others):
                if group and submenu.actions():
                    submenu.addSeparator()
                for automation in group:
                    label = display_name(automation.name, automation.shell)
                    submenu.addAction(label).triggered.connect(
                        lambda checked=False, label=label, content=automation.content: (
                            self._run_automation(widget, tab_title, label, content)
                        )
                    )
        return menu if menu.actions() else None

    def _run_automation(self, widget, tab_title: str, name: str, content: str) -> None:
        """Types a saved automation into a session tab after a confirmation
        -- it's a real, unreviewed action against a live session (possibly
        a root shell or an admin desktop), and there's no undo once it's
        been typed. Nothing comes back from the remote side either, so
        this is fire-and-forget past the prompt.
        """
        reply = QMessageBox.question(
            self,
            "Run Automation",
            f'Type "{name}" into {tab_title}? Each line is entered as if typed at the '
            "keyboard, into whatever currently has focus in that session.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        widget.send_text(content)

    def _on_session_tab_context_menu(self, pos) -> None:
        tab_bar = self._session_tabs.tabBar()
        menu = self._build_session_tab_menu(tab_bar.tabAt(pos))
        if menu is not None:
            menu.exec(tab_bar.mapToGlobal(pos))

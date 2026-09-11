import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules import ToolModule
from it_toolbox.modules.registry import load_modules
from it_toolbox.widgets.rdp_widget import RdpWidget

# Windows' native window/taskbar chrome only ever renders a raster icon
# (no SVG rasterizer in the picture at all) -- .ico is also a Qt-supported
# QIcon source everywhere else, but .svg scales more cleanly on Linux
# desktops that render it larger than any single baked-in .ico resolution,
# so this still picks per-platform rather than standardizing on one.
_ICON_NAME = "it-toolbox.ico" if sys.platform == "win32" else "it-toolbox.svg"
_ICON_PATH = Path(__file__).resolve().parent / "resources" / "icons" / _ICON_NAME


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
        if not isinstance(widget, RdpWidget):
            return None
        menu = QMenu(self)
        menu.addAction("Refresh Resolution").triggered.connect(widget.refresh_resolution)
        return menu

    def _on_session_tab_context_menu(self, pos) -> None:
        tab_bar = self._session_tabs.tabBar()
        menu = self._build_session_tab_menu(tab_bar.tabAt(pos))
        if menu is not None:
            menu.exec(tab_bar.mapToGlobal(pos))

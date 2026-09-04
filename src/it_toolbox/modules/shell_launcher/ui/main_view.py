from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core.shell_discovery import Shell, discover_shells
from it_toolbox.widgets.terminal_widget import TerminalWidget

SHELL_ROLE = Qt.ItemDataRole.UserRole


class ShellLauncherView(QWidget):
    """Discovers shells installed on the local machine and launches them
    in embedded terminal tabs — a local-only counterpart to Connection
    Manager's remote connection families. Every tab here is a
    TerminalWidget; unlike Connection Manager there's no tunnel or
    account state to track alongside it, so tabs are their own source of
    truth (no parallel session-id bookkeeping needed).
    """

    def __init__(self, parent: QWidget | None = None, tabs: QTabWidget | None = None) -> None:
        super().__init__(parent)

        self._list = QTreeWidget()
        self._list.setHeaderLabels(["Shells"])
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)

        # A shared tabs widget (injected by ShellLauncherModule/MainWindow
        # in the real app) is owned and wired up centrally — see
        # MainWindow._on_session_tab_close_requested / _changed.
        # Standalone/test usage (tabs=None) stays fully self-contained.
        self._owns_tabs = tabs is None
        self._tabs = tabs if tabs is not None else QTabWidget()
        if self._owns_tabs:
            self._tabs.setTabsClosable(True)
            self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
            self._tabs.currentChanged.connect(self._on_tab_changed)
        self._owned_tab_widgets: set[TerminalWidget] = set()

        layout = QVBoxLayout(self)
        if self._owns_tabs:
            layout.addWidget(self._tabs, 1)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._close_all_sessions)

        self.refresh_shells()

    @property
    def sidebar_widget(self) -> QWidget:
        """The discovered-shells list, hosted in the app sidebar nested
        under this module's entry — see
        ShellLauncherModule.create_sidebar_widget().
        """
        return self._list

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking this module's entry in the app
        sidebar — see ShellLauncherModule.build_context_menu().
        """
        menu = QMenu(parent)
        menu.addAction("Refresh").triggered.connect(self.refresh_shells)
        return menu

    # -- Shell list ---------------------------------------------------------

    def refresh_shells(self) -> None:
        self._list.clear()
        for shell in discover_shells():
            item = QTreeWidgetItem([shell.name])
            item.setData(0, SHELL_ROLE, shell)
            self._list.addTopLevelItem(item)

    def _on_list_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Refresh").triggered.connect(self.refresh_shells)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        shell = item.data(0, SHELL_ROLE)
        self._launch_shell(shell)

    # -- Launch / teardown ----------------------------------------------

    def _launch_shell(self, shell: Shell) -> None:
        terminal = TerminalWidget(list(shell.argv))
        terminal.finished.connect(lambda: self._on_terminal_finished(terminal))
        self._owned_tab_widgets.add(terminal)
        index = self._tabs.addTab(terminal, shell.name)
        self._tabs.setCurrentIndex(index)
        terminal.setFocus()

    def _on_terminal_finished(self, terminal: TerminalWidget) -> None:
        index = self._tabs.indexOf(terminal)
        if index != -1:
            self._tabs.removeTab(index)
        self._owned_tab_widgets.discard(terminal)
        terminal.deleteLater()

    def try_close_tab(self, widget: QWidget) -> bool:
        """Tear down `widget` if this view launched it into (possibly
        shared) self._tabs, and report whether it did — see
        ToolModule.try_close_tab and MainWindow._on_session_tab_close_requested.
        """
        if widget not in self._owned_tab_widgets:
            return False
        index = self._tabs.indexOf(widget)
        if index != -1:
            self._tabs.removeTab(index)
        self._owned_tab_widgets.discard(widget)
        widget.close_session()
        widget.deleteLater()
        return True

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self.try_close_tab(widget)

    def _on_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if widget is not None:
            widget.setFocus()

    def _close_all_sessions(self) -> None:
        for widget in list(self._owned_tab_widgets):
            widget.close_session()

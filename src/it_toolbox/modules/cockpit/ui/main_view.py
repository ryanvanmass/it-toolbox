import shiboken6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, settings
from it_toolbox.core import cockpit_machines as cm
from it_toolbox.core.cockpit_machines import CockpitMachine
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.hosting_manager_widget import HostingManagerWidget
from it_toolbox.widgets.proftpd_manager_widget import ProftpdManagerWidget
from it_toolbox.widgets.remote_helper_widget import ServerDialog, prompt_to_retry
from it_toolbox.widgets.scheduler_manager_widget import SchedulerManagerWidget

MACHINE_KEY_ROLE = Qt.ItemDataRole.UserRole + 60
TOOL_ROLE = Qt.ItemDataRole.UserRole + 61
IS_ADD_ITEM_ROLE = Qt.ItemDataRole.UserRole + 62

#: Tab-title prefix per tool, e.g. "Hosting: web".
TAB_PREFIXES = {cm.PROFTPD: "ProFTPD", cm.HOSTING: "Hosting", cm.SCHEDULER: "Scheduler"}


def manager_widget_class(tool: str):
    """Looked up at call time so tests can swap the widgets out."""
    return {
        cm.PROFTPD: ProftpdManagerWidget,
        cm.HOSTING: HostingManagerWidget,
        cm.SCHEDULER: SchedulerManagerWidget,
    }[tool]


class MachineDialog(ServerDialog):
    """The managers' server dialog plus the one ProFTPD-specific setting."""

    def __init__(self, machine: CockpitMachine | None = None, parent: QWidget | None = None) -> None:
        super().__init__("Cockpit Machine", CockpitMachine, machine, parent)
        self.setWindowTitle("Edit Machine" if machine else "Add Machine")
        self._container = QLineEdit((machine.proftpd_container or "") if machine else "")
        self._container.setPlaceholderText("Only for the cockpit-proftpd container (TrueNAS app)")
        form = self.findChild(QFormLayout)
        form.addRow("ProFTPD container:", self._container)

    def server(self) -> CockpitMachine:
        machine = super().server()
        machine.proftpd_container = self._container.text().strip() or None
        return machine


class CockpitView(QWidget):
    """Machines running the user's Cockpit modules. Each machine is a
    sidebar node; beneath it, one child per manager whose module helper
    was found on it (see core/cockpit_machines.py), much like a GCP
    project's VMs and buckets in Connection Manager. Opening a child opens
    that manager's tab in the shared session-tab pane, reusing the
    passwords the machine's detection asked for.
    """

    def __init__(self, parent: QWidget | None = None, tabs: QTabWidget | None = None) -> None:
        super().__init__(parent)

        # Same shared/own tabs arrangement as GeneralToolsView.
        self._owns_tabs = tabs is None
        self._tabs = tabs if tabs is not None else QTabWidget()
        if self._owns_tabs:
            self._tabs.setTabsClosable(True)
            self._tabs.tabCloseRequested.connect(
                lambda index: self.try_close_tab(self._tabs.widget(index))
            )

        # Per machine key: SSH/sudo passwords typed this session (never
        # saved), shared by its detection and all of its manager tabs.
        self._credentials: dict[tuple, dict] = {}
        self._detecting: set[tuple] = set()
        self._open_tabs: dict[tuple[tuple, str], QWidget] = {}

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Machines"])
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        layout = QVBoxLayout(self)
        if self._owns_tabs:
            layout.addWidget(self._tabs, 1)

        self._populate()

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close_all_sessions)

    @property
    def sidebar_tree(self) -> QTreeWidget:
        return self._tree

    # -- Saved machines ------------------------------------------------------

    def machines(self) -> list[CockpitMachine]:
        saved = settings.load_cockpit_machines()
        if saved is None:
            # First run with the Cockpit module: bring over the servers the
            # managers kept under General Tools.
            machines = cm.migrate_tool_servers(
                settings.load_proftpd_servers(),
                settings.load_hosting_servers(),
                settings.load_scheduler_servers(),
            )
            settings.save_cockpit_machines([m.to_dict() for m in machines])
            return machines
        loaded = (CockpitMachine.from_dict(d) for d in saved)
        return [machine for machine in loaded if machine is not None]

    def machine(self, key: tuple) -> CockpitMachine | None:
        return next((m for m in self.machines() if m.key == key), None)

    def _save(self, machines: list[CockpitMachine]) -> None:
        settings.save_cockpit_machines([m.to_dict() for m in machines])
        self._populate()

    def add_machine(self) -> None:
        dialog = MachineDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        machine = dialog.server()
        machines = self.machines()
        if any(m.key == machine.key for m in machines):
            QMessageBox.information(self, "Add Machine", f"{machine.target} is already in the list.")
            return
        self._save([*machines, machine])
        item = self._machine_item(machine.key)
        if item is not None:
            item.setExpanded(True)  # detects its tools
            self._tree.setCurrentItem(item)

    def _edit_machine(self, key: tuple) -> None:
        machines = self.machines()
        index = next((i for i, m in enumerate(machines) if m.key == key), None)
        if index is None:
            return
        dialog = MachineDialog(machines[index], parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited, old = dialog.server(), machines[index]
        # A different login or container may see different modules.
        same_target = (edited.key, edited.proftpd_container) == (old.key, old.proftpd_container)
        edited.tools = old.tools if same_target else None
        machines[index] = edited
        self._save(machines)

    def _remove_machine(self, key: tuple) -> None:
        machines = self.machines()
        machine = next((m for m in machines if m.key == key), None)
        if machine is None:
            return
        confirmed = QMessageBox.question(
            self, "Remove Machine", f"Remove {machine.name}? Nothing on the machine changes."
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._save([m for m in machines if m.key != key])

    # -- Tree ------------------------------------------------------------------

    def _populate(self) -> None:
        expanded = {
            self._tree.topLevelItem(i).data(0, MACHINE_KEY_ROLE)
            for i in range(self._tree.topLevelItemCount())
            if self._tree.topLevelItem(i).isExpanded()
        }
        self._tree.clear()
        add_item = QTreeWidgetItem(["Add Machine…"])
        add_item.setData(0, IS_ADD_ITEM_ROLE, True)
        self._tree.addTopLevelItem(add_item)
        for machine in self.machines():
            item = QTreeWidgetItem([machine.name])
            item.setToolTip(0, machine.target)
            item.setData(0, MACHINE_KEY_ROLE, machine.key)
            self._tree.addTopLevelItem(item)
            self._fill_tools(item, machine)
            if machine.key in expanded or machine.tools:
                item.setExpanded(True)

    def _machine_item(self, key: tuple) -> QTreeWidgetItem | None:
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, MACHINE_KEY_ROLE) == key:
                return item
        return None

    def _fill_tools(self, item: QTreeWidgetItem, machine: CockpitMachine) -> None:
        item.takeChildren()
        if machine.key in self._detecting:
            item.addChild(QTreeWidgetItem(["Checking for Cockpit modules…"]))
            return
        if machine.tools is None:
            # Detected on first expand, not at startup, so launching the
            # app never pops up password prompts for every machine.
            item.addChild(QTreeWidgetItem(["Expand to check for Cockpit modules"]))
            return
        if not machine.tools:
            item.addChild(QTreeWidgetItem(["(no supported Cockpit modules found)"]))
            return
        for tool in cm.TOOL_IDS:
            if not cm.has_tool(machine, tool):
                continue
            label = cm.TOOL_NAMES[tool]
            if tool not in machine.tools:
                label += " (helper not installed)"
            child = QTreeWidgetItem([label])
            child.setData(0, MACHINE_KEY_ROLE, machine.key)
            child.setData(0, TOOL_ROLE, tool)
            item.addChild(child)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, MACHINE_KEY_ROLE)
        if key is None or item.parent() is not None:
            return
        machine = self.machine(key)
        if machine is not None and machine.tools is None:
            self.detect(machine)

    # -- Detection -------------------------------------------------------------

    def detect(self, machine: CockpitMachine) -> None:
        """Connects to the machine in the background and lists the tools
        it has, prompting (once per session) for any passwords needed."""
        if machine.key in self._detecting:
            return
        self._detecting.add(machine.key)
        item = self._machine_item(machine.key)
        if item is not None:
            self._fill_tools(item, machine)
        credentials = self._credentials.setdefault(machine.key, {})
        connection = cm.MachineConnection(machine, **credentials)
        task = status_bar.begin(self, f"Checking {machine.name} for Cockpit modules…")

        def work():
            connection.connect()
            try:
                return connection.detect_tools()
            finally:
                connection.close()

        def ok(tools):
            task.finish()
            self._detecting.discard(machine.key)
            self._on_detected(machine.key, tools)

        def failed(error):
            task.finish()
            self._detecting.discard(machine.key)
            if not shiboken6.isValid(self):
                return
            if prompt_to_retry(self, connection, error, credentials):
                self.detect(machine)
                return
            self._on_detect_failed(machine.key, error)

        async_utils.run_in_background(work, on_result=ok, on_error=failed)

    def _on_detected(self, key: tuple, tools: list[str]) -> None:
        machines = self.machines()
        machine = next((m for m in machines if m.key == key), None)
        if machine is None:
            return  # removed while detecting
        machine.tools = tools
        settings.save_cockpit_machines([m.to_dict() for m in machines])
        item = self._machine_item(key)
        if item is not None and shiboken6.isValid(item):
            self._fill_tools(item, machine)
            item.setExpanded(True)

    def _on_detect_failed(self, key: tuple, error: Exception) -> None:
        item = self._machine_item(key)
        machine = self.machine(key)
        if item is None or machine is None:
            return
        self._fill_tools(item, machine)
        if machine.tools is None:
            item.takeChildren()
        error_item = QTreeWidgetItem([f"Couldn't connect: {error}"])
        error_item.setToolTip(0, str(error))
        item.insertChild(0, error_item)
        item.setExpanded(True)

    # -- Menus / activation ------------------------------------------------------

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking this module's entry in the app sidebar."""
        menu = QMenu(parent)
        menu.addAction("Add Machine…").triggered.connect(self.add_machine)
        return menu

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, IS_ADD_ITEM_ROLE):
            self.add_machine()
            return
        tool = item.data(0, TOOL_ROLE)
        if tool is not None:
            machine = self.machine(item.data(0, MACHINE_KEY_ROLE))
            if machine is not None:
                self.open_tool(machine, tool)

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        key = item.data(0, MACHINE_KEY_ROLE) if item is not None else None
        machine = self.machine(key) if key is not None else None
        tool = item.data(0, TOOL_ROLE) if item is not None else None
        if machine is not None:
            if tool is not None:
                menu.addAction(f"Open {cm.TOOL_NAMES[tool]}").triggered.connect(
                    lambda: self.open_tool(machine, tool)
                )
                menu.addSeparator()
            self.add_machine_actions(menu, machine)
            menu.addSeparator()
        menu.addAction("Add Machine…").triggered.connect(self.add_machine)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def add_machine_actions(self, menu: QMenu, machine: CockpitMachine) -> None:
        menu.addAction("Refresh Tools").triggered.connect(lambda: self.detect(machine))
        menu.addAction("Open in Cockpit").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(machine.cockpit_url))
        )
        menu.addSeparator()
        menu.addAction("Edit…").triggered.connect(lambda: self._edit_machine(machine.key))
        menu.addAction("Remove").triggered.connect(lambda: self._remove_machine(machine.key))

    # -- Tabs ------------------------------------------------------------------

    def open_tool(self, machine: CockpitMachine, tool: str) -> QWidget:
        """Opens (or switches to) the tool's manager tab for the machine."""
        tab_key = (machine.key, tool)
        existing = self._open_tabs.get(tab_key)
        if existing is not None:
            self._tabs.setCurrentWidget(existing)
            return existing
        credentials = self._credentials.setdefault(machine.key, {})
        widget = manager_widget_class(tool)(machine.server_for(tool), credentials=credentials)
        self._open_tabs[tab_key] = widget
        index = self._tabs.addTab(widget, f"{TAB_PREFIXES[tool]}: {machine.name}")
        self._tabs.setTabToolTip(index, machine.target)
        self._tabs.setCurrentIndex(index)
        return widget

    def try_close_tab(self, widget: QWidget) -> bool:
        """See ToolModule.try_close_tab."""
        tab_key = next((k for k, w in self._open_tabs.items() if w is widget), None)
        if tab_key is None:
            return False
        index = self._tabs.indexOf(widget)
        if index != -1:
            self._tabs.removeTab(index)
        del self._open_tabs[tab_key]
        widget.close_session()
        widget.deleteLater()
        return True

    def close_all_sessions(self) -> None:
        for widget in list(self._open_tabs.values()):
            widget.close_session()

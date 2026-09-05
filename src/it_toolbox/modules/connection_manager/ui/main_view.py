from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, settings
from it_toolbox.core.auth import gcp_auth
from it_toolbox.core.iap_tunnel import IapTunnelTarget
from it_toolbox.core.qemu_tunnel import QemuTunnel
from it_toolbox.core.tunnel_session import BackgroundTunnel
from it_toolbox.modules.connection_manager import gcp_client, qemu_client
from it_toolbox.modules.connection_manager.models import (
    RDP_PORT,
    SSH_PORT,
    GcpProject,
    GcsBucket,
    Instance,
    ManualConnection,
    QemuHost,
    QemuVm,
)
from it_toolbox.modules.connection_manager.qemu_client import QemuApiError
from it_toolbox.modules.connection_manager.ui.active_sessions_dialog import ActiveSessionsDialog
from it_toolbox.modules.connection_manager.ui.manage_hosts_dialog import ManageHostsDialog
from it_toolbox.modules.connection_manager.ui.manage_manual_connections_dialog import (
    ManageManualConnectionsDialog,
)
from it_toolbox.modules.connection_manager.ui.project_selection_dialog import (
    ProjectSelectionDialog,
)
from it_toolbox.widgets.bucket_browser_widget import BucketBrowserWidget
from it_toolbox.widgets.rdp_widget import RdpWidget
from it_toolbox.widgets.terminal_widget import TerminalWidget

try:
    # SpiceWidget pulls in PyGObject/spice-glib (core/spice/spice_session_worker.py
    # does `from gi.repository import GLib`), which pyproject.toml only
    # installs on sys_platform == "linux" — importing it unconditionally
    # here would crash the *entire app* at startup on Windows/macOS, not
    # just disable the QEMU/SPICE feature. VM discovery/power actions
    # (qemu_client.py, pure subprocess/virsh) don't need this and stay
    # available regardless; only the actual "Connect via SPICE" action is
    # gated on SpiceWidget being importable.
    from it_toolbox.widgets.spice_widget import SpiceWidget
except ImportError:
    SpiceWidget = None

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole
CHILDREN_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1
INSTANCE_ROLE = Qt.ItemDataRole.UserRole + 2
IS_GCP_ROOT_ROLE = Qt.ItemDataRole.UserRole + 3
CATEGORY_ROLE = Qt.ItemDataRole.UserRole + 4
BUCKET_ROLE = Qt.ItemDataRole.UserRole + 5
IS_QEMU_ROOT_ROLE = Qt.ItemDataRole.UserRole + 6
HOST_ROLE = Qt.ItemDataRole.UserRole + 7
VM_ROLE = Qt.ItemDataRole.UserRole + 8
IS_MANUAL_ROOT_ROLE = Qt.ItemDataRole.UserRole + 9
MANUAL_CONNECTION_ROLE = Qt.ItemDataRole.UserRole + 10
IS_LOADING_ROLE = Qt.ItemDataRole.UserRole + 11

CATEGORY_VMS = "vms"
CATEGORY_BUCKETS = "buckets"

GCP_REFRESH_INTERVAL_MS = 30 * 60 * 1000  # manual refresh covers "need it sooner"


class ConnectionManagerView(QWidget):
    def __init__(self, parent: QWidget | None = None, tabs: QTabWidget | None = None) -> None:
        super().__init__(parent)

        self._account: str | None = None
        self._active_sessions: dict[int, tuple[str, BackgroundTunnel | QemuTunnel]] = {}
        self._session_tab_widgets: dict[int, TerminalWidget | RdpWidget | SpiceWidget] = {}
        # Every widget this view has added to self._tabs (sessions above,
        # plus untracked ones like bucket browsers) — lets try_close_tab
        # recognize its own tabs when self._tabs is shared with other
        # modules (see ConnectionManagerModule / MainWindow).
        self._owned_tab_widgets: set[QWidget] = set()
        self._next_session_id = 1
        self._all_projects: list[GcpProject] = []
        self._gcp_root_item: QTreeWidgetItem | None = None
        self._qemu_root_item: QTreeWidgetItem | None = None
        self._manual_root_item: QTreeWidgetItem | None = None

        self._active_sessions_dialog = ActiveSessionsDialog(parent=self)
        self._active_sessions_dialog.disconnect_requested.connect(self._on_disconnect_requested)

        self._sign_in_button = QPushButton("Sign in with gcloud")
        self._sign_in_button.clicked.connect(self._on_sign_in_clicked)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        top_bar.addWidget(self._sign_in_button)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Connections"])
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)

        # A shared tabs widget (injected by ConnectionManagerModule/
        # MainWindow in the real app) is owned and wired up centrally —
        # see MainWindow._on_session_tab_close_requested / _changed.
        # Standalone/test usage (tabs=None) stays fully self-contained.
        self._owns_tabs = tabs is None
        self._tabs = tabs if tabs is not None else QTabWidget()
        if self._owns_tabs:
            self._tabs.setTabsClosable(True)
            self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
            self._tabs.currentChanged.connect(self._on_session_tab_changed)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        if self._owns_tabs:
            layout.addWidget(self._tabs, 1)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_all_sessions)

        # Keeps selected projects' VMs/buckets from going stale between
        # visits — runs regardless of sign-in state (no-ops via
        # _refresh_all_gcp_data's own guard until there's data to refresh)
        # so it's already running by the time there is.
        self._gcp_refresh_timer = QTimer(self)
        self._gcp_refresh_timer.setInterval(GCP_REFRESH_INTERVAL_MS)
        self._gcp_refresh_timer.timeout.connect(self._refresh_all_gcp_data)
        self._gcp_refresh_timer.start()

        # QEMU hosts and manually-configured connections are independent
        # connection families — shown regardless of GCP sign-in state,
        # unlike everything below this point which requires the gcloud CLI.
        self._populate_qemu_hosts()
        self._populate_manual_connections()

        if not gcp_auth.is_available():
            self._sign_in_button.setEnabled(False)
            self._sign_in_button.setToolTip(
                f"gcloud CLI not found — install it from {gcp_auth.INSTALL_URL} "
                "and relaunch."
            )
            return

        self._sign_in_button.setEnabled(False)
        async_utils.run_in_background(
            gcp_auth.get_active_account,
            on_result=self._on_startup_account_checked,
            on_error=self._on_auth_error,
        )

    @property
    def sidebar_tree(self) -> QTreeWidget:
        """The GCP project/instance browser, hosted in the app sidebar
        (nested under this module's entry) rather than in this view's own
        layout — see ConnectionManagerModule.create_sidebar_widget().
        """
        return self._tree

    # -- Sign in / out -----------------------------------------------------

    def _on_startup_account_checked(self, account: str | None) -> None:
        self._sign_in_button.setEnabled(True)
        if account is not None:
            self._set_signed_in(account)

    def _on_sign_in_clicked(self) -> None:
        self._sign_in_button.setEnabled(False)
        async_utils.run_in_background(
            gcp_auth.sign_in,
            on_result=self._set_signed_in,
            on_error=self._on_auth_error,
        )

    def _do_sign_out(self) -> None:
        async_utils.run_in_background(
            gcp_auth.sign_out,
            on_result=lambda _: self._set_signed_out(),
            on_error=self._on_auth_error,
        )

    def _set_signed_in(self, account: str) -> None:
        self._account = account
        self._sign_in_button.setVisible(False)
        async_utils.run_in_background(
            lambda: gcp_client.list_projects(gcp_auth.get_credentials()),
            on_result=self._populate_projects,
            on_error=self._on_load_error,
        )

    def _set_signed_out(self) -> None:
        self._account = None
        self._all_projects = []
        self._tree.clear()
        self._sign_in_button.setEnabled(True)
        self._sign_in_button.setVisible(True)

    def _on_auth_error(self, error: Exception) -> None:
        self._sign_in_button.setEnabled(True)
        QMessageBox.warning(self, "gcloud auth failed", str(error))

    # -- Project / instance tree --------------------------------------------

    def _populate_projects(self, projects: list[GcpProject]) -> None:
        self._all_projects = projects

        selected_ids = settings.load_selected_project_ids()
        if selected_ids is None:
            # First time signing in (or never configured) — with accounts
            # that can have hundreds of projects, showing everything by
            # default is both unusable and means one slow/unresponsive
            # project can eat a request timeout on every session start.
            dialog = ProjectSelectionDialog(projects, selected_ids=set(), parent=self)
            if dialog.exec() == ProjectSelectionDialog.DialogCode.Accepted:
                selected_ids = dialog.selected_project_ids()
                settings.save_selected_project_ids(selected_ids)
            else:
                selected_ids = set()

        self._apply_project_selection(selected_ids)

    def _apply_project_selection(self, selected_ids: set[str]) -> None:
        visible = sorted(
            (p for p in self._all_projects if p.project_id in selected_ids),
            key=lambda p: (p.display_name or p.project_id).lower(),
        )

        # tree.clear() destroys every top-level item, QEMU/Manual roots
        # included — rebuild them right after so each connection family
        # stays independent of the others' refresh cycles.
        self._tree.clear()
        self._qemu_root_item = None
        self._manual_root_item = None
        gcp_category = QTreeWidgetItem(["GCP"])
        gcp_category.setData(0, IS_GCP_ROOT_ROLE, True)
        self._tree.addTopLevelItem(gcp_category)
        self._gcp_root_item = gcp_category
        for project in visible:
            item = QTreeWidgetItem([project.display_name or project.project_id])
            item.setData(0, PROJECT_ID_ROLE, project.project_id)
            gcp_category.addChild(item)

            for category, label in ((CATEGORY_VMS, "VMs"), (CATEGORY_BUCKETS, "Buckets")):
                category_item = QTreeWidgetItem([label])
                category_item.setData(0, PROJECT_ID_ROLE, project.project_id)
                category_item.setData(0, CATEGORY_ROLE, category)
                category_item.setData(0, CHILDREN_LOADED_ROLE, False)
                category_item.addChild(QTreeWidgetItem(["Loading…"]))
                item.addChild(category_item)
                # Pre-load in the background so the data is already there
                # (or visibly loading) the first time the user expands it,
                # rather than waiting for that expand to even start fetching.
                self._load_category(category_item, project.project_id, category)
        gcp_category.setExpanded(True)
        self._populate_qemu_hosts()
        self._populate_manual_connections()

    def _on_select_projects_clicked(self) -> None:
        current_ids = settings.load_selected_project_ids() or set()
        dialog = ProjectSelectionDialog(self._all_projects, selected_ids=current_ids, parent=self)
        if dialog.exec() != ProjectSelectionDialog.DialogCode.Accepted:
            return
        selected_ids = dialog.selected_project_ids()
        settings.save_selected_project_ids(selected_ids)
        self._apply_project_selection(selected_ids)

    # -- Module context menu: default username / active sessions --------------

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking this module's entry in the app
        sidebar — see ConnectionManagerModule.build_context_menu().
        """
        username = settings.load_default_username()
        menu = QMenu(parent)
        set_username_action = menu.addAction(
            f"Default Username: {username}" if username else "Set Default Username…"
        )
        set_username_action.triggered.connect(self._on_set_default_username_clicked)
        view_sessions_action = menu.addAction("View Active Sessions…")
        view_sessions_action.triggered.connect(self._on_view_active_sessions_clicked)
        return menu

    def _on_set_default_username_clicked(self) -> None:
        current = settings.load_default_username() or ""
        username, ok = QInputDialog.getText(
            self,
            "Default Username",
            "Username to use for connections that don't specify their own "
            "(leave blank to be prompted each time instead):",
            text=current,
        )
        if not ok:
            return
        settings.save_default_username(username.strip() or None)

    def _on_view_active_sessions_clicked(self) -> None:
        self._active_sessions_dialog.show()
        self._active_sessions_dialog.raise_()
        self._active_sessions_dialog.activateWindow()

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        host = item.data(0, HOST_ROLE)
        if host is not None and item.data(0, VM_ROLE) is None:  # a QEMU host node, not a VM leaf
            if not item.data(0, CHILDREN_LOADED_ROLE):
                item.setData(0, CHILDREN_LOADED_ROLE, True)
                self._load_qemu_vms(item, host)
            return

        project_id = item.data(0, PROJECT_ID_ROLE)
        category = item.data(0, CATEGORY_ROLE)
        already_loaded = item.data(0, CHILDREN_LOADED_ROLE)
        if project_id is None or category is None or already_loaded or self._account is None:
            return

        self._load_category(item, project_id, category)

    def _load_category(self, item: QTreeWidgetItem, project_id: str, category: str) -> None:
        """Fetch one project's VMs or buckets and populate `item` with the
        result. The single entry point for that fetch regardless of what
        triggered it — first expand, background pre-load, a periodic
        refresh, or a manual "Refresh" — so all four naturally share the
        same in-flight guard (IS_LOADING_ROLE) instead of each needing
        their own bookkeeping.
        """
        if item.data(0, IS_LOADING_ROLE):
            # Already loading (or still loading from a previous trigger) —
            # letting a second call through here risks a slow stale
            # request's error arriving *after* a fresh success and
            # clobbering good data with an error message.
            return
        item.setData(0, CHILDREN_LOADED_ROLE, True)
        item.setData(0, IS_LOADING_ROLE, True)

        if category == CATEGORY_VMS:
            async_utils.run_in_background(
                lambda: gcp_client.list_instances(gcp_auth.get_credentials(), project_id),
                on_result=lambda instances: self._on_category_loaded(
                    item, self._populate_instances, instances
                ),
                on_error=lambda error: self._on_category_load_failed(item, error),
            )
        elif category == CATEGORY_BUCKETS:
            async_utils.run_in_background(
                lambda: gcp_client.list_buckets(gcp_auth.get_credentials(), project_id),
                on_result=lambda buckets: self._on_category_loaded(
                    item, self._populate_buckets, buckets
                ),
                on_error=lambda error: self._on_category_load_failed(item, error),
            )

    def _on_category_loaded(self, item: QTreeWidgetItem, populate, data) -> None:
        item.setData(0, IS_LOADING_ROLE, False)
        populate(item, data)

    def _on_category_load_failed(self, item: QTreeWidgetItem, error: Exception) -> None:
        item.setData(0, IS_LOADING_ROLE, False)
        self._populate_category_error(item, error)

    def _refresh_project(self, project_item: QTreeWidgetItem) -> None:
        """Re-fetch both of a project's categories — used by the manual
        "Refresh" context-menu action and, per-project, by the periodic
        refresh timer.
        """
        project_id = project_item.data(0, PROJECT_ID_ROLE)
        for i in range(project_item.childCount()):
            category_item = project_item.child(i)
            category = category_item.data(0, CATEGORY_ROLE)
            if category is not None:
                self._load_category(category_item, project_id, category)

    def _refresh_all_gcp_data(self) -> None:
        if self._account is None or self._gcp_root_item is None:
            return
        for i in range(self._gcp_root_item.childCount()):
            self._refresh_project(self._gcp_root_item.child(i))

    def _populate_instances(self, category_item: QTreeWidgetItem, instances: list[Instance]) -> None:
        category_item.takeChildren()
        if not instances:
            category_item.addChild(QTreeWidgetItem(["(no instances)"]))
            return
        for instance in instances:
            item = QTreeWidgetItem([instance.name])
            item.setData(0, INSTANCE_ROLE, instance)
            item.setToolTip(0, f"Status: {instance.status}")
            category_item.addChild(item)

    def _populate_buckets(self, category_item: QTreeWidgetItem, buckets: list[GcsBucket]) -> None:
        # A project with no buckets just hides the category entirely
        # instead of showing an empty "(no buckets)" row — most projects
        # never have any, so this cuts a lot of noise out of the tree.
        # Stays hidden/shown correctly across periodic/manual refreshes
        # since setHidden() re-evaluates from the latest result every time
        # (buckets added later un-hide it; all deleted re-hides it).
        category_item.setHidden(not buckets)
        category_item.takeChildren()
        for bucket in buckets:
            item = QTreeWidgetItem([bucket.name])
            item.setData(0, BUCKET_ROLE, bucket)
            category_item.addChild(item)

    def _populate_category_error(self, category_item: QTreeWidgetItem, error: Exception) -> None:
        # Always surface errors — never leave a category hidden (from a
        # prior empty-but-successful load) while silently swallowing a
        # real failure on a later refresh.
        category_item.setHidden(False)
        category_item.takeChildren()
        category_item.addChild(QTreeWidgetItem([f"Error: {error}"]))

    def _on_load_error(self, error: Exception) -> None:
        QMessageBox.warning(self, "Failed to load projects", str(error))

    # -- QEMU host / VM tree ----------------------------------------------

    @staticmethod
    def _load_qemu_hosts() -> list[QemuHost]:
        return [QemuHost(name=h["name"], uri=h["uri"]) for h in settings.load_qemu_hosts()]

    @staticmethod
    def _save_qemu_hosts(hosts: list[QemuHost]) -> None:
        settings.save_qemu_hosts([{"name": h.name, "uri": h.uri} for h in hosts])

    def _populate_qemu_hosts(self) -> None:
        if self._qemu_root_item is None:
            self._qemu_root_item = QTreeWidgetItem(["QEMU"])
            self._qemu_root_item.setData(0, IS_QEMU_ROOT_ROLE, True)
            self._tree.addTopLevelItem(self._qemu_root_item)
        self._qemu_root_item.takeChildren()
        for host in self._load_qemu_hosts():
            host_item = QTreeWidgetItem([host.name])
            host_item.setData(0, HOST_ROLE, host)
            host_item.setData(0, CHILDREN_LOADED_ROLE, False)
            host_item.addChild(QTreeWidgetItem(["Loading…"]))
            self._qemu_root_item.addChild(host_item)

    def _find_qemu_host_item(self, host: QemuHost) -> QTreeWidgetItem | None:
        if self._qemu_root_item is None:
            return None
        for i in range(self._qemu_root_item.childCount()):
            child = self._qemu_root_item.child(i)
            if child.data(0, HOST_ROLE) == host:
                return child
        return None

    def _load_qemu_vms(self, host_item: QTreeWidgetItem, host: QemuHost) -> None:
        async_utils.run_in_background(
            lambda: qemu_client.list_vms(host),
            on_result=lambda vms: self._populate_qemu_vms(host_item, host, vms),
            on_error=lambda error: self._populate_category_error(host_item, error),
        )

    def _populate_qemu_vms(
        self, host_item: QTreeWidgetItem, host: QemuHost, vms: list[QemuVm]
    ) -> None:
        host_item.takeChildren()
        if not vms:
            host_item.addChild(QTreeWidgetItem(["(no VMs)"]))
            return
        for vm in vms:
            item = QTreeWidgetItem([vm.name])
            item.setData(0, HOST_ROLE, host)
            item.setData(0, VM_ROLE, vm)
            item.setToolTip(0, f"State: {vm.state}")
            host_item.addChild(item)

    def _on_manage_hosts_clicked(self) -> None:
        dialog = ManageHostsDialog(self._load_qemu_hosts(), parent=self)
        dialog.exec()
        self._save_qemu_hosts(dialog.hosts())
        self._populate_qemu_hosts()

    def _run_qemu_power_action(self, host: QemuHost, vm: QemuVm, action: str) -> None:
        async_utils.run_in_background(
            lambda: qemu_client.power_action(host, vm.name, action),
            on_result=lambda _: self._on_qemu_power_action_done(host),
            on_error=self._on_session_error,
        )

    def _on_qemu_power_action_done(self, host: QemuHost) -> None:
        # Refresh the host's VM list so the state column (and SPICE port,
        # once it's actually running) reflects the change.
        host_item = self._find_qemu_host_item(host)
        if host_item is not None:
            self._load_qemu_vms(host_item, host)

    # -- Manually-configured RDP/SSH connections --------------------------

    @staticmethod
    def _load_manual_connections() -> list[ManualConnection]:
        return [
            ManualConnection(
                name=c["name"], host=c["host"], port=c["port"], kind=c["kind"], username=c.get("username")
            )
            for c in settings.load_manual_connections()
        ]

    @staticmethod
    def _save_manual_connections(connections: list[ManualConnection]) -> None:
        settings.save_manual_connections(
            [
                {
                    "name": c.name,
                    "host": c.host,
                    "port": c.port,
                    "kind": c.kind,
                    "username": c.username,
                }
                for c in connections
            ]
        )

    def _populate_manual_connections(self) -> None:
        if self._manual_root_item is None:
            self._manual_root_item = QTreeWidgetItem(["Manual"])
            self._manual_root_item.setData(0, IS_MANUAL_ROOT_ROLE, True)
            self._tree.addTopLevelItem(self._manual_root_item)
        self._manual_root_item.takeChildren()
        for connection in self._load_manual_connections():
            item = QTreeWidgetItem([connection.name])
            item.setData(0, MANUAL_CONNECTION_ROLE, connection)
            item.setToolTip(0, f"{connection.kind.upper()} {connection.host}:{connection.port}")
            self._manual_root_item.addChild(item)

    def _on_manage_manual_connections_clicked(self) -> None:
        dialog = ManageManualConnectionsDialog(self._load_manual_connections(), parent=self)
        dialog.exec()
        self._save_manual_connections(dialog.connections())
        self._populate_manual_connections()

    # -- Tree context menu: connect -------------------------------------------

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return

        if item.data(0, IS_GCP_ROOT_ROLE):
            self._show_gcp_root_context_menu(pos)
            return

        if item.data(0, IS_QEMU_ROOT_ROLE):
            self._show_qemu_root_context_menu(pos)
            return

        vm = item.data(0, VM_ROLE)
        if vm is not None:
            self._show_qemu_vm_context_menu(pos, item, vm)
            return

        if item.data(0, IS_MANUAL_ROOT_ROLE):
            self._show_manual_root_context_menu(pos)
            return

        manual_connection = item.data(0, MANUAL_CONNECTION_ROLE)
        if manual_connection is not None:
            self._show_manual_connection_context_menu(pos, manual_connection)
            return

        # A GCP project node — PROJECT_ID_ROLE set, but neither a VMs/
        # Buckets category (CATEGORY_ROLE) nor an instance leaf
        # (INSTANCE_ROLE).
        if (
            item.data(0, PROJECT_ID_ROLE) is not None
            and item.data(0, CATEGORY_ROLE) is None
            and item.data(0, INSTANCE_ROLE) is None
        ):
            menu = QMenu(self)
            menu.addAction("Refresh").triggered.connect(lambda: self._refresh_project(item))
            menu.exec(self._tree.viewport().mapToGlobal(pos))
            return

        instance = item.data(0, INSTANCE_ROLE)
        if instance is None:
            return

        menu = QMenu(self)
        rdp_action = menu.addAction("Connect via RDP")
        ssh_action = menu.addAction("Connect via SSH")
        menu.addSeparator()
        turn_on_action = menu.addAction("Turn On")
        turn_off_action = menu.addAction("Turn Off")
        menu.addSeparator()
        set_password_action = menu.addAction("Set Password…")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is rdp_action:
            self._start_session_from_instance(instance, "rdp")
        elif chosen is ssh_action:
            self._start_session_from_instance(instance, "ssh")
        elif chosen is turn_on_action:
            self._run_instance_power_action(instance, "start")
        elif chosen is turn_off_action:
            self._run_instance_power_action(instance, "stop")
        elif chosen is set_password_action:
            self._on_set_instance_password_clicked(instance)

    def _show_qemu_root_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Manage Hosts…").triggered.connect(self._on_manage_hosts_clicked)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _show_qemu_vm_context_menu(self, pos, item: QTreeWidgetItem, vm: QemuVm) -> None:
        host = item.data(0, HOST_ROLE)
        menu = QMenu(self)
        # SpiceWidget (and so "Connect via SPICE") is only available where
        # PyGObject/spice-glib are installed — see the SpiceWidget import
        # at the top of this file. VM discovery/power actions below don't
        # need it and stay available regardless.
        connect_action = menu.addAction("Connect via SPICE") if SpiceWidget is not None else None
        if connect_action is not None:
            menu.addSeparator()
        start_action = menu.addAction("Start")
        pause_action = menu.addAction("Pause")
        resume_action = menu.addAction("Resume")
        shutdown_action = menu.addAction("Shutdown")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if connect_action is not None and chosen is connect_action:
            self._connect_qemu(host, vm)
        elif chosen is start_action:
            self._run_qemu_power_action(host, vm, "start")
        elif chosen is pause_action:
            self._run_qemu_power_action(host, vm, "pause")
        elif chosen is resume_action:
            self._run_qemu_power_action(host, vm, "resume")
        elif chosen is shutdown_action:
            self._run_qemu_power_action(host, vm, "shutdown")

    def _show_manual_root_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Manage Connections…").triggered.connect(
            self._on_manage_manual_connections_clicked
        )
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _show_manual_connection_context_menu(self, pos, connection: ManualConnection) -> None:
        menu = QMenu(self)
        connect_action = menu.addAction(f"Connect via {connection.kind.upper()}")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is connect_action:
            self._start_session_from_manual_connection(connection)

    def _build_gcp_root_menu(self) -> QMenu | None:
        if self._account is None:
            return None
        menu = QMenu(self)
        menu.addAction("Select Projects…").triggered.connect(self._on_select_projects_clicked)
        menu.addAction("Sign out").triggered.connect(self._do_sign_out)
        return menu

    def _show_gcp_root_context_menu(self, pos) -> None:
        menu = self._build_gcp_root_menu()
        if menu is not None:
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        bucket = item.data(0, BUCKET_ROLE)
        if bucket is not None:
            self._open_bucket_browser(bucket)

    def _open_bucket_browser(self, bucket: GcsBucket) -> None:
        browser = BucketBrowserWidget(bucket, get_credentials=gcp_auth.get_credentials)
        self._owned_tab_widgets.add(browser)
        index = self._tabs.addTab(browser, bucket.name)
        self._tabs.setCurrentIndex(index)

    def _start_session_from_instance(self, instance: Instance, kind: str) -> None:
        username = settings.load_default_username()
        if username is None:
            username, ok = QInputDialog.getText(
                self, "Username", f"Username for {instance.name} (leave blank to be prompted):"
            )
            if not ok:
                return
            username = username.strip() or None

        password = None
        if kind == "rdp":
            # Not persisted anywhere (no keyring integration in this app) —
            # the embedded RDP client needs it upfront for the NLA
            # handshake, unlike external mstsc/xfreerdp which prompt in
            # their own window.
            password, ok = QInputDialog.getText(
                self,
                "Password",
                f"Password for {username or 'RDP'}@{instance.name}:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return

        self._connect(
            display_name=instance.name,
            project_id=instance.project_id,
            zone=instance.zone,
            instance_name=instance.name,
            network_interface=instance.network_interface,
            kind=kind,
            username=username,
            password=password,
        )

    def _run_instance_power_action(self, instance: Instance, action: str) -> None:
        if action == "stop":
            reply = QMessageBox.question(
                self,
                "Turn Off Instance",
                f"Turn off {instance.name}? Any unsaved work on the instance will be lost "
                "as it shuts down.",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        fn = gcp_client.start_instance if action == "start" else gcp_client.stop_instance
        async_utils.run_in_background(
            lambda: fn(gcp_auth.get_credentials(), instance.project_id, instance.zone, instance.name),
            on_result=lambda _: self._on_instance_power_action_done(instance),
            on_error=self._on_instance_action_error,
        )

    def _on_instance_power_action_done(self, instance: Instance) -> None:
        # The instance won't have reached its final state yet (start/stop
        # only submits the request) but this reflects the transitional
        # status (e.g. STOPPING) rather than leaving a stale one displayed.
        project_item = self._find_project_item(instance.project_id)
        if project_item is not None:
            self._refresh_project(project_item)

    def _find_project_item(self, project_id: str) -> QTreeWidgetItem | None:
        if self._gcp_root_item is None:
            return None
        for i in range(self._gcp_root_item.childCount()):
            child = self._gcp_root_item.child(i)
            if child.data(0, PROJECT_ID_ROLE) == project_id:
                return child
        return None

    def _on_set_instance_password_clicked(self, instance: Instance) -> None:
        # Pre-filled with the app's configured default username (the same
        # one RDP/SSH connections default to) rather than silently assuming
        # "Administrator" — that's rarely the account anyone actually wants
        # reset, and picking one quietly on the user's behalf is worse than
        # just asking.
        username, ok = QInputDialog.getText(
            self,
            "Set Password",
            f"Windows account to reset on {instance.name}:",
            QLineEdit.EchoMode.Normal,
            settings.load_default_username() or "",
        )
        if not ok or not username.strip():
            return
        username = username.strip()

        async_utils.run_in_background(
            lambda: gcp_client.reset_windows_password(
                gcp_auth.get_credentials(), instance.project_id, instance.zone, instance.name, username
            ),
            on_result=lambda credential: self._on_password_reset(instance, credential),
            on_error=self._on_instance_action_error,
        )

    def _on_password_reset(self, instance: Instance, credential: tuple[str, str]) -> None:
        username, password = credential
        QMessageBox.information(
            self,
            "Password Reset",
            f"New login for {instance.name} — shown once, not stored anywhere:\n\n"
            f"Username: {username}\nPassword: {password}",
        )

    def _on_instance_action_error(self, error: Exception) -> None:
        QMessageBox.warning(self, "Instance action failed", str(error))

    # -- Connect: tunnel, then embed SSH or launch external RDP ---------------

    def _connect(
        self,
        display_name: str,
        project_id: str,
        zone: str,
        instance_name: str,
        network_interface: str,
        kind: str,
        username: str | None,
        password: str | None = None,
    ) -> None:
        target = IapTunnelTarget(
            project=project_id,
            zone=zone,
            instance=instance_name,
            interface=network_interface,
            port=RDP_PORT if kind == "rdp" else SSH_PORT,
        )

        async_utils.run_in_background(
            lambda: self._start_tunnel(target),
            on_result=lambda tunnel: self._on_tunnel_ready(
                tunnel, display_name, kind, username, password
            ),
            on_error=self._on_session_error,
        )

    @staticmethod
    def _start_tunnel(target: IapTunnelTarget) -> BackgroundTunnel:
        tunnel = BackgroundTunnel(
            target, get_access_token=lambda: gcp_auth.get_credentials().token
        )
        tunnel.start()
        return tunnel

    def _on_tunnel_ready(
        self,
        tunnel: BackgroundTunnel,
        display_name: str,
        kind: str,
        username: str | None,
        password: str | None = None,
    ) -> None:
        session_id = self._next_session_id
        self._next_session_id += 1
        self._active_sessions[session_id] = (kind, tunnel)

        if kind == "ssh":
            self._embed_ssh(session_id, display_name, tunnel.port, username)
        else:
            self._embed_rdp(session_id, display_name, tunnel.port, username, password)

        label = f"{display_name} ({kind.upper()}) — 127.0.0.1:{tunnel.port}"
        self._active_sessions_dialog.add_session(session_id, label)

    def _embed_ssh(
        self,
        session_id: int,
        display_name: str,
        port: int,
        username: str | None,
        host: str = "127.0.0.1",
    ) -> None:
        target = f"{username}@{host}" if username else host
        terminal = TerminalWidget(["ssh", "-p", str(port), target])
        terminal.finished.connect(lambda: self._on_disconnect_requested(session_id))
        self._session_tab_widgets[session_id] = terminal
        self._owned_tab_widgets.add(terminal)
        index = self._tabs.addTab(terminal, display_name)
        self._tabs.setCurrentIndex(index)
        terminal.setFocus()

    def _embed_rdp(
        self,
        session_id: int,
        display_name: str,
        port: int,
        username: str | None,
        password: str | None,
        host: str = "127.0.0.1",
    ) -> None:
        rdp = RdpWidget(host, port, username or "", password or "")
        rdp.finished.connect(lambda: self._on_disconnect_requested(session_id))
        self._session_tab_widgets[session_id] = rdp
        self._owned_tab_widgets.add(rdp)
        index = self._tabs.addTab(rdp, display_name)
        self._tabs.setCurrentIndex(index)
        rdp.setFocus()

    # -- Connect: manually-configured RDP/SSH, direct (no tunnel) ---------

    def _start_session_from_manual_connection(self, connection: ManualConnection) -> None:
        username = connection.username or settings.load_default_username()
        if username is None:
            username, ok = QInputDialog.getText(
                self, "Username", f"Username for {connection.name} (leave blank to be prompted):"
            )
            if not ok:
                return
            username = username.strip() or None

        password = None
        if connection.kind == "rdp":
            password, ok = QInputDialog.getText(
                self,
                "Password",
                f"Password for {username or 'RDP'}@{connection.name}:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return

        session_id = self._next_session_id
        self._next_session_id += 1

        if connection.kind == "ssh":
            self._embed_ssh(session_id, connection.name, connection.port, username, host=connection.host)
        else:
            self._embed_rdp(
                session_id, connection.name, connection.port, username, password, host=connection.host
            )

        label = f"{connection.name} ({connection.kind.upper()}) — {connection.host}:{connection.port}"
        self._active_sessions_dialog.add_session(session_id, label)

    # -- Connect: QEMU/libvirt, tunnel over SSH, embed SPICE ------------------

    def _connect_qemu(self, host: QemuHost, vm: QemuVm) -> None:
        if SpiceWidget is None:
            QMessageBox.warning(
                self,
                "SPICE unavailable",
                "Embedded SPICE needs PyGObject/spice-glib, which aren't available on "
                "this platform — see docs/qemu-spice-status.md.",
            )
            return
        async_utils.run_in_background(
            lambda: self._start_qemu_tunnel(host, vm),
            on_result=lambda tunnel: self._on_qemu_tunnel_ready(tunnel, vm),
            on_error=self._on_session_error,
        )

    @staticmethod
    def _start_qemu_tunnel(host: QemuHost, vm: QemuVm) -> QemuTunnel:
        spice_port = qemu_client.get_vm_spice_port(host, vm.name)
        if spice_port is None:
            raise QemuApiError(f"{vm.name} has no SPICE port available — is it running?")
        tunnel = QemuTunnel(host.uri, spice_port)
        tunnel.start()
        return tunnel

    def _on_qemu_tunnel_ready(self, tunnel: QemuTunnel, vm: QemuVm) -> None:
        session_id = self._next_session_id
        self._next_session_id += 1
        self._active_sessions[session_id] = ("spice", tunnel)

        self._embed_spice(session_id, vm.name, tunnel.port)

        label = f"{vm.name} (SPICE) — 127.0.0.1:{tunnel.port}"
        self._active_sessions_dialog.add_session(session_id, label)

    def _embed_spice(self, session_id: int, display_name: str, port: int) -> None:
        spice = SpiceWidget("127.0.0.1", port)
        spice.finished.connect(lambda: self._on_disconnect_requested(session_id))
        self._session_tab_widgets[session_id] = spice
        self._owned_tab_widgets.add(spice)
        index = self._tabs.addTab(spice, display_name)
        self._tabs.setCurrentIndex(index)
        spice.setFocus()

    def _on_session_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if widget is not None:
            widget.setFocus()

    def _on_session_error(self, error: Exception) -> None:
        QMessageBox.warning(self, "Connection failed", str(error))

    # -- Disconnect ------------------------------------------------------

    def try_close_tab(self, widget: QWidget) -> bool:
        """Tear down `widget` if this view added it to (possibly shared)
        self._tabs, and report whether it did — see ToolModule.try_close_tab
        and MainWindow._on_session_tab_close_requested.
        """
        if widget not in self._owned_tab_widgets:
            return False
        session_id = next(
            (sid for sid, w in self._session_tab_widgets.items() if w is widget), None
        )
        if session_id is not None:
            self._on_disconnect_requested(session_id)
        else:
            # Owned but not a tracked session (e.g. a bucket browser tab)
            # — just a plain tab with nothing else to tear down.
            index = self._tabs.indexOf(widget)
            if index != -1:
                self._tabs.removeTab(index)
            self._owned_tab_widgets.discard(widget)
            widget.deleteLater()
        return True

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if not self.try_close_tab(widget):
            self._tabs.removeTab(index)
            widget.deleteLater()

    def _on_disconnect_requested(self, session_id: int) -> None:
        self._active_sessions_dialog.remove_session(session_id)

        widget = self._session_tab_widgets.pop(session_id, None)
        if widget is not None:
            index = self._tabs.indexOf(widget)
            if index != -1:
                self._tabs.removeTab(index)
            self._owned_tab_widgets.discard(widget)
            widget.close_session()
            widget.deleteLater()

        entry = self._active_sessions.pop(session_id, None)
        if entry is not None:
            _, tunnel = entry
            async_utils.run_in_background(tunnel.stop)

    def _stop_all_sessions(self) -> None:
        for widget in self._session_tab_widgets.values():
            widget.close_session()
        self._session_tab_widgets.clear()

        for _, tunnel in self._active_sessions.values():
            tunnel.stop(timeout=2)
        self._active_sessions.clear()

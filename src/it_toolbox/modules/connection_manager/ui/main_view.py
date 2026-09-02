from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, session_launcher, settings
from it_toolbox.core.auth import gcp_auth
from it_toolbox.core.iap_tunnel import IapTunnelTarget
from it_toolbox.core.tunnel_session import BackgroundTunnel
from it_toolbox.modules.connection_manager import gcp_client
from it_toolbox.modules.connection_manager.models import RDP_PORT, SSH_PORT, GcpProject, Instance
from it_toolbox.modules.connection_manager.ui.active_sessions_dialog import ActiveSessionsDialog
from it_toolbox.modules.connection_manager.ui.project_selection_dialog import (
    ProjectSelectionDialog,
)
from it_toolbox.widgets.terminal_widget import TerminalWidget

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole
INSTANCES_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1
INSTANCE_ROLE = Qt.ItemDataRole.UserRole + 2
IS_GCP_ROOT_ROLE = Qt.ItemDataRole.UserRole + 3


class ConnectionManagerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._account: str | None = None
        self._active_sessions: dict[int, tuple[str, BackgroundTunnel]] = {}
        self._session_tab_widgets: dict[int, TerminalWidget] = {}
        self._next_session_id = 1
        self._all_projects: list[GcpProject] = []

        self._active_sessions_dialog = ActiveSessionsDialog(parent=self)
        self._active_sessions_dialog.disconnect_requested.connect(self._on_disconnect_requested)

        self._status_label = QLabel("Not signed in")

        self._sign_in_button = QPushButton("Sign in with gcloud")
        self._sign_in_button.clicked.connect(self._on_sign_in_clicked)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self._status_label)
        top_bar.addStretch()
        top_bar.addWidget(self._sign_in_button)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name"])
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tabs.currentChanged.connect(self._on_session_tab_changed)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(self._tabs, 1)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_all_sessions)

        if not gcp_auth.is_available():
            self._status_label.setText(
                f"gcloud CLI not found — install it from {gcp_auth.INSTALL_URL} "
                "and relaunch."
            )
            self._sign_in_button.setEnabled(False)
            return

        self._status_label.setText("Checking for an active gcloud session…")
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
        else:
            self._status_label.setText("Not signed in")

    def _on_sign_in_clicked(self) -> None:
        self._status_label.setText("Signing in — check your browser…")
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
        self._status_label.setText(f"Signed in as {account} — loading projects…")
        async_utils.run_in_background(
            lambda: gcp_client.list_projects(gcp_auth.get_credentials()),
            on_result=self._populate_projects,
            on_error=self._on_load_error,
        )

    def _set_signed_out(self) -> None:
        self._account = None
        self._all_projects = []
        self._tree.clear()
        self._status_label.setText("Not signed in")
        self._sign_in_button.setEnabled(True)
        self._sign_in_button.setVisible(True)

    def _on_auth_error(self, error: Exception) -> None:
        self._sign_in_button.setEnabled(True)
        self._status_label.setText("Not signed in" if self._account is None else "Signed in")
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
            self._status_label.setText(
                f"Signed in as {self._account} — {len(projects)} project(s) found, "
                "pick which to show…"
            )
            dialog = ProjectSelectionDialog(projects, selected_ids=set(), parent=self)
            if dialog.exec() == ProjectSelectionDialog.DialogCode.Accepted:
                selected_ids = dialog.selected_project_ids()
                settings.save_selected_project_ids(selected_ids)
            else:
                selected_ids = set()

        self._apply_project_selection(selected_ids)

    def _apply_project_selection(self, selected_ids: set[str]) -> None:
        visible = [p for p in self._all_projects if p.project_id in selected_ids]
        self._status_label.setText(
            f"Signed in as {self._account} — showing {len(visible)} of "
            f"{len(self._all_projects)} project(s)"
        )

        self._tree.clear()
        gcp_category = QTreeWidgetItem(["GCP"])
        gcp_category.setData(0, IS_GCP_ROOT_ROLE, True)
        self._tree.addTopLevelItem(gcp_category)
        for project in visible:
            item = QTreeWidgetItem([project.display_name or project.project_id])
            item.setData(0, PROJECT_ID_ROLE, project.project_id)
            item.setData(0, INSTANCES_LOADED_ROLE, False)
            item.addChild(QTreeWidgetItem(["Loading…"]))
            gcp_category.addChild(item)
        gcp_category.setExpanded(True)

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
        project_id = item.data(0, PROJECT_ID_ROLE)
        already_loaded = item.data(0, INSTANCES_LOADED_ROLE)
        if project_id is None or already_loaded or self._account is None:
            return

        item.setData(0, INSTANCES_LOADED_ROLE, True)
        async_utils.run_in_background(
            lambda: gcp_client.list_instances(gcp_auth.get_credentials(), project_id),
            on_result=lambda instances: self._populate_instances(item, instances),
            on_error=lambda error: self._populate_instances_error(item, error),
        )

    def _populate_instances(self, project_item: QTreeWidgetItem, instances: list[Instance]) -> None:
        project_item.takeChildren()
        if not instances:
            project_item.addChild(QTreeWidgetItem(["(no instances)"]))
            return
        for instance in instances:
            item = QTreeWidgetItem([instance.name])
            item.setData(0, INSTANCE_ROLE, instance)
            item.setToolTip(0, f"Status: {instance.status}")
            project_item.addChild(item)

    def _populate_instances_error(self, project_item: QTreeWidgetItem, error: Exception) -> None:
        project_item.takeChildren()
        project_item.addChild(QTreeWidgetItem([f"Error: {error}"]))

    def _on_load_error(self, error: Exception) -> None:
        self._status_label.setText(f"Signed in as {self._account}")
        QMessageBox.warning(self, "Failed to load projects", str(error))

    # -- Tree context menu: connect -------------------------------------------

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return

        if item.data(0, IS_GCP_ROOT_ROLE):
            self._show_gcp_root_context_menu(pos)
            return

        instance = item.data(0, INSTANCE_ROLE)
        if instance is None:
            return

        menu = QMenu(self)
        rdp_action = menu.addAction("Connect via RDP")
        ssh_action = menu.addAction("Connect via SSH")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is rdp_action:
            self._start_session_from_instance(instance, "rdp")
        elif chosen is ssh_action:
            self._start_session_from_instance(instance, "ssh")

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

    def _start_session_from_instance(self, instance: Instance, kind: str) -> None:
        username = settings.load_default_username()
        if username is None:
            username, ok = QInputDialog.getText(
                self, "Username", f"Username for {instance.name} (leave blank to be prompted):"
            )
            if not ok:
                return
            username = username.strip() or None

        self._connect(
            display_name=instance.name,
            project_id=instance.project_id,
            zone=instance.zone,
            instance_name=instance.name,
            network_interface=instance.network_interface,
            kind=kind,
            username=username,
        )

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
    ) -> None:
        target = IapTunnelTarget(
            project=project_id,
            zone=zone,
            instance=instance_name,
            interface=network_interface,
            port=RDP_PORT if kind == "rdp" else SSH_PORT,
        )

        self._status_label.setText(f"Connecting to {display_name} via {kind.upper()}…")
        async_utils.run_in_background(
            lambda: self._start_tunnel(target),
            on_result=lambda tunnel: self._on_tunnel_ready(tunnel, display_name, kind, username),
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
        self, tunnel: BackgroundTunnel, display_name: str, kind: str, username: str | None
    ) -> None:
        self._status_label.setText(f"Signed in as {self._account}")

        session_id = self._next_session_id
        self._next_session_id += 1
        self._active_sessions[session_id] = (kind, tunnel)

        if kind == "ssh":
            self._embed_ssh(session_id, display_name, tunnel.port, username)
        else:
            try:
                session_launcher.launch_rdp("127.0.0.1", tunnel.port, username)
            except session_launcher.SessionLaunchError as exc:
                self._active_sessions.pop(session_id, None)
                tunnel.stop()
                QMessageBox.warning(self, "Connection failed", str(exc))
                return

        label = f"{display_name} ({kind.upper()}) — 127.0.0.1:{tunnel.port}"
        self._active_sessions_dialog.add_session(session_id, label)

    def _embed_ssh(self, session_id: int, display_name: str, port: int, username: str | None) -> None:
        target = f"{username}@127.0.0.1" if username else "127.0.0.1"
        terminal = TerminalWidget(["ssh", "-p", str(port), target])
        terminal.finished.connect(lambda: self._on_disconnect_requested(session_id))
        self._session_tab_widgets[session_id] = terminal
        index = self._tabs.addTab(terminal, display_name)
        self._tabs.setCurrentIndex(index)
        terminal.setFocus()

    def _on_session_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if widget is not None:
            widget.setFocus()

    def _on_session_error(self, error: Exception) -> None:
        self._status_label.setText(f"Signed in as {self._account}")
        QMessageBox.warning(self, "Connection failed", str(error))

    # -- Disconnect ------------------------------------------------------

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self._tabs.widget(index)
        session_id = next(
            (sid for sid, w in self._session_tab_widgets.items() if w is widget), None
        )
        if session_id is not None:
            self._on_disconnect_requested(session_id)

    def _on_disconnect_requested(self, session_id: int) -> None:
        self._active_sessions_dialog.remove_session(session_id)

        widget = self._session_tab_widgets.pop(session_id, None)
        if widget is not None:
            index = self._tabs.indexOf(widget)
            if index != -1:
                self._tabs.removeTab(index)
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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
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
from it_toolbox.modules.connection_manager.models import GcpProject, Instance
from it_toolbox.modules.connection_manager.ui.project_selection_dialog import (
    ProjectSelectionDialog,
)

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole
INSTANCES_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1
INSTANCE_ROLE = Qt.ItemDataRole.UserRole + 2
SESSION_ID_ROLE = Qt.ItemDataRole.UserRole

RDP_PORT = 3389
SSH_PORT = 22


class ConnectionManagerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._account: str | None = None
        self._active_sessions: dict[int, tuple[Instance, str, BackgroundTunnel]] = {}
        self._next_session_id = 1
        self._all_projects: list[GcpProject] = []

        self._status_label = QLabel("Not signed in")
        self._select_projects_button = QPushButton("Select Projects…")
        self._select_projects_button.setEnabled(False)
        self._select_projects_button.clicked.connect(self._on_select_projects_clicked)
        self._sign_in_button = QPushButton("Sign in with gcloud")
        self._sign_in_button.clicked.connect(self._on_sign_in_clicked)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self._status_label)
        top_bar.addStretch()
        top_bar.addWidget(self._select_projects_button)
        top_bar.addWidget(self._sign_in_button)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Zone", "Status"])
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        self._sessions_list = QListWidget()
        self._disconnect_button = QPushButton("Disconnect")
        self._disconnect_button.setEnabled(False)
        self._disconnect_button.clicked.connect(self._on_disconnect_clicked)
        self._sessions_list.itemSelectionChanged.connect(
            lambda: self._disconnect_button.setEnabled(bool(self._sessions_list.selectedItems()))
        )

        sessions_bar = QHBoxLayout()
        sessions_bar.addWidget(QLabel("Active sessions:"))
        sessions_bar.addWidget(self._sessions_list, 1)
        sessions_bar.addWidget(self._disconnect_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(self._tree)
        layout.addLayout(sessions_bar)

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

    # -- Sign in / out -----------------------------------------------------

    def _on_startup_account_checked(self, account: str | None) -> None:
        self._sign_in_button.setEnabled(True)
        if account is not None:
            self._set_signed_in(account)
        else:
            self._status_label.setText("Not signed in")

    def _on_sign_in_clicked(self) -> None:
        if self._account is not None:
            self._sign_in_button.setEnabled(False)
            async_utils.run_in_background(
                gcp_auth.sign_out,
                on_result=lambda _: self._set_signed_out(),
                on_error=self._on_auth_error,
            )
            return

        self._status_label.setText("Signing in — check your browser…")
        self._sign_in_button.setEnabled(False)
        async_utils.run_in_background(
            gcp_auth.sign_in,
            on_result=self._set_signed_in,
            on_error=self._on_auth_error,
        )

    def _set_signed_in(self, account: str) -> None:
        self._account = account
        self._sign_in_button.setEnabled(True)
        self._sign_in_button.setText("Sign out")
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
        self._sign_in_button.setText("Sign in with gcloud")
        self._select_projects_button.setEnabled(False)

    def _on_auth_error(self, error: Exception) -> None:
        self._sign_in_button.setEnabled(True)
        self._status_label.setText("Not signed in" if self._account is None else "Signed in")
        QMessageBox.warning(self, "gcloud auth failed", str(error))

    # -- Project / instance tree --------------------------------------------

    def _populate_projects(self, projects: list[GcpProject]) -> None:
        self._all_projects = projects
        self._select_projects_button.setEnabled(True)

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
        for project in visible:
            item = QTreeWidgetItem([project.display_name or project.project_id])
            item.setData(0, PROJECT_ID_ROLE, project.project_id)
            item.setData(0, INSTANCES_LOADED_ROLE, False)
            item.addChild(QTreeWidgetItem(["Loading…"]))
            self._tree.addTopLevelItem(item)

    def _on_select_projects_clicked(self) -> None:
        current_ids = settings.load_selected_project_ids() or set()
        dialog = ProjectSelectionDialog(self._all_projects, selected_ids=current_ids, parent=self)
        if dialog.exec() != ProjectSelectionDialog.DialogCode.Accepted:
            return
        selected_ids = dialog.selected_project_ids()
        settings.save_selected_project_ids(selected_ids)
        self._apply_project_selection(selected_ids)

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
            item = QTreeWidgetItem([instance.name, instance.zone, instance.status])
            item.setData(0, INSTANCE_ROLE, instance)
            project_item.addChild(item)

    def _populate_instances_error(self, project_item: QTreeWidgetItem, error: Exception) -> None:
        project_item.takeChildren()
        project_item.addChild(QTreeWidgetItem([f"Error: {error}"]))

    def _on_load_error(self, error: Exception) -> None:
        self._status_label.setText(f"Signed in as {self._account}")
        QMessageBox.warning(self, "Failed to load projects", str(error))

    # -- Connect (tunnel + launch RDP/SSH) -----------------------------------

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        instance = item.data(0, INSTANCE_ROLE)
        if instance is None:
            return

        menu = QMenu(self)
        rdp_action = menu.addAction("Connect via RDP")
        ssh_action = menu.addAction("Connect via SSH")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is rdp_action:
            self._start_session(instance, "rdp")
        elif chosen is ssh_action:
            self._start_session(instance, "ssh")

    def _start_session(self, instance: Instance, kind: str) -> None:
        username, ok = QInputDialog.getText(
            self, "Username", f"Username for {instance.name} (leave blank to be prompted):"
        )
        if not ok:
            return
        username = username.strip() or None

        target = IapTunnelTarget(
            project=instance.project_id,
            zone=instance.zone,
            instance=instance.name,
            interface=instance.network_interface,
            port=RDP_PORT if kind == "rdp" else SSH_PORT,
        )

        self._status_label.setText(f"Connecting to {instance.name} via {kind.upper()}…")
        async_utils.run_in_background(
            lambda: self._connect_and_launch(target, kind, username),
            on_result=lambda tunnel: self._on_session_started(instance, kind, tunnel),
            on_error=self._on_session_error,
        )

    @staticmethod
    def _connect_and_launch(
        target: IapTunnelTarget, kind: str, username: str | None
    ) -> BackgroundTunnel:
        tunnel = BackgroundTunnel(
            target, get_access_token=lambda: gcp_auth.get_credentials().token
        )
        port = tunnel.start()
        try:
            if kind == "rdp":
                session_launcher.launch_rdp("127.0.0.1", port, username)
            else:
                session_launcher.launch_ssh("127.0.0.1", port, username)
        except session_launcher.SessionLaunchError:
            tunnel.stop()
            raise
        return tunnel

    def _on_session_started(self, instance: Instance, kind: str, tunnel: BackgroundTunnel) -> None:
        self._status_label.setText(f"Signed in as {self._account}")

        session_id = self._next_session_id
        self._next_session_id += 1
        self._active_sessions[session_id] = (instance, kind, tunnel)

        item = QListWidgetItem(f"{instance.name} ({kind.upper()}) — 127.0.0.1:{tunnel.port}")
        item.setData(SESSION_ID_ROLE, session_id)
        self._sessions_list.addItem(item)

    def _on_session_error(self, error: Exception) -> None:
        self._status_label.setText(f"Signed in as {self._account}")
        QMessageBox.warning(self, "Connection failed", str(error))

    def _on_disconnect_clicked(self) -> None:
        items = self._sessions_list.selectedItems()
        if not items:
            return
        item = items[0]
        session_id = item.data(SESSION_ID_ROLE)
        self._sessions_list.takeItem(self._sessions_list.row(item))

        entry = self._active_sessions.pop(session_id, None)
        if entry is not None:
            _, _, tunnel = entry
            async_utils.run_in_background(tunnel.stop)

    def _stop_all_sessions(self) -> None:
        for _, _, tunnel in self._active_sessions.values():
            tunnel.stop(timeout=2)
        self._active_sessions.clear()

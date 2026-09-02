from google.oauth2.credentials import Credentials
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core.auth import gcp_oauth
from it_toolbox.core.settings import oauth_client_path
from it_toolbox.modules.connection_manager import gcp_client
from it_toolbox.modules.connection_manager.models import GcpProject, Instance

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole
INSTANCES_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1


class ConnectionManagerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._credentials: Credentials | None = None

        self._status_label = QLabel("Not signed in")
        self._sign_in_button = QPushButton("Sign in with Google")
        self._sign_in_button.clicked.connect(self._on_sign_in_clicked)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self._status_label)
        top_bar.addStretch()
        top_bar.addWidget(self._sign_in_button)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Zone", "Status"])
        self._tree.itemExpanded.connect(self._on_item_expanded)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(self._tree)

        if not gcp_oauth.is_configured():
            self._status_label.setText(
                f"OAuth client not configured — place your downloaded "
                f"'Desktop app' client JSON at:\n{oauth_client_path()}"
            )
            self._sign_in_button.setEnabled(False)
            return

        self._status_label.setText("Checking for a saved sign-in…")
        self._sign_in_button.setEnabled(False)
        async_utils.run_in_background(
            gcp_oauth.get_credentials,
            on_result=self._on_startup_credentials_checked,
            on_error=self._on_auth_error,
        )

    # -- Sign in / out -----------------------------------------------------

    def _on_startup_credentials_checked(self, credentials: Credentials | None) -> None:
        self._sign_in_button.setEnabled(True)
        if credentials is not None:
            self._set_signed_in(credentials)
        else:
            self._status_label.setText("Not signed in")

    def _on_sign_in_clicked(self) -> None:
        if self._credentials is not None:
            gcp_oauth.sign_out()
            self._credentials = None
            self._tree.clear()
            self._status_label.setText("Not signed in")
            self._sign_in_button.setText("Sign in with Google")
            return

        self._status_label.setText("Signing in — check your browser…")
        self._sign_in_button.setEnabled(False)
        async_utils.run_in_background(
            gcp_oauth.sign_in,
            on_result=self._set_signed_in,
            on_error=self._on_auth_error,
        )

    def _set_signed_in(self, credentials: Credentials) -> None:
        self._credentials = credentials
        self._sign_in_button.setEnabled(True)
        self._sign_in_button.setText("Sign out")
        self._status_label.setText("Signed in — loading projects…")
        async_utils.run_in_background(
            lambda: gcp_client.list_projects(credentials),
            on_result=self._populate_projects,
            on_error=self._on_load_error,
        )

    def _on_auth_error(self, error: Exception) -> None:
        self._sign_in_button.setEnabled(True)
        self._status_label.setText("Not signed in")
        QMessageBox.warning(self, "Sign-in failed", str(error))

    # -- Project / instance tree --------------------------------------------

    def _populate_projects(self, projects: list[GcpProject]) -> None:
        self._tree.clear()
        self._status_label.setText(f"Signed in — {len(projects)} project(s)")

        for project in projects:
            item = QTreeWidgetItem([project.display_name or project.project_id])
            item.setData(0, PROJECT_ID_ROLE, project.project_id)
            item.setData(0, INSTANCES_LOADED_ROLE, False)
            item.addChild(QTreeWidgetItem(["Loading…"]))
            self._tree.addTopLevelItem(item)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        project_id = item.data(0, PROJECT_ID_ROLE)
        already_loaded = item.data(0, INSTANCES_LOADED_ROLE)
        if project_id is None or already_loaded or self._credentials is None:
            return

        item.setData(0, INSTANCES_LOADED_ROLE, True)
        async_utils.run_in_background(
            lambda: gcp_client.list_instances(self._credentials, project_id),
            on_result=lambda instances: self._populate_instances(item, instances),
            on_error=lambda error: self._populate_instances_error(item, error),
        )

    def _populate_instances(self, project_item: QTreeWidgetItem, instances: list[Instance]) -> None:
        project_item.takeChildren()
        if not instances:
            project_item.addChild(QTreeWidgetItem(["(no instances)"]))
            return
        for instance in instances:
            project_item.addChild(
                QTreeWidgetItem([instance.name, instance.zone, instance.status])
            )

    def _populate_instances_error(self, project_item: QTreeWidgetItem, error: Exception) -> None:
        project_item.takeChildren()
        project_item.addChild(QTreeWidgetItem([f"Error: {error}"]))

    def _on_load_error(self, error: Exception) -> None:
        self._status_label.setText("Signed in")
        QMessageBox.warning(self, "Failed to load projects", str(error))

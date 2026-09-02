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
from it_toolbox.core.auth import gcp_auth
from it_toolbox.modules.connection_manager import gcp_client
from it_toolbox.modules.connection_manager.models import GcpProject, Instance

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole
INSTANCES_LOADED_ROLE = Qt.ItemDataRole.UserRole + 1


class ConnectionManagerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._account: str | None = None

        self._status_label = QLabel("Not signed in")
        self._sign_in_button = QPushButton("Sign in with gcloud")
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
        self._tree.clear()
        self._status_label.setText("Not signed in")
        self._sign_in_button.setEnabled(True)
        self._sign_in_button.setText("Sign in with gcloud")

    def _on_auth_error(self, error: Exception) -> None:
        self._sign_in_button.setEnabled(True)
        self._status_label.setText("Not signed in" if self._account is None else "Signed in")
        QMessageBox.warning(self, "gcloud auth failed", str(error))

    # -- Project / instance tree --------------------------------------------

    def _populate_projects(self, projects: list[GcpProject]) -> None:
        self._tree.clear()
        self._status_label.setText(f"Signed in as {self._account} — {len(projects)} project(s)")

        for project in projects:
            item = QTreeWidgetItem([project.display_name or project.project_id])
            item.setData(0, PROJECT_ID_ROLE, project.project_id)
            item.setData(0, INSTANCES_LOADED_ROLE, False)
            item.addChild(QTreeWidgetItem(["Loading…"]))
            self._tree.addTopLevelItem(item)

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
            project_item.addChild(
                QTreeWidgetItem([instance.name, instance.zone, instance.status])
            )

    def _populate_instances_error(self, project_item: QTreeWidgetItem, error: Exception) -> None:
        project_item.takeChildren()
        project_item.addChild(QTreeWidgetItem([f"Error: {error}"]))

    def _on_load_error(self, error: Exception) -> None:
        self._status_label.setText(f"Signed in as {self._account}")
        QMessageBox.warning(self, "Failed to load projects", str(error))

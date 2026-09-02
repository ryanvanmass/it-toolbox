from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import settings
from it_toolbox.modules.connection_manager.models import RDP_PORT, SSH_PORT, Connection, Instance


class ConnectionDialog(QDialog):
    """Add (from a live GCP instance) or edit a saved connection profile.

    The underlying GCE target (project/zone/instance/interface) is shown
    read-only — changing which VM a saved connection points at means
    re-saving it from the tree, rather than editing it here.
    """

    def __init__(
        self,
        instance: Instance | None = None,
        connection: Connection | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if (instance is None) == (connection is None):
            raise ValueError("pass exactly one of instance or connection")

        self.setWindowTitle("Edit Connection" if connection else "Save Connection")

        self._name_edit = QLineEdit()
        self._type_combo = QComboBox()
        self._type_combo.addItems(["RDP", "SSH"])
        self._username_edit = QLineEdit()
        self._username_edit.setPlaceholderText("(leave blank to be prompted)")
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("(optional)")

        if connection is not None:
            self._connection_id = connection.id
            self._project_id = connection.project_id
            self._zone = connection.zone
            self._instance_name = connection.instance_name
            self._network_interface = connection.network_interface
            self._name_edit.setText(connection.name)
            self._type_combo.setCurrentText(connection.type.upper())
            self._username_edit.setText(connection.username or "")
            self._folder_edit.setText(connection.folder or "")
        else:
            self._connection_id = None
            self._project_id = instance.project_id
            self._zone = instance.zone
            self._instance_name = instance.name
            self._network_interface = instance.network_interface
            self._name_edit.setText(instance.name)
            self._username_edit.setText(settings.load_default_username() or "")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("Type:", self._type_combo)
        form.addRow("Username:", self._username_edit)
        form.addRow("Folder:", self._folder_edit)
        form.addRow("Project:", QLabel(self._project_id))
        form.addRow("Zone:", QLabel(self._zone))
        form.addRow("Instance:", QLabel(self._instance_name))

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Name required", "Please enter a name for this connection.")
            return
        self.accept()

    def connection(self) -> Connection:
        kind = self._type_combo.currentText().lower()
        return Connection(
            id=self._connection_id,
            name=self._name_edit.text().strip(),
            type=kind,
            project_id=self._project_id,
            zone=self._zone,
            instance_name=self._instance_name,
            network_interface=self._network_interface,
            remote_port=RDP_PORT if kind == "rdp" else SSH_PORT,
            username=self._username_edit.text().strip() or None,
            folder=self._folder_edit.text().strip() or None,
            last_used_at=None,
            created_at=None,
        )

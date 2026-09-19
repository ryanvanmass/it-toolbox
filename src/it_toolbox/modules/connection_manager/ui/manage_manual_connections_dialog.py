"""CRUD dialog for manually-configured RDP/SSH connections — no account,
project, or host discovery involved; the user just registers a host,
port, and protocol directly. Mirrors manage_hosts_dialog.py's shape.

Optionally routed through an SSH gateway (core/ssh_tunnel.py) -- mirrors
mRemoteNG's SSH-tunneling feature, e.g. reaching an internal RDP host
through a bastion the client machine can't otherwise reach directly. The
gateway is authenticated with the user's existing SSH keys/agent, same
as every other SSH use in this app -- no separate password field here.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules.connection_manager.models import RDP_PORT, SSH_PORT, ManualConnection

CONNECTION_ROLE = Qt.ItemDataRole.UserRole

_DEFAULT_PORTS = {"rdp": RDP_PORT, "ssh": SSH_PORT}


class _ConnectionEditDialog(QDialog):
    """Add or edit a single connection's name/host/port/kind/username."""

    def __init__(self, connection: ManualConnection | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Connection" if connection else "Add Connection")

        self._name_edit = QLineEdit(connection.name if connection else "")
        self._host_edit = QLineEdit(connection.host if connection else "")
        self._host_edit.setPlaceholderText("hostname or IP")

        self._kind_combo = QComboBox()
        self._kind_combo.addItem("RDP", "rdp")
        self._kind_combo.addItem("SSH", "ssh")
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)

        self._username_edit = QLineEdit(connection.username if connection and connection.username else "")
        self._username_edit.setPlaceholderText("leave blank to use the default / be prompted")

        if connection:
            index = self._kind_combo.findData(connection.kind)
            if index != -1:
                self._kind_combo.setCurrentIndex(index)
            self._port_spin.setValue(connection.port)
        else:
            self._port_spin.setValue(_DEFAULT_PORTS["rdp"])

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("Host:", self._host_edit)
        form.addRow("Kind:", self._kind_combo)
        form.addRow("Port:", self._port_spin)
        form.addRow("Username:", self._username_edit)

        # -- Optional SSH gateway --------------------------------------------
        has_gateway = bool(connection and connection.gateway_host)
        self._gateway_checkbox = QCheckBox("Connect via an SSH gateway")
        self._gateway_checkbox.setChecked(has_gateway)
        self._gateway_checkbox.toggled.connect(self._on_gateway_toggled)

        self._gateway_host_edit = QLineEdit(connection.gateway_host if has_gateway else "")
        self._gateway_host_edit.setPlaceholderText("bastion hostname or IP")
        self._gateway_port_spin = QSpinBox()
        self._gateway_port_spin.setRange(1, 65535)
        self._gateway_port_spin.setValue(connection.gateway_port if connection else SSH_PORT)
        self._gateway_username_edit = QLineEdit(
            connection.gateway_username if has_gateway and connection.gateway_username else ""
        )
        self._gateway_username_edit.setPlaceholderText("leave blank to use the local SSH default")

        gateway_form = QFormLayout()
        gateway_form.addRow("Gateway host:", self._gateway_host_edit)
        gateway_form.addRow("Gateway port:", self._gateway_port_spin)
        gateway_form.addRow("Gateway username:", self._gateway_username_edit)
        gateway_box_layout = QVBoxLayout()
        gateway_box_layout.addWidget(self._gateway_checkbox)
        gateway_box_layout.addLayout(gateway_form)
        gateway_box = QGroupBox("SSH Gateway")
        gateway_box.setLayout(gateway_box_layout)
        self._on_gateway_toggled(has_gateway)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(gateway_box)
        layout.addWidget(buttons)

    def _on_gateway_toggled(self, checked: bool) -> None:
        self._gateway_host_edit.setEnabled(checked)
        self._gateway_port_spin.setEnabled(checked)
        self._gateway_username_edit.setEnabled(checked)

    def _on_kind_changed(self, index: int) -> None:
        # Only auto-fill the port when it still matches the *other*
        # kind's default — an explicit non-default port (a forwarded/
        # nonstandard one) is left alone when switching kinds.
        kind = self._kind_combo.itemData(index)
        other_default = _DEFAULT_PORTS["ssh"] if kind == "rdp" else _DEFAULT_PORTS["rdp"]
        if self._port_spin.value() == other_default:
            self._port_spin.setValue(_DEFAULT_PORTS[kind])

    def connection(self) -> ManualConnection:
        gateway_enabled = self._gateway_checkbox.isChecked()
        return ManualConnection(
            name=self._name_edit.text().strip(),
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            kind=self._kind_combo.currentData(),
            username=self._username_edit.text().strip() or None,
            gateway_host=self._gateway_host_edit.text().strip() if gateway_enabled else None,
            gateway_port=self._gateway_port_spin.value(),
            gateway_username=(
                self._gateway_username_edit.text().strip() or None if gateway_enabled else None
            ),
        )


class ManageManualConnectionsDialog(QDialog):
    """Lets the user add, edit, and remove manually-configured connections.

    Edits apply to the in-dialog list immediately (add/edit/remove); the
    caller reads back the final list via connections() once this closes
    and is responsible for persisting it (settings.save_manual_connections)
    — there's no separate "cancel all changes" step.
    """

    def __init__(self, connections: list[ManualConnection], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Connections")
        self.resize(460, 320)

        self._list = QListWidget()
        for connection in connections:
            self._add_list_item(connection)

        add_button = QPushButton("Add…")
        add_button.clicked.connect(self._on_add_clicked)
        edit_button = QPushButton("Edit…")
        edit_button.clicked.connect(self._on_edit_clicked)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._on_remove_clicked)

        buttons_bar = QHBoxLayout()
        buttons_bar.addWidget(add_button)
        buttons_bar.addWidget(edit_button)
        buttons_bar.addWidget(remove_button)
        buttons_bar.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_bar = QHBoxLayout()
        close_bar.addStretch()
        close_bar.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons_bar)
        layout.addLayout(close_bar)

    @staticmethod
    def _list_label(connection: ManualConnection) -> str:
        label = f"{connection.name} — {connection.kind.upper()} {connection.host}:{connection.port}"
        if connection.gateway_host:
            label += f" (via {connection.gateway_host})"
        return label

    def _add_list_item(self, connection: ManualConnection) -> None:
        item = QListWidgetItem(self._list_label(connection))
        item.setData(CONNECTION_ROLE, connection)
        self._list.addItem(item)

    def _on_add_clicked(self) -> None:
        dialog = _ConnectionEditDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        connection = dialog.connection()
        if connection.name and connection.host:
            self._add_list_item(connection)

    def _on_edit_clicked(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        dialog = _ConnectionEditDialog(item.data(CONNECTION_ROLE), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        connection = dialog.connection()
        if connection.name and connection.host:
            item.setText(self._list_label(connection))
            item.setData(CONNECTION_ROLE, connection)

    def _on_remove_clicked(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._list.takeItem(self._list.row(item))

    def connections(self) -> list[ManualConnection]:
        return [self._list.item(i).data(CONNECTION_ROLE) for i in range(self._list.count())]

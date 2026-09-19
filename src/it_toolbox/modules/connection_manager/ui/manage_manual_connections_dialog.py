"""CRUD dialog for manually-configured RDP/SSH/SFTP/FTP connections — no
account, project, or host discovery involved; the user just registers a
host, port, and protocol directly. Mirrors manage_hosts_dialog.py's
shape, plus (for SFTP/FTP only) an optional remembered password field
shaped like manage_glinet_hosts_dialog.py's: this dialog never imports
core/settings's encryption helpers, and a blank password field when
editing an existing connection means "keep the currently-stored
password" — the caller (ConnectionManagerView) encrypts and persists
whatever was actually changed after this dialog closes.

A connection (of any kind) can optionally be routed through an SSH
gateway (core/ssh_tunnel.py) -- mirrors mRemoteNG's SSH-tunneling
feature, e.g. reaching an internal host through a bastion the client
machine can't otherwise reach directly. The gateway defaults to the
user's existing SSH keys/agent, same as every other SSH use in this
app; an optional password field is a real, if less secure, opt-in for a
gateway that only accepts password auth (see
ManualConnection.gateway_password's own docstring for the plaintext-at-
rest tradeoff).
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
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules.connection_manager.models import (
    FTP_PORT,
    RDP_PORT,
    SFTP_PORT,
    SSH_PORT,
    ManualConnection,
)

CONNECTION_ROLE = Qt.ItemDataRole.UserRole
NEW_PASSWORD_ROLE = Qt.ItemDataRole.UserRole + 1

_DEFAULT_PORTS = {"rdp": RDP_PORT, "ssh": SSH_PORT, "sftp": SFTP_PORT, "ftp": FTP_PORT}
_PASSWORD_KINDS = ("sftp", "ftp")


class _ConnectionEditDialog(QDialog):
    """Add or edit a single connection's name/host/port/kind/username
    (plus, for SFTP/FTP, a rememberable password)."""

    def __init__(self, connection: ManualConnection | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Connection" if connection else "Add Connection")

        self._name_edit = QLineEdit(connection.name if connection else "")
        self._host_edit = QLineEdit(connection.host if connection else "")
        self._host_edit.setPlaceholderText("hostname or IP")

        self._kind_combo = QComboBox()
        self._kind_combo.addItem("RDP", "rdp")
        self._kind_combo.addItem("SSH", "ssh")
        self._kind_combo.addItem("SFTP", "sftp")
        self._kind_combo.addItem("FTP", "ftp")
        self._current_kind = connection.kind if connection else "rdp"
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)

        self._username_edit = QLineEdit(connection.username if connection and connection.username else "")
        self._username_edit.setPlaceholderText("leave blank to use the default / be prompted")

        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText(
            "Leave blank to keep the existing password" if connection else "Leave blank to be prompted"
        )
        self._password_hint = QLabel(
            "Leave the password blank to keep the one already stored."
            if connection
            else "Leave the password blank to be prompted for it (or a key) each time."
        )
        self._password_hint.setWordWrap(True)

        if connection:
            index = self._kind_combo.findData(connection.kind)
            if index != -1:
                self._kind_combo.setCurrentIndex(index)
            self._port_spin.setValue(connection.port)
        else:
            self._port_spin.setValue(_DEFAULT_PORTS["rdp"])

        self._form = QFormLayout()
        self._form.addRow("Name:", self._name_edit)
        self._form.addRow("Host:", self._host_edit)
        self._form.addRow("Kind:", self._kind_combo)
        self._form.addRow("Port:", self._port_spin)
        self._form.addRow("Username:", self._username_edit)
        self._form.addRow("Password:", self._password_edit)
        self._form.addRow("", self._password_hint)

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

        self._gateway_password_edit = QLineEdit(
            connection.gateway_password if has_gateway and connection.gateway_password else ""
        )
        self._gateway_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._gateway_password_edit.setPlaceholderText("leave blank to use keys/agent instead")
        gateway_password_note = QLabel(
            "Only needed if the gateway doesn't accept this app's SSH key -- stored as plain "
            "text (this app has no credential vault)."
        )
        gateway_password_note.setWordWrap(True)
        gateway_password_note.setStyleSheet("color: gray;")

        self._gateway_prompt_password_checkbox = QCheckBox("Prompt for it instead of storing it")
        self._gateway_prompt_password_checkbox.setChecked(
            has_gateway and connection.gateway_prompt_for_password
        )
        self._gateway_prompt_password_checkbox.toggled.connect(self._on_gateway_prompt_password_toggled)

        gateway_form = QFormLayout()
        gateway_form.addRow("Gateway host:", self._gateway_host_edit)
        gateway_form.addRow("Gateway port:", self._gateway_port_spin)
        gateway_form.addRow("Gateway username:", self._gateway_username_edit)
        gateway_form.addRow("Gateway password:", self._gateway_password_edit)
        gateway_form.addRow("", gateway_password_note)
        gateway_form.addRow("", self._gateway_prompt_password_checkbox)
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
        layout.addLayout(self._form)
        layout.addWidget(gateway_box)
        layout.addWidget(buttons)

        self._original_password_encrypted = connection.password_encrypted if connection else None
        self._update_password_field_visibility(self._current_kind)

    def _on_gateway_toggled(self, checked: bool) -> None:
        self._gateway_host_edit.setEnabled(checked)
        self._gateway_port_spin.setEnabled(checked)
        self._gateway_username_edit.setEnabled(checked)
        self._gateway_prompt_password_checkbox.setEnabled(checked)
        # The password field's own enabled state is also gated on the
        # "prompt instead" checkbox -- re-derive it here rather than just
        # setting it to `checked`, so re-enabling the gateway section
        # doesn't also re-enable a field "prompt instead" says to leave
        # alone.
        self._on_gateway_prompt_password_toggled(self._gateway_prompt_password_checkbox.isChecked())

    def _on_gateway_prompt_password_toggled(self, checked: bool) -> None:
        gateway_enabled = self._gateway_checkbox.isChecked()
        self._gateway_password_edit.setEnabled(gateway_enabled and not checked)
        if checked:
            # Prompting each time means never storing one -- clear any
            # value left over from before this was checked, rather than
            # just hiding a stale password that would otherwise get
            # silently written back out to disk (connection() would return
            # None for it regardless, since it's gated on this same
            # checkbox, but leaving stale text in a disabled field the
            # user can't see is exactly the kind of thing that no longer
            # reflects what's actually stored being confusing later).
            self._gateway_password_edit.clear()

    def _on_kind_changed(self, index: int) -> None:
        # Only auto-fill the port when it still matches the *previous*
        # kind's own default — an explicit non-default port (a forwarded/
        # nonstandard one) is left alone when switching kinds.
        kind = self._kind_combo.itemData(index)
        if self._port_spin.value() == _DEFAULT_PORTS.get(self._current_kind):
            self._port_spin.setValue(_DEFAULT_PORTS[kind])
        self._current_kind = kind
        self._update_password_field_visibility(kind)

    def _update_password_field_visibility(self, kind: str) -> None:
        # RDP/SSH never persist a password (see ManualConnection's
        # docstring) -- only SFTP/FTP get the "remember password" field.
        visible = kind in _PASSWORD_KINDS
        self._password_edit.setVisible(visible)
        self._password_hint.setVisible(visible)
        password_label = self._form.labelForField(self._password_edit)
        if password_label is not None:
            password_label.setVisible(visible)

    def connection(self) -> ManualConnection:
        gateway_enabled = self._gateway_checkbox.isChecked()
        return ManualConnection(
            name=self._name_edit.text().strip(),
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            kind=self._kind_combo.currentData(),
            username=self._username_edit.text().strip() or None,
            password_encrypted=self._original_password_encrypted,
            gateway_host=self._gateway_host_edit.text().strip() if gateway_enabled else None,
            gateway_port=self._gateway_port_spin.value(),
            gateway_username=(
                self._gateway_username_edit.text().strip() or None if gateway_enabled else None
            ),
            gateway_password=(
                self._gateway_password_edit.text() or None if gateway_enabled else None
            ),
            gateway_prompt_for_password=(
                gateway_enabled and self._gateway_prompt_password_checkbox.isChecked()
            ),
        )

    def new_password(self) -> str | None:
        """The plaintext password the user actually typed for an SFTP/FTP
        connection, or None if the field was left blank (meaning "keep
        the existing password", or "none stored yet")."""
        if self._kind_combo.currentData() not in _PASSWORD_KINDS:
            return None
        return self._password_edit.text() or None


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

    def _add_list_item(self, connection: ManualConnection, new_password: str | None = None) -> None:
        item = QListWidgetItem(self._list_label(connection))
        item.setData(CONNECTION_ROLE, connection)
        item.setData(NEW_PASSWORD_ROLE, new_password)
        self._list.addItem(item)

    def _on_add_clicked(self) -> None:
        dialog = _ConnectionEditDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        connection = dialog.connection()
        if connection.name and connection.host:
            self._add_list_item(connection, dialog.new_password())

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
            item.setData(NEW_PASSWORD_ROLE, dialog.new_password())

    def _on_remove_clicked(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._list.takeItem(self._list.row(item))

    def connections(self) -> list[ManualConnection]:
        return [self._list.item(i).data(CONNECTION_ROLE) for i in range(self._list.count())]

    def new_passwords(self) -> list[str | None]:
        """New plaintext passwords typed for each SFTP/FTP connection,
        same order/length as connections() — None at an index means that
        connection's password wasn't touched (RDP/SSH always give None
        here; unchanged for SFTP/FTP too)."""
        return [self._list.item(i).data(NEW_PASSWORD_ROLE) for i in range(self._list.count())]

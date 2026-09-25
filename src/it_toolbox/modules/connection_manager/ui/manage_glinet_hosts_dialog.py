"""CRUD dialog for GL.iNet router registrations — mirrors
manage_hosts_dialog.py's shape (no account-based discovery, the user just
registers each router), with an added password field.

Stays settings-agnostic like ManageHostsDialog: it never imports
core/settings's encryption helpers. A blank password field when editing an
existing host means "keep the currently-stored password" — the dialog
tracks the plaintext the user actually typed separately from
GlinetHost.password_encrypted, and the caller (ConnectionManagerView)
encrypts and persists whatever was actually changed after this dialog
closes.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules.connection_manager.models import GlinetHost

HOST_ROLE = Qt.ItemDataRole.UserRole
NEW_PASSWORD_ROLE = Qt.ItemDataRole.UserRole + 1


class _GlinetHostEditDialog(QDialog):
    """Add or edit a single GL.iNet host's registration."""

    def __init__(self, host: GlinetHost | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit GL.iNet Host" if host else "Add GL.iNet Host")

        self._name_edit = QLineEdit(host.name if host else "")
        self._url_edit = QLineEdit(host.url if host else "https://192.168.8.1/rpc")
        self._url_edit.setPlaceholderText("https://192.168.8.1/rpc")
        self._username_edit = QLineEdit(host.username if host else "root")
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText(
            "Leave blank to keep the existing password" if host else ""
        )
        self._verify_ssl_checkbox = QCheckBox("Verify SSL certificate")
        self._verify_ssl_checkbox.setChecked(host.verify_ssl if host else False)

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("URL:", self._url_edit)
        form.addRow("Username:", self._username_edit)
        form.addRow("Password:", self._password_edit)
        form.addRow("", self._verify_ssl_checkbox)
        if host is not None:
            hint = QLabel("Leave the password blank to keep the one already stored.")
            hint.setWordWrap(True)
            form.addRow("", hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._original_password_encrypted = host.password_encrypted if host else None

    def host(self) -> GlinetHost:
        return GlinetHost(
            name=self._name_edit.text().strip(),
            url=self._url_edit.text().strip(),
            username=self._username_edit.text().strip() or "root",
            verify_ssl=self._verify_ssl_checkbox.isChecked(),
            password_encrypted=self._original_password_encrypted,
        )

    def new_password(self) -> str | None:
        """The plaintext password the user actually typed, or None if the
        field was left blank (meaning "keep the existing password").
        """
        return self._password_edit.text() or None


class ManageGlinetHostsDialog(QDialog):
    """Lets the user add, edit, and remove registered GL.iNet hosts.

    Edits apply to the in-dialog list immediately (add/edit/remove); the
    caller reads back the final list via hosts() (and any freshly-typed
    passwords via new_passwords()) once this closes and is responsible for
    encrypting/persisting them — there's no separate "cancel all changes"
    step, matching ManageHostsDialog's contract.
    """

    def __init__(self, hosts: list[GlinetHost], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage GL.iNet Hosts")
        self.resize(480, 320)

        self._list = QListWidget()
        for host in hosts:
            self._add_list_item(host, new_password=None)

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

    def _add_list_item(self, host: GlinetHost, new_password: str | None) -> None:
        item = QListWidgetItem(f"{host.name} — {host.url}")
        item.setData(HOST_ROLE, host)
        item.setData(NEW_PASSWORD_ROLE, new_password)
        self._list.addItem(item)

    def _on_add_clicked(self) -> None:
        dialog = _GlinetHostEditDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host = dialog.host()
        if host.name and host.url:
            self._add_list_item(host, dialog.new_password())

    def _on_edit_clicked(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        dialog = _GlinetHostEditDialog(item.data(HOST_ROLE), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host = dialog.host()
        if host.name and host.url:
            item.setText(f"{host.name} — {host.url}")
            item.setData(HOST_ROLE, host)
            item.setData(NEW_PASSWORD_ROLE, dialog.new_password())

    def _on_remove_clicked(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._list.takeItem(self._list.row(item))

    def hosts(self) -> list[GlinetHost]:
        return [self._list.item(i).data(HOST_ROLE) for i in range(self._list.count())]

    def new_passwords(self) -> list[str | None]:
        """New plaintext passwords typed for each host, same order/length
        as hosts() — None at an index means that host's password wasn't
        touched and should stay as its current password_encrypted value.
        """
        return [self._list.item(i).data(NEW_PASSWORD_ROLE) for i in range(self._list.count())]

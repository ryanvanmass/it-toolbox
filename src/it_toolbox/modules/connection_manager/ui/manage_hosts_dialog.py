"""CRUD dialog for QEMU/libvirt host registrations (name + libvirt
connection URI, e.g. "qemu+ssh://user@host/system") — mirrors
virt-connect's "Add host" flow, since unlike GCP projects there's no
account-based discovery of QEMU hosts; the user just registers them.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules.connection_manager.models import QemuHost

HOST_ROLE = Qt.ItemDataRole.UserRole


class _HostEditDialog(QDialog):
    """Add or edit a single host's name + URI."""

    def __init__(self, host: QemuHost | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Host" if host else "Add Host")

        self._name_edit = QLineEdit(host.name if host else "")
        self._uri_edit = QLineEdit(host.uri if host else "")
        self._uri_edit.setPlaceholderText("qemu+ssh://user@host/system")

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("URI:", self._uri_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def host(self) -> QemuHost:
        return QemuHost(name=self._name_edit.text().strip(), uri=self._uri_edit.text().strip())


class ManageHostsDialog(QDialog):
    """Lets the user add, edit, and remove registered QEMU/libvirt hosts.

    Edits apply to the in-dialog list immediately (add/edit/remove); the
    caller reads back the final list via hosts() once this closes and is
    responsible for persisting it (settings.save_qemu_hosts) — there's no
    separate "cancel all changes" step.
    """

    def __init__(self, hosts: list[QemuHost], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage QEMU Hosts")
        self.resize(420, 320)

        self._list = QListWidget()
        for host in hosts:
            self._add_list_item(host)

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

    def _add_list_item(self, host: QemuHost) -> None:
        item = QListWidgetItem(f"{host.name} — {host.uri}")
        item.setData(HOST_ROLE, host)
        self._list.addItem(item)

    def _on_add_clicked(self) -> None:
        dialog = _HostEditDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host = dialog.host()
        if host.name and host.uri:
            self._add_list_item(host)

    def _on_edit_clicked(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        dialog = _HostEditDialog(item.data(HOST_ROLE), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host = dialog.host()
        if host.name and host.uri:
            item.setText(f"{host.name} — {host.uri}")
            item.setData(HOST_ROLE, host)

    def _on_remove_clicked(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._list.takeItem(self._list.row(item))

    def hosts(self) -> list[QemuHost]:
        return [self._list.item(i).data(HOST_ROLE) for i in range(self._list.count())]

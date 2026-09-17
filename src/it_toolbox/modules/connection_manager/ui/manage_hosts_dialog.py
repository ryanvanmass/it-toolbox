"""CRUD dialog for QEMU/libvirt host registrations (name + libvirt
connection URI, e.g. "qemu+ssh://user@host/system") — mirrors
virt-connect's "Add host" flow, since unlike GCP projects there's no
account-based discovery of QEMU hosts; the user just registers them.

Also configures each host's own defaults for CreateVmDialog (memory/
vCPUs/disk size/disk pool/network/ISO pool/OS variant) -- plain
text/number fields, not a live pool/network picker the way
CreateVmDialog's own combos are. This dialog has never done live
discovery against a host (URI itself isn't validated either), and
adding it here would mean an async round-trip just to edit a host's
saved name/defaults -- pool/network/os-variant defaults are matched by
name against whatever CreateVmDialog actually discovers live at deploy
time, with a stale/typo'd name just silently falling back to the
dialog's normal default rather than erroring.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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

from it_toolbox.modules.connection_manager.models import QemuHost

HOST_ROLE = Qt.ItemDataRole.UserRole

# 0 displays as the special-value text below and maps back to None
# (meaning "no override, use CreateVmDialog's own hardcoded default") --
# real memory/vCPU/disk-size values are never 0, so there's no ambiguity.
_UNSET_SPIN_VALUE = 0
_UNSET_LABEL = "(dialog default)"


def _make_optional_spin(maximum: int, suffix: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(_UNSET_SPIN_VALUE, maximum)
    spin.setSpecialValueText(_UNSET_LABEL)
    if suffix:
        spin.setSuffix(suffix)
    return spin


class _HostEditDialog(QDialog):
    """Add or edit a single host's name/URI and its CreateVmDialog defaults."""

    def __init__(self, host: QemuHost | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Host" if host else "Add Host")

        self._name_edit = QLineEdit(host.name if host else "")
        self._uri_edit = QLineEdit(host.uri if host else "")
        self._uri_edit.setPlaceholderText("qemu+ssh://user@host/system")

        self._memory_spin = _make_optional_spin(1_048_576, " MiB")
        self._memory_spin.setValue((host.default_memory_mib if host else None) or _UNSET_SPIN_VALUE)

        self._vcpus_spin = _make_optional_spin(64)
        self._vcpus_spin.setValue((host.default_vcpus if host else None) or _UNSET_SPIN_VALUE)

        self._disk_spin = _make_optional_spin(16_384, " GiB")
        self._disk_spin.setValue((host.default_disk_gib if host else None) or _UNSET_SPIN_VALUE)

        self._disk_pool_edit = QLineEdit(host.default_disk_pool if host and host.default_disk_pool else "")
        self._network_edit = QLineEdit(host.default_network if host and host.default_network else "")
        self._iso_pool_edit = QLineEdit(host.default_iso_pool if host and host.default_iso_pool else "")
        self._os_variant_edit = QLineEdit(host.default_os_variant if host and host.default_os_variant else "")
        for edit, placeholder in (
            (self._disk_pool_edit, "leave blank for no default"),
            (self._network_edit, "leave blank for no default"),
            (self._iso_pool_edit, "leave blank for no default"),
            (self._os_variant_edit, "leave blank for no default"),
        ):
            edit.setPlaceholderText(placeholder)

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("URI:", self._uri_edit)
        defaults_label = QLabel("Defaults for \"Deploy VM…\" on this host")
        defaults_label.setStyleSheet("font-weight: bold;")
        form.addRow(defaults_label)
        form.addRow("Memory:", self._memory_spin)
        form.addRow("vCPUs:", self._vcpus_spin)
        form.addRow("Disk size:", self._disk_spin)
        form.addRow("Disk storage pool:", self._disk_pool_edit)
        form.addRow("Network:", self._network_edit)
        form.addRow("ISO storage pool:", self._iso_pool_edit)
        form.addRow("OS variant:", self._os_variant_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def host(self) -> QemuHost:
        return QemuHost(
            name=self._name_edit.text().strip(),
            uri=self._uri_edit.text().strip(),
            default_memory_mib=self._memory_spin.value() or None,
            default_vcpus=self._vcpus_spin.value() or None,
            default_disk_gib=self._disk_spin.value() or None,
            default_disk_pool=self._disk_pool_edit.text().strip() or None,
            default_network=self._network_edit.text().strip() or None,
            default_iso_pool=self._iso_pool_edit.text().strip() or None,
            default_os_variant=self._os_variant_edit.text().strip() or None,
        )


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

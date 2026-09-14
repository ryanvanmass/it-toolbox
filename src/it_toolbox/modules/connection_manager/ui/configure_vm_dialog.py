""""Configure…" dialog — edits an existing VM's resources: resize
vCPUs/memory, add or remove disks, change/eject CD-ROM media (only
offered when the VM actually has a cdrom device -- confirmed live that
a VM deployed without an ISO chosen at create time has none at all),
and change its network (only offered when it has exactly one network
interface -- multiple-NIC VMs are a real, deliberately deferred case,
see docs/qemu-vm-provisioning-status.md).

Openable for a running VM too (not just a stopped one) -- confirmed
live, per operation, what that actually means:
- vCPU/memory resize is *always* --config-only regardless of running
  state (a real vCPU reduction is flatly rejected live for a normally-
  provisioned VM) -- shown with a note that it applies on next restart.
- Adding a disk hot-attaches reliably when running, but only because
  add_disk(live=True) forces the new disk onto an explicit virtio
  target/bus -- confirmed live that continuing whatever scheme the
  VM's *existing* disks use (this app's own common case: a plain
  "generic" os-variant VM gets an IDE boot disk from virt-install by
  default) produces another IDE target, and IDE disks flatly refuse to
  hotplug at all, failing the *entire* call outright, not just its live
  half. No caveat needed in the UI -- the fix is unconditional inside
  add_disk itself, not something the user needs to know about.
- Removing a disk or changing the network *requests* an immediate
  removal (via an extra `--live` flag) when running, but confirmed live
  this is genuinely unreliable -- `virsh` reports success immediately
  while the old device was still fully present several seconds later,
  since hot-*removal* needs the guest OS to actually release it. Shown
  with an explicit warning rather than pretending it's guaranteed.
- Changing CD-ROM media is reliably immediate when running (confirmed
  live) -- no caveat needed, unlike disk/network removal.

All edits are batched -- nothing actually runs against the host until
OK is pressed, same as the original vCPU/memory/add-disk-only version
of this dialog. A disk marked for removal just disappears from the
in-dialog list immediately (mirroring ManageHostsDialog's own
add/edit/remove-is-local-until-saved convention); the real
detach happens in that same batched save.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.modules.connection_manager import qemu_provisioning
from it_toolbox.modules.connection_manager.models import QemuHost, QemuVm, VmDisk, VmNetworkInterface
from it_toolbox.modules.connection_manager.ui.searchable_combo import make_searchable, resolve_data

DISK_TARGET_ROLE = Qt.ItemDataRole.UserRole
_NONE_ISO_LABEL = "(None — eject)"


class ConfigureVmDialog(QDialog):
    def __init__(
        self, host: QemuHost, vm: QemuVm, current_vcpus: int, current_memory_mib: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._vm = vm
        self._is_running = vm.state == "running"
        self._current_vcpus = current_vcpus
        self._current_memory_mib = current_memory_mib
        self._cdrom_target: str | None = None
        self._network_mac: str | None = None
        self._current_network: str | None = None
        self._pending_disk_removals: set[str] = set()
        self.setWindowTitle(f"Configure {vm.name}")
        self.resize(480, 620)

        self._vcpus_spin = QSpinBox()
        self._vcpus_spin.setRange(1, 64)
        self._vcpus_spin.setValue(current_vcpus)

        self._memory_spin = QSpinBox()
        self._memory_spin.setRange(128, 1_048_576)
        self._memory_spin.setSuffix(" MiB")
        self._memory_spin.setValue(current_memory_mib)

        resource_form = QFormLayout()
        resource_form.addRow("vCPUs:", self._vcpus_spin)
        resource_form.addRow("Memory:", self._memory_spin)
        if self._is_running:
            # vCPU/memory changes are always --config-only regardless of
            # running state (confirmed live: a real vCPU reduction is
            # flatly rejected as a live change for a normally-provisioned
            # VM) -- this is the one place in the dialog where "running"
            # doesn't unlock anything extra, so say so plainly.
            resize_note = QLabel("vCPU/memory changes apply the next time this VM restarts.")
            resize_note.setWordWrap(True)
            resize_note.setStyleSheet("color: gray;")
            resource_form.addRow("", resize_note)

        # -- Disks --------------------------------------------------------
        self._disks_list = QListWidget()
        remove_disk_button = QPushButton("Remove Selected Disk")
        remove_disk_button.clicked.connect(self._on_remove_disk_clicked)

        self._add_disk_checkbox = QCheckBox("Add a new disk")
        self._add_disk_checkbox.toggled.connect(self._on_add_disk_toggled)
        self._disk_size_spin = QSpinBox()
        self._disk_size_spin.setRange(1, 16_384)
        self._disk_size_spin.setSuffix(" GiB")
        self._disk_size_spin.setValue(20)
        self._disk_size_spin.setEnabled(False)
        self._disk_pool_combo = QComboBox()
        self._disk_pool_combo.setEnabled(False)

        disks_layout = QVBoxLayout()
        disks_layout.addWidget(self._disks_list)
        disks_layout.addWidget(remove_disk_button)
        if self._is_running:
            # Adding a disk hot-attaches reliably (confirmed live), but
            # removal is a genuinely different story -- confirmed live
            # that virsh reports success immediately while the disk was
            # still fully attached several seconds later, since it needs
            # the guest OS to actually release it first.
            remove_note = QLabel(
                "Removing a disk while running requests immediate removal, but full "
                "completion depends on the guest OS releasing it -- it may not actually "
                "disappear until this VM restarts."
            )
            remove_note.setWordWrap(True)
            remove_note.setStyleSheet("color: gray;")
            disks_layout.addWidget(remove_note)
        add_disk_form = QFormLayout()
        add_disk_form.addRow("", self._add_disk_checkbox)
        add_disk_form.addRow("New disk size:", self._disk_size_spin)
        add_disk_form.addRow("New disk pool:", self._disk_pool_combo)
        disks_layout.addLayout(add_disk_form)
        self._disks_box = QGroupBox("Disks")
        self._disks_box.setLayout(disks_layout)

        # -- CD-ROM (hidden entirely if the VM has no cdrom device) --------
        self._cdrom_current_label = QLabel("Loading…")
        self._change_media_checkbox = QCheckBox("Change media")
        self._change_media_checkbox.toggled.connect(self._on_change_media_toggled)
        self._cdrom_pool_combo = QComboBox()
        self._cdrom_pool_combo.setEnabled(False)
        self._cdrom_pool_combo.currentIndexChanged.connect(self._on_cdrom_pool_changed)
        self._cdrom_iso_combo = QComboBox()
        self._cdrom_iso_combo.setEnabled(False)
        self._cdrom_iso_combo.addItem(_NONE_ISO_LABEL, None)
        self._cdrom_completer = make_searchable(
            self._cdrom_iso_combo, self, "Type to search, or leave blank to eject"
        )

        cdrom_form = QFormLayout()
        cdrom_form.addRow("Current:", self._cdrom_current_label)
        cdrom_form.addRow("", self._change_media_checkbox)
        cdrom_form.addRow("ISO storage pool:", self._cdrom_pool_combo)
        cdrom_form.addRow("New media:", self._cdrom_iso_combo)
        self._cdrom_box = QGroupBox("CD-ROM")
        self._cdrom_box.setLayout(cdrom_form)
        self._cdrom_box.setVisible(False)

        # -- Network --------------------------------------------------------
        self._network_current_label = QLabel("Loading…")
        self._change_network_checkbox = QCheckBox("Change network")
        self._change_network_checkbox.toggled.connect(self._on_change_network_toggled)
        self._network_combo = QComboBox()
        self._network_combo.setEnabled(False)

        network_form = QFormLayout()
        network_form.addRow("Current:", self._network_current_label)
        network_form.addRow("", self._change_network_checkbox)
        network_form.addRow("New network:", self._network_combo)
        if self._is_running:
            # Attaching the new network hot-attaches reliably (confirmed
            # live), but detaching the old interface has the same
            # guest-cooperation caveat as disk removal above.
            network_note = QLabel(
                "The new network is added immediately, but the old interface may not "
                "fully disappear until this VM restarts."
            )
            network_note.setWordWrap(True)
            network_note.setStyleSheet("color: gray;")
            network_form.addRow("", network_note)
        self._network_box = QGroupBox("Network")
        self._network_box.setLayout(network_form)
        self._network_box.setVisible(False)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: red;")
        self._error_label.setVisible(False)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(resource_form)
        layout.addWidget(self._disks_box)
        layout.addWidget(self._cdrom_box)
        layout.addWidget(self._network_box)
        layout.addWidget(self._error_label)
        layout.addWidget(self._buttons)

        self._load_all()

    def _load_all(self) -> None:
        async_utils.run_in_background(
            lambda: (
                qemu_provisioning.list_disks(self._host, self._vm.name),
                qemu_provisioning.list_network_interfaces(self._host, self._vm.name),
                qemu_provisioning.list_storage_pools(self._host),
                qemu_provisioning.list_networks(self._host),
            ),
            on_result=self._on_loaded,
            on_error=self._on_error,
        )

    def _on_loaded(self, result: tuple[list[VmDisk], list[VmNetworkInterface], list, list]) -> None:
        disks, interfaces, pools, networks = result
        self._populate_disks(disks)
        self._populate_cdrom(disks, pools)
        self._populate_network(interfaces, networks)
        for pool in pools:
            self._disk_pool_combo.addItem(pool.name, pool.name)
        self._disk_pool_combo.setEnabled(self._add_disk_checkbox.isChecked())

    def _populate_disks(self, disks: list[VmDisk]) -> None:
        self._disks_list.clear()
        for disk in disks:
            if disk.device != "disk":
                continue
            item = QListWidgetItem(f"{disk.target} — {disk.source or '(no source)'}")
            item.setData(DISK_TARGET_ROLE, disk.target)
            self._disks_list.addItem(item)

    def _populate_cdrom(self, disks: list[VmDisk], pools: list) -> None:
        cdrom = next((d for d in disks if d.device == "cdrom"), None)
        if cdrom is None:
            return  # no cdrom device at all -- section stays hidden
        self._cdrom_target = cdrom.target
        self._cdrom_current_label.setText(cdrom.source or "(empty)")
        for pool in pools:
            self._cdrom_pool_combo.addItem(pool.name, pool.name)
        self._cdrom_box.setVisible(True)

    def _populate_network(self, interfaces: list[VmNetworkInterface], networks: list) -> None:
        if len(interfaces) != 1:
            return  # no interface, or more than one -- section stays hidden (see module docstring)
        interface = interfaces[0]
        self._network_mac = interface.mac
        self._current_network = interface.network
        self._network_current_label.setText(interface.network)
        for network in networks:
            self._network_combo.addItem(network.name, network.name)
        index = self._network_combo.findData(self._current_network)
        if index != -1:
            self._network_combo.setCurrentIndex(index)
        self._network_box.setVisible(True)

    def _on_remove_disk_clicked(self) -> None:
        item = self._disks_list.currentItem()
        if item is None:
            return
        target = item.data(DISK_TARGET_ROLE)
        reply = QMessageBox.question(
            self,
            "Remove Disk",
            f"Remove disk {target} from {self._vm.name}? The underlying storage volume is not "
            "deleted -- only detached from this VM.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._pending_disk_removals.add(target)
        self._disks_list.takeItem(self._disks_list.row(item))

    def _on_add_disk_toggled(self, checked: bool) -> None:
        self._disk_size_spin.setEnabled(checked)
        self._disk_pool_combo.setEnabled(checked)

    def _on_change_media_toggled(self, checked: bool) -> None:
        self._cdrom_pool_combo.setEnabled(checked)
        self._cdrom_iso_combo.setEnabled(checked)
        if checked and self._cdrom_pool_combo.currentData() is not None:
            self._load_isos_for_cdrom_pool()

    def _on_cdrom_pool_changed(self, _index: int) -> None:
        if self._change_media_checkbox.isChecked():
            self._load_isos_for_cdrom_pool()

    def _load_isos_for_cdrom_pool(self) -> None:
        pool_name = self._cdrom_pool_combo.currentData()
        if pool_name is None:
            return
        async_utils.run_in_background(
            lambda: qemu_provisioning.list_volumes(self._host, pool_name),
            on_result=self._on_cdrom_volumes_loaded,
            on_error=self._on_error,
        )

    def _on_cdrom_volumes_loaded(self, volumes: list) -> None:
        typed = self._cdrom_iso_combo.currentText()
        self._cdrom_iso_combo.clear()
        self._cdrom_iso_combo.addItem(_NONE_ISO_LABEL, None)
        for volume in volumes:
            if volume.name.lower().endswith(".iso"):
                index = self._cdrom_iso_combo.count()
                self._cdrom_iso_combo.addItem(volume.name, volume.path)
                self._cdrom_iso_combo.setItemData(index, volume.path, Qt.ItemDataRole.ToolTipRole)
        self._cdrom_iso_combo.setCurrentText(typed)

    def _on_change_network_toggled(self, checked: bool) -> None:
        self._network_combo.setEnabled(checked)

    def _on_error(self, error: Exception) -> None:
        self._show_error(str(error))

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _on_accept(self) -> None:
        new_vcpus = self._vcpus_spin.value()
        new_memory = self._memory_spin.value()
        vcpus = new_vcpus if new_vcpus != self._current_vcpus else None
        memory_mib = new_memory if new_memory != self._current_memory_mib else None

        add_disk = self._add_disk_checkbox.isChecked()
        disk_pool = self._disk_pool_combo.currentData()
        disk_size = self._disk_size_spin.value()
        if add_disk and disk_pool is None:
            self._show_error("Choose a storage pool for the new disk.")
            return

        disks_to_remove = list(self._pending_disk_removals)

        change_media = self._change_media_checkbox.isChecked()
        # resolve_data(), not currentData() directly -- see its own
        # docstring: a real user who types an exact, valid ISO name by
        # hand (rather than clicking the completer's own popup
        # suggestion) needs their choice actually recognized.
        new_iso_path = resolve_data(self._cdrom_iso_combo) if change_media else None

        change_network = self._change_network_checkbox.isChecked()
        new_network = self._network_combo.currentData() if change_network else None
        if change_network and new_network is None:
            self._show_error("Choose a network.")
            return
        network_actually_changes = change_network and new_network != self._current_network

        if (
            vcpus is None and memory_mib is None and not add_disk and not disks_to_remove
            and not change_media and not network_actually_changes
        ):
            # Nothing actually changed -- close without making any call.
            self.accept()
            return

        def do_work() -> None:
            if vcpus is not None or memory_mib is not None:
                qemu_provisioning.resize_vm(self._host, self._vm.name, vcpus=vcpus, memory_mib=memory_mib)
            for target in disks_to_remove:
                qemu_provisioning.remove_disk(self._host, self._vm.name, target, live=self._is_running)
            if add_disk:
                qemu_provisioning.add_disk(
                    self._host, self._vm.name, pool=disk_pool, size_gib=disk_size, live=self._is_running
                )
            if change_media:
                qemu_provisioning.change_cdrom_media(
                    self._host, self._vm.name, self._cdrom_target, new_iso_path, live=self._is_running
                )
            if network_actually_changes:
                qemu_provisioning.change_network(
                    self._host,
                    self._vm.name,
                    old_mac=self._network_mac,
                    new_network=new_network,
                    live=self._is_running,
                )

        self._error_label.setVisible(False)
        self._buttons.setEnabled(False)
        async_utils.run_in_background(do_work, on_result=lambda _: self.accept(), on_error=self._on_save_error)

    def _on_save_error(self, error: Exception) -> None:
        self._buttons.setEnabled(True)
        self._show_error(str(error))

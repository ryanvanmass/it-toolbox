""""Deploy VM…" dialog — provisions a new VM's resources (disk, RAM,
vCPUs, network) on a registered QEMU/libvirt host and optionally
attaches an existing ISO from that host as install media. Deliberately
does not attempt the OS install itself — the resulting VM is meant to
be finished (or just used, if --import booted something already
usable) through the existing embedded SPICE viewer. See
docs/qemu-vm-provisioning-status.md for the full design/verification
history.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.modules.connection_manager import qemu_provisioning
from it_toolbox.modules.connection_manager.models import QemuHost, StorageVolume, VmCreateSpec

_NONE_ISO_LABEL = "(None — boot the new disk directly)"
_DEFAULT_OS_VARIANT = "generic"
# Real ISO filenames (and, to a lesser extent, --osinfo short IDs) easily
# outrun the combo box's own on-screen width -- widening the *popup*
# specifically (Qt doesn't clip a QComboBox's dropdown to its own field
# width) is what actually makes a large library legible, without forcing
# the whole compact form layout wider just to fit one field's content.
_SEARCHABLE_POPUP_MIN_WIDTH = 420


def _make_searchable(combo: QComboBox, parent: QWidget) -> QCompleter:
    """Wires a QComboBox up for type-to-filter search over a large list
    (real cases: ~940 --osinfo short IDs, or a large ISO library where
    many entries share a long common prefix/suffix) -- editable so
    typing works at all, NoInsert so a search that doesn't exactly match
    anything can't silently create a bogus new entry, MatchContains
    (not the default MatchStartsWith) since a real library's names
    often need matching a substring in the middle, not just a prefix.
    The completer is bound to the combo's own model, which QComboBox
    mutates in place on clear()/addItem() rather than replacing --
    filtering results automatically stay current as items load in.
    """
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.view().setMinimumWidth(_SEARCHABLE_POPUP_MIN_WIDTH)
    completer = QCompleter(combo.model(), parent)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)
    return completer


class CreateVmDialog(QDialog):
    def __init__(self, host: QemuHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self.setWindowTitle(f"Deploy VM on {host.name}")
        self.resize(460, 420)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("my-new-vm")

        self._memory_spin = QSpinBox()
        self._memory_spin.setRange(128, 1_048_576)
        self._memory_spin.setSuffix(" MiB")
        self._memory_spin.setValue(2048)

        self._vcpus_spin = QSpinBox()
        self._vcpus_spin.setRange(1, 64)
        self._vcpus_spin.setValue(2)

        self._disk_spin = QSpinBox()
        self._disk_spin.setRange(1, 16_384)
        self._disk_spin.setSuffix(" GiB")
        self._disk_spin.setValue(20)

        # Separate pool pickers -- the VM's own new disk and its ISO
        # install media (if any) can live on different storage backends
        # (e.g. a fast local pool for the disk, a shared/NFS pool of
        # ISOs everyone deploys from). Each loads independently; the ISO
        # pool's selection drives which volumes _iso_combo offers.
        self._disk_pool_combo = QComboBox()
        self._disk_pool_combo.setEnabled(False)

        self._iso_pool_combo = QComboBox()
        self._iso_pool_combo.setEnabled(False)
        self._iso_pool_combo.currentIndexChanged.connect(self._on_iso_pool_changed)

        self._network_combo = QComboBox()
        self._network_combo.setEnabled(False)

        # Searchable (type-to-filter) -- a real ISO library can easily
        # have dozens of similarly-prefixed entries ("kubernetes-*.iso"
        # etc.), where a plain non-searchable dropdown is genuinely
        # unusable to scroll through. Repopulated per ISO-pool change
        # (see _on_volumes_loaded); the completer stays wired to the
        # same combo model throughout, so it reflects whatever's
        # currently loaded without needing to be rebuilt each time.
        self._iso_combo = QComboBox()
        self._iso_combo.setEnabled(False)
        self._iso_combo.addItem(_NONE_ISO_LABEL, None)
        self._iso_combo.setCurrentText(_NONE_ISO_LABEL)
        self._iso_completer = _make_searchable(self._iso_combo, self)

        # Searchable list of every real --os-variant virt-install
        # accepts -- confirmed live there are ~940 of these, loaded
        # async the same way pools/networks are; "generic" (itself a
        # real, valid entry) is the default before that load finishes.
        self._os_variant_combo = QComboBox()
        self._os_variant_combo.addItem(_DEFAULT_OS_VARIANT)
        self._os_variant_combo.setCurrentText(_DEFAULT_OS_VARIANT)
        self._os_variant_completer = _make_searchable(self._os_variant_combo, self)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: red;")
        self._error_label.setVisible(False)

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("Memory:", self._memory_spin)
        form.addRow("vCPUs:", self._vcpus_spin)
        form.addRow("Disk size:", self._disk_spin)
        form.addRow("Disk storage pool:", self._disk_pool_combo)
        form.addRow("Network:", self._network_combo)
        form.addRow("ISO storage pool:", self._iso_pool_combo)
        form.addRow("Install media (ISO):", self._iso_combo)
        form.addRow("OS variant:", self._os_variant_combo)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._error_label)
        layout.addWidget(self._buttons)

        self._load_pools_and_networks()
        self._load_os_variants()

    def _load_pools_and_networks(self) -> None:
        async_utils.run_in_background(
            lambda: (
                qemu_provisioning.list_storage_pools(self._host),
                qemu_provisioning.list_networks(self._host),
            ),
            on_result=self._on_pools_and_networks_loaded,
            on_error=self._on_load_error,
        )

    def _on_pools_and_networks_loaded(self, result: tuple[list, list]) -> None:
        pools, networks = result
        for pool in pools:
            self._disk_pool_combo.addItem(pool.name, pool.name)
            self._iso_pool_combo.addItem(pool.name, pool.name)
        for network in networks:
            self._network_combo.addItem(network.name, network.name)

        if not pools:
            self._show_error(f"No storage pools found on {self._host.name} — create one first.")
            return
        if not networks:
            self._show_error(f"No virtual networks found on {self._host.name} — create one first.")
            return

        self._disk_pool_combo.setEnabled(True)
        self._iso_pool_combo.setEnabled(True)
        self._network_combo.setEnabled(True)
        self._iso_combo.setEnabled(True)
        self._ok_button.setEnabled(True)
        self._load_isos_for_current_pool()

    def _on_iso_pool_changed(self, _index: int) -> None:
        self._load_isos_for_current_pool()

    def _load_isos_for_current_pool(self) -> None:
        pool_name = self._iso_pool_combo.currentData()
        if pool_name is None:
            return
        async_utils.run_in_background(
            lambda: qemu_provisioning.list_volumes(self._host, pool_name),
            on_result=self._on_volumes_loaded,
            on_error=self._on_load_error,
        )

    def _on_volumes_loaded(self, volumes: list[StorageVolume]) -> None:
        self._iso_combo.clear()
        self._iso_combo.addItem(_NONE_ISO_LABEL, None)
        for volume in volumes:
            if volume.name.lower().endswith(".iso"):
                index = self._iso_combo.count()
                self._iso_combo.addItem(volume.name, volume.path)
                # The combo box's own field still truncates a long real
                # filename at rest -- a tooltip is the cheap way to
                # recover the full name without widening the whole
                # form's layout just for this one field.
                self._iso_combo.setItemData(index, volume.path, Qt.ItemDataRole.ToolTipRole)
        self._iso_combo.setCurrentIndex(0)

    def _load_os_variants(self) -> None:
        async_utils.run_in_background(
            qemu_provisioning.list_os_variants,
            on_result=self._on_os_variants_loaded,
            on_error=self._on_load_error,
        )

    def _on_os_variants_loaded(self, variants: list[str]) -> None:
        current = self._os_variant_combo.currentText()
        self._os_variant_combo.clear()
        self._os_variant_combo.addItems(variants)
        self._os_variant_combo.setCurrentText(current)

    def _on_load_error(self, error: Exception) -> None:
        self._show_error(str(error))

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._show_error("Name is required.")
            return

        spec = VmCreateSpec(
            name=name,
            memory_mib=self._memory_spin.value(),
            vcpus=self._vcpus_spin.value(),
            disk_gib=self._disk_spin.value(),
            pool=self._disk_pool_combo.currentData(),
            network=self._network_combo.currentData(),
            os_variant=self._os_variant_combo.currentText().strip() or _DEFAULT_OS_VARIANT,
            iso_path=self._iso_combo.currentData(),
        )

        self._error_label.setVisible(False)
        self._buttons.setEnabled(False)
        async_utils.run_in_background(
            lambda: qemu_provisioning.create_vm(self._host, spec),
            on_result=lambda _: self.accept(),
            on_error=self._on_create_error,
        )

    def _on_create_error(self, error: Exception) -> None:
        self._buttons.setEnabled(True)
        self._show_error(str(error))

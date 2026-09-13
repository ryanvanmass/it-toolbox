""""Configure…" dialog — resizes an existing, *stopped* VM's vCPUs/
memory and/or adds a new disk. Only ever opened by the caller
(main_view.py) for a VM whose state isn't "running" — resize_vm's own
--config-only calls are the backend's defense in depth for that same
rule, this dialog is the first line of it.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.modules.connection_manager import qemu_provisioning
from it_toolbox.modules.connection_manager.models import QemuHost, QemuVm


class ConfigureVmDialog(QDialog):
    def __init__(
        self, host: QemuHost, vm: QemuVm, current_vcpus: int, current_memory_mib: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._vm = vm
        self._current_vcpus = current_vcpus
        self._current_memory_mib = current_memory_mib
        self.setWindowTitle(f"Configure {vm.name}")
        self.resize(380, 280)

        self._vcpus_spin = QSpinBox()
        self._vcpus_spin.setRange(1, 64)
        self._vcpus_spin.setValue(current_vcpus)

        self._memory_spin = QSpinBox()
        self._memory_spin.setRange(128, 1_048_576)
        self._memory_spin.setSuffix(" MiB")
        self._memory_spin.setValue(current_memory_mib)

        self._add_disk_checkbox = QCheckBox("Add a new disk")
        self._add_disk_checkbox.toggled.connect(self._on_add_disk_toggled)

        self._disk_size_spin = QSpinBox()
        self._disk_size_spin.setRange(1, 16_384)
        self._disk_size_spin.setSuffix(" GiB")
        self._disk_size_spin.setValue(20)
        self._disk_size_spin.setEnabled(False)

        self._disk_pool_combo = QComboBox()
        self._disk_pool_combo.setEnabled(False)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: red;")
        self._error_label.setVisible(False)

        form = QFormLayout()
        form.addRow("vCPUs:", self._vcpus_spin)
        form.addRow("Memory:", self._memory_spin)
        form.addRow("", self._add_disk_checkbox)
        form.addRow("New disk size:", self._disk_size_spin)
        form.addRow("New disk pool:", self._disk_pool_combo)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._error_label)
        layout.addWidget(self._buttons)

    def _on_add_disk_toggled(self, checked: bool) -> None:
        self._disk_size_spin.setEnabled(checked)
        self._disk_pool_combo.setEnabled(checked)
        if checked and self._disk_pool_combo.count() == 0:
            async_utils.run_in_background(
                lambda: qemu_provisioning.list_storage_pools(self._host),
                on_result=self._on_pools_loaded,
                on_error=self._on_error,
            )

    def _on_pools_loaded(self, pools: list) -> None:
        for pool in pools:
            self._disk_pool_combo.addItem(pool.name, pool.name)
        if not pools:
            self._show_error(f"No storage pools found on {self._host.name}.")
            self._add_disk_checkbox.setChecked(False)

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

        if vcpus is None and memory_mib is None and not add_disk:
            # Nothing actually changed -- close without making any call.
            self.accept()
            return

        def do_work() -> None:
            if vcpus is not None or memory_mib is not None:
                qemu_provisioning.resize_vm(self._host, self._vm.name, vcpus=vcpus, memory_mib=memory_mib)
            if add_disk:
                qemu_provisioning.add_disk(self._host, self._vm.name, pool=disk_pool, size_gib=disk_size)

        self._error_label.setVisible(False)
        self._buttons.setEnabled(False)
        async_utils.run_in_background(do_work, on_result=lambda _: self.accept(), on_error=self._on_save_error)

    def _on_save_error(self, error: Exception) -> None:
        self._buttons.setEnabled(True)
        self._show_error(str(error))

from it_toolbox.modules.connection_manager.models import QemuHost, QemuVm, StoragePool
from it_toolbox.modules.connection_manager.ui.configure_vm_dialog import ConfigureVmDialog

HOST = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
VM = QemuVm(id="-", name="myvm", state="shut off")


def _make_dialog(qtbot, current_vcpus=2, current_memory_mib=2048):
    dialog = ConfigureVmDialog(HOST, VM, current_vcpus, current_memory_mib)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_fields_prefilled_with_current_values(qtbot):
    dialog = _make_dialog(qtbot, current_vcpus=4, current_memory_mib=8192)

    assert dialog._vcpus_spin.value() == 4
    assert dialog._memory_spin.value() == 8192


def test_add_disk_fields_disabled_until_checkbox_checked(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_storage_pools",
        lambda host: [StoragePool(name="default", state="active")],
    )
    dialog = _make_dialog(qtbot)

    assert dialog._disk_size_spin.isEnabled() is False
    assert dialog._disk_pool_combo.isEnabled() is False

    dialog._add_disk_checkbox.setChecked(True)
    qtbot.waitUntil(lambda: dialog._disk_pool_combo.count() == 1, timeout=1000)

    assert dialog._disk_size_spin.isEnabled() is True
    assert dialog._disk_pool_combo.currentData() == "default"


def test_accept_with_no_changes_closes_without_calling_anything(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, current_vcpus=2, current_memory_mib=2048)
    calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.resize_vm",
        lambda *a, **k: calls.append("resize"),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.add_disk",
        lambda *a, **k: calls.append("add_disk"),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))

    dialog._on_accept()

    assert calls == []
    assert accepted == [True]


def test_accept_resizes_only_the_changed_field(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, current_vcpus=2, current_memory_mib=2048)
    dialog._vcpus_spin.setValue(4)  # memory left unchanged

    resize_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.resize_vm",
        lambda host, vm_name, *, vcpus=None, memory_mib=None: resize_calls.append((vcpus, memory_mib)),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))

    dialog._on_accept()

    qtbot.waitUntil(lambda: resize_calls == [(4, None)], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_accept_with_add_disk_calls_add_disk_with_chosen_pool_and_size(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_storage_pools",
        lambda host: [StoragePool(name="default", state="active")],
    )
    dialog = _make_dialog(qtbot)
    dialog._add_disk_checkbox.setChecked(True)
    qtbot.waitUntil(lambda: dialog._disk_pool_combo.count() == 1, timeout=1000)
    dialog._disk_size_spin.setValue(50)

    add_disk_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.add_disk",
        lambda host, vm_name, *, pool, size_gib: add_disk_calls.append((vm_name, pool, size_gib)),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))

    dialog._on_accept()

    qtbot.waitUntil(lambda: add_disk_calls == [("myvm", "default", 50)], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_accept_requires_a_pool_when_add_disk_checked_but_no_pools_loaded(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_storage_pools",
        lambda host: [],
    )
    dialog = _make_dialog(qtbot)
    dialog._add_disk_checkbox.setChecked(True)
    qtbot.waitUntil(lambda: dialog._error_label.isVisible(), timeout=1000)
    # list_storage_pools returned empty -- the checkbox auto-unchecks itself
    assert dialog._add_disk_checkbox.isChecked() is False


def test_save_error_reenables_buttons_and_shows_message(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, current_vcpus=2, current_memory_mib=2048)
    dialog._vcpus_spin.setValue(4)

    def fail(*a, **k):
        raise RuntimeError("virsh: command not found")

    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.resize_vm", fail
    )

    dialog._on_accept()

    qtbot.waitUntil(lambda: dialog._error_label.isVisible(), timeout=1000)
    assert "virsh" in dialog._error_label.text()
    assert dialog._buttons.isEnabled() is True

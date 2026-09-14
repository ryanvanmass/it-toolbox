from it_toolbox.modules.connection_manager.models import QemuHost
from it_toolbox.modules.connection_manager.ui.manage_hosts_dialog import _UNSET_LABEL, _HostEditDialog


def test_add_dialog_starts_with_unset_defaults(qtbot):
    dialog = _HostEditDialog()
    qtbot.addWidget(dialog)

    assert dialog._memory_spin.value() == 0
    assert dialog._memory_spin.text() == _UNSET_LABEL
    assert dialog._disk_pool_edit.text() == ""

    host = dialog.host()
    assert host.default_memory_mib is None
    assert host.default_vcpus is None
    assert host.default_disk_gib is None
    assert host.default_disk_pool is None
    assert host.default_network is None
    assert host.default_iso_pool is None
    assert host.default_os_variant is None


def test_edit_dialog_prefills_existing_defaults(qtbot):
    host = QemuHost(
        name="lab", uri="qemu+ssh://user@lab-host/system",
        default_memory_mib=4096, default_vcpus=4, default_disk_gib=80,
        default_disk_pool="fast-local", default_network="br0", default_iso_pool="iso-share",
        default_os_variant="fedora40",
    )
    dialog = _HostEditDialog(host)
    qtbot.addWidget(dialog)

    assert dialog._memory_spin.value() == 4096
    assert dialog._vcpus_spin.value() == 4
    assert dialog._disk_spin.value() == 80
    assert dialog._disk_pool_edit.text() == "fast-local"
    assert dialog._network_edit.text() == "br0"
    assert dialog._iso_pool_edit.text() == "iso-share"
    assert dialog._os_variant_edit.text() == "fedora40"

    assert dialog.host() == host


def test_edit_dialog_can_clear_a_previously_set_default(qtbot):
    host = QemuHost(
        name="lab", uri="qemu+ssh://user@lab-host/system",
        default_memory_mib=4096, default_disk_pool="fast-local",
    )
    dialog = _HostEditDialog(host)
    qtbot.addWidget(dialog)

    dialog._memory_spin.setValue(0)  # back to "(dialog default)"
    dialog._disk_pool_edit.setText("")

    updated = dialog.host()
    assert updated.default_memory_mib is None
    assert updated.default_disk_pool is None

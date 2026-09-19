from PySide6.QtWidgets import QMessageBox

from it_toolbox.modules.connection_manager.models import (
    QemuHost,
    QemuVm,
    StoragePool,
    StorageVolume,
    VirtualNetwork,
    VmDisk,
    VmNetworkInterface,
)
from it_toolbox.modules.connection_manager.ui.configure_vm_dialog import ConfigureVmDialog

HOST = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
VM = QemuVm(id="-", name="myvm", state="shut off")
VM_RUNNING = QemuVm(id="1", name="myvm", state="running")

_ONE_DISK = (VmDisk(target="hda", device="disk", source="/pool/myvm.qcow2"),)
_ONE_DISK_ONE_CDROM = _ONE_DISK + (VmDisk(target="hdb", device="cdrom", source=None),)
_ONE_INTERFACE = (VmNetworkInterface(mac="52:54:00:aa:bb:cc", network="default", model="e1000"),)
_ONE_POOL = (StoragePool(name="default", state="active"),)
_ONE_NETWORK = (VirtualNetwork(name="default", state="active"),)


def _make_dialog(
    qtbot, monkeypatch, current_vcpus=2, current_memory_mib=2048, current_display_device="spice",
    disks=_ONE_DISK, interfaces=_ONE_INTERFACE, pools=_ONE_POOL, networks=_ONE_NETWORK,
    volumes=(), vm=VM,
):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_disks",
        lambda host, vm_name: list(disks),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_network_interfaces",
        lambda host, vm_name: list(interfaces),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_storage_pools",
        lambda host: list(pools),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_networks",
        lambda host: list(networks),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.list_volumes",
        lambda host, pool_name: list(volumes),
    )
    dialog = ConfigureVmDialog(HOST, vm, current_vcpus, current_memory_mib, current_display_device)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._disk_pool_combo.count() == len(pools), timeout=1000)
    return dialog


def test_fields_prefilled_with_current_values(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, current_vcpus=4, current_memory_mib=8192)

    assert dialog._vcpus_spin.value() == 4
    assert dialog._memory_widget.value_mib() == 8192


def test_disks_list_shows_only_data_disks_not_cdrom(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, disks=_ONE_DISK_ONE_CDROM)
    qtbot.waitUntil(lambda: dialog._disks_list.count() == 1, timeout=1000)

    assert dialog._disks_list.item(0).text() == "hda — /pool/myvm.qcow2"


def test_add_disk_fields_enabled_by_checkbox_pool_already_loaded(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    assert dialog._disk_size_spin.isEnabled() is False
    assert dialog._disk_pool_combo.isEnabled() is False
    assert dialog._disk_pool_combo.currentData() == "default"

    dialog._add_disk_checkbox.setChecked(True)

    assert dialog._disk_size_spin.isEnabled() is True
    assert dialog._disk_pool_combo.isEnabled() is True


def test_cdrom_section_hidden_when_vm_has_no_cdrom_device(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, disks=_ONE_DISK)
    assert dialog._cdrom_box.isVisible() is False


def test_cdrom_section_visible_and_shows_current_media(qtbot, monkeypatch):
    disks = (
        VmDisk(target="hda", device="disk", source="/pool/myvm.qcow2"),
        VmDisk(target="hdb", device="cdrom", source="/pool/ubuntu.iso"),
    )
    dialog = _make_dialog(qtbot, monkeypatch, disks=disks)
    qtbot.waitUntil(lambda: dialog._cdrom_box.isVisible(), timeout=1000)

    assert dialog._cdrom_current_label.text() == "/pool/ubuntu.iso"


def test_cdrom_section_shows_empty_when_no_media_inserted(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, disks=_ONE_DISK_ONE_CDROM)
    qtbot.waitUntil(lambda: dialog._cdrom_box.isVisible(), timeout=1000)

    assert dialog._cdrom_current_label.text() == "(empty)"


def test_network_section_hidden_when_no_interfaces(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, interfaces=())
    assert dialog._network_box.isVisible() is False


def test_network_section_hidden_when_multiple_interfaces(qtbot, monkeypatch):
    interfaces = (
        VmNetworkInterface(mac="aa:aa:aa:aa:aa:aa", network="default", model="e1000"),
        VmNetworkInterface(mac="bb:bb:bb:bb:bb:bb", network="isolated", model="virtio"),
    )
    dialog = _make_dialog(qtbot, monkeypatch, interfaces=interfaces)
    assert dialog._network_box.isVisible() is False


def test_network_section_shows_and_preselects_current_network(qtbot, monkeypatch):
    networks = (VirtualNetwork(name="default", state="active"), VirtualNetwork(name="isolated", state="active"))
    dialog = _make_dialog(qtbot, monkeypatch, interfaces=_ONE_INTERFACE, networks=networks)
    qtbot.waitUntil(lambda: dialog._network_box.isVisible(), timeout=1000)

    assert dialog._network_current_label.text() == "default"
    assert dialog._network_combo.currentData() == "default"


def test_accept_with_no_changes_closes_without_calling_anything(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    calls = []
    for fn in ("resize_vm", "add_disk", "remove_disk", "change_cdrom_media", "change_network", "set_display_device"):
        monkeypatch.setattr(
            f"it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.{fn}",
            lambda *a, **k: calls.append(fn),
        )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))

    dialog._on_accept()

    assert calls == []
    assert accepted == [True]


def test_accept_resizes_only_the_changed_field(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, current_vcpus=2, current_memory_mib=2048)
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
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._add_disk_checkbox.setChecked(True)
    dialog._disk_size_spin.setValue(50)

    add_disk_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.add_disk",
        lambda host, vm_name, *, pool, size_gib, live: add_disk_calls.append((vm_name, pool, size_gib, live)),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))

    dialog._on_accept()

    qtbot.waitUntil(lambda: add_disk_calls == [("myvm", "default", 50, False)], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_accept_requires_a_pool_when_add_disk_checked_but_no_pools_loaded(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, pools=())
    dialog._add_disk_checkbox.setChecked(True)

    dialog._on_accept()

    assert dialog._error_label.isVisible() is True
    assert "storage pool" in dialog._error_label.text()


def test_remove_disk_requires_confirmation_and_defers_to_accept(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    dialog._disks_list.setCurrentRow(0)
    dialog._on_remove_disk_clicked()

    assert dialog._disks_list.count() == 0  # removed from the visible list immediately
    assert dialog._pending_disk_removals == {"hda"}

    remove_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.remove_disk",
        lambda host, vm_name, target, *, live: remove_calls.append((target, live)),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    qtbot.waitUntil(lambda: remove_calls == [("hda", False)], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_remove_disk_declined_confirmation_does_nothing(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))

    dialog._disks_list.setCurrentRow(0)
    dialog._on_remove_disk_clicked()

    assert dialog._disks_list.count() == 1
    assert dialog._pending_disk_removals == set()


def test_accept_with_change_media_inserts_chosen_iso(qtbot, monkeypatch):
    volumes = (StorageVolume(name="ubuntu.iso", path="/pool/ubuntu.iso"),)
    dialog = _make_dialog(qtbot, monkeypatch, disks=_ONE_DISK_ONE_CDROM, volumes=volumes)
    qtbot.waitUntil(lambda: dialog._cdrom_box.isVisible(), timeout=1000)

    dialog._change_media_checkbox.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cdrom_iso_combo.count() == 2, timeout=1000)
    dialog._cdrom_iso_combo.setCurrentText("ubuntu.iso")

    change_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.change_cdrom_media",
        lambda host, vm_name, target, iso_path, *, live: change_calls.append((vm_name, target, iso_path, live)),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    qtbot.waitUntil(lambda: change_calls == [("myvm", "hdb", "/pool/ubuntu.iso", False)], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_accept_with_change_media_left_blank_ejects(qtbot, monkeypatch):
    disks = (
        VmDisk(target="hda", device="disk", source="/pool/myvm.qcow2"),
        VmDisk(target="hdb", device="cdrom", source="/pool/ubuntu.iso"),
    )
    dialog = _make_dialog(qtbot, monkeypatch, disks=disks)
    qtbot.waitUntil(lambda: dialog._cdrom_box.isVisible(), timeout=1000)

    dialog._change_media_checkbox.setChecked(True)  # left blank -- means eject

    change_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.change_cdrom_media",
        lambda host, vm_name, target, iso_path, *, live: change_calls.append((vm_name, target, iso_path, live)),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    qtbot.waitUntil(lambda: change_calls == [("myvm", "hdb", None, False)], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_accept_with_change_network_to_a_different_network(qtbot, monkeypatch):
    networks = (VirtualNetwork(name="default", state="active"), VirtualNetwork(name="isolated", state="active"))
    dialog = _make_dialog(qtbot, monkeypatch, networks=networks)
    qtbot.waitUntil(lambda: dialog._network_box.isVisible(), timeout=1000)

    dialog._change_network_checkbox.setChecked(True)
    index = dialog._network_combo.findData("isolated")
    dialog._network_combo.setCurrentIndex(index)

    change_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.change_network",
        lambda host, vm_name, *, old_mac, new_network, live: change_calls.append(
            (vm_name, old_mac, new_network, live)
        ),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    qtbot.waitUntil(lambda: change_calls == [("myvm", "52:54:00:aa:bb:cc", "isolated", False)], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_accept_with_change_network_left_on_same_network_is_a_no_op(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: dialog._network_box.isVisible(), timeout=1000)

    dialog._change_network_checkbox.setChecked(True)  # combo already preselected to "default"

    change_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.change_network",
        lambda *a, **k: change_calls.append(True),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    assert change_calls == []
    assert accepted == [True]


def test_display_section_shows_current_device(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, current_display_device="vnc")

    assert dialog._display_combo.currentData() == "vnc"


def test_display_section_defaults_to_spice_when_no_device_at_all(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, current_display_device=None)

    assert dialog._display_combo.currentData() == "spice"


def test_accept_with_display_device_switched_to_spice(qtbot, monkeypatch):
    # The main recovery scenario this section exists for: a VM that ended
    # up with VNC graphics (so it can never get a SPICE port -- see
    # qemu_client.diagnose_missing_spice_port) gets switched back.
    dialog = _make_dialog(qtbot, monkeypatch, current_display_device="vnc")

    index = dialog._display_combo.findData("spice")
    dialog._display_combo.setCurrentIndex(index)

    set_display_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.set_display_device",
        lambda host, vm_name, graphics_type: set_display_calls.append((vm_name, graphics_type)),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    qtbot.waitUntil(lambda: set_display_calls == [("myvm", "spice")], timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)


def test_accept_with_display_device_left_unchanged_is_a_no_op(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, current_display_device="spice")
    # Combo already preselected to "spice" -- nothing touched.

    set_display_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.set_display_device",
        lambda *a, **k: set_display_calls.append(True),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    assert set_display_calls == []
    assert accepted == [True]


def test_accept_with_no_device_left_on_default_spice_selection_is_a_no_op(qtbot, monkeypatch):
    # Regression case: a VM with no graphics device at all defaults the
    # combo to "spice" for display purposes, but leaving that default
    # untouched must not look like a deliberate change -- only an actual
    # interaction with the combo should trigger set_display_device.
    dialog = _make_dialog(qtbot, monkeypatch, current_display_device=None)

    set_display_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.set_display_device",
        lambda *a, **k: set_display_calls.append(True),
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    assert set_display_calls == []
    assert accepted == [True]


def test_save_error_reenables_buttons_and_shows_message(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, current_vcpus=2, current_memory_mib=2048)
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


# -- Running-VM behavior (Configure… is no longer stopped-VM-only) --------


def test_running_vm_shows_resize_applies_after_restart_note(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, vm=VM_RUNNING)

    # The note is only added to the layout when running -- just confirm the
    # dialog builds without error and the resize fields are still usable
    # (this is the one operation that's *never* live regardless of state).
    assert dialog._vcpus_spin.isEnabled()
    assert dialog._memory_widget.isEnabled()


def test_running_vm_remove_disk_passes_live_true(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, vm=VM_RUNNING)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dialog._disks_list.setCurrentRow(0)
    dialog._on_remove_disk_clicked()

    remove_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.remove_disk",
        lambda host, vm_name, target, *, live: remove_calls.append((target, live)),
    )
    dialog._on_accept()

    qtbot.waitUntil(lambda: remove_calls == [("hda", True)], timeout=1000)


def test_running_vm_change_media_passes_live_true(qtbot, monkeypatch):
    volumes = (StorageVolume(name="ubuntu.iso", path="/pool/ubuntu.iso"),)
    dialog = _make_dialog(qtbot, monkeypatch, vm=VM_RUNNING, disks=_ONE_DISK_ONE_CDROM, volumes=volumes)
    qtbot.waitUntil(lambda: dialog._cdrom_box.isVisible(), timeout=1000)

    dialog._change_media_checkbox.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cdrom_iso_combo.count() == 2, timeout=1000)
    dialog._cdrom_iso_combo.setCurrentText("ubuntu.iso")

    change_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.change_cdrom_media",
        lambda host, vm_name, target, iso_path, *, live: change_calls.append((target, iso_path, live)),
    )
    dialog._on_accept()

    qtbot.waitUntil(lambda: change_calls == [("hdb", "/pool/ubuntu.iso", True)], timeout=1000)


def test_running_vm_change_network_passes_live_true(qtbot, monkeypatch):
    networks = (VirtualNetwork(name="default", state="active"), VirtualNetwork(name="isolated", state="active"))
    dialog = _make_dialog(qtbot, monkeypatch, vm=VM_RUNNING, networks=networks)
    qtbot.waitUntil(lambda: dialog._network_box.isVisible(), timeout=1000)

    dialog._change_network_checkbox.setChecked(True)
    index = dialog._network_combo.findData("isolated")
    dialog._network_combo.setCurrentIndex(index)

    change_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.change_network",
        lambda host, vm_name, *, old_mac, new_network, live: change_calls.append((old_mac, new_network, live)),
    )
    dialog._on_accept()

    qtbot.waitUntil(lambda: change_calls == [("52:54:00:aa:bb:cc", "isolated", True)], timeout=1000)


def test_running_vm_add_disk_passes_live_true(qtbot, monkeypatch):
    # add_disk(live=True) forces an explicit virtio target/bus -- see its
    # own docstring for why this is required (not optional) for reliable
    # hot-attach: continuing an IDE boot disk's own scheme fails outright.
    dialog = _make_dialog(qtbot, monkeypatch, vm=VM_RUNNING)
    dialog._add_disk_checkbox.setChecked(True)
    dialog._disk_size_spin.setValue(10)

    add_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.add_disk",
        lambda host, vm_name, *, pool, size_gib, live: add_calls.append((pool, size_gib, live)),
    )
    dialog._on_accept()

    qtbot.waitUntil(lambda: add_calls == [("default", 10, True)], timeout=1000)


def test_stopped_vm_add_disk_passes_live_false(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)  # default vm=VM, state="shut off"
    dialog._add_disk_checkbox.setChecked(True)
    dialog._disk_size_spin.setValue(10)

    add_calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.configure_vm_dialog.qemu_provisioning.add_disk",
        lambda host, vm_name, *, pool, size_gib, live: add_calls.append((pool, size_gib, live)),
    )
    dialog._on_accept()

    qtbot.waitUntil(lambda: add_calls == [("default", 10, False)], timeout=1000)

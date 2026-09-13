from it_toolbox.modules.connection_manager.models import QemuHost, StoragePool, StorageVolume, VirtualNetwork
from it_toolbox.modules.connection_manager.ui.create_vm_dialog import CreateVmDialog

HOST = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")


def _make_dialog(qtbot, monkeypatch, pools=(StoragePool(name="default", state="active"),),
                  networks=(VirtualNetwork(name="default", state="active"),), volumes=()):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.create_vm_dialog.qemu_provisioning.list_storage_pools",
        lambda host: list(pools),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.create_vm_dialog.qemu_provisioning.list_networks",
        lambda host: list(networks),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.create_vm_dialog.qemu_provisioning.list_volumes",
        lambda host, pool_name: list(volumes),
    )
    dialog = CreateVmDialog(HOST)
    qtbot.addWidget(dialog)
    dialog.show()  # isVisible() is otherwise always False for an unshown top-level widget
    qtbot.waitUntil(lambda: dialog._pool_combo.count() == len(pools), timeout=1000)
    return dialog


def test_pools_and_networks_populate_and_enable_ok(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    assert dialog._pool_combo.currentData() == "default"
    assert dialog._network_combo.currentData() == "default"
    assert dialog._ok_button.isEnabled() is True


def test_ok_disabled_and_error_shown_when_no_pools(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, pools=())
    qtbot.waitUntil(lambda: dialog._error_label.isVisible(), timeout=1000)

    assert dialog._ok_button.isEnabled() is False
    assert "No storage pools" in dialog._error_label.text()


def test_iso_combo_only_lists_iso_suffixed_volumes(qtbot, monkeypatch):
    volumes = (
        StorageVolume(name="disk1.qcow2", path="/var/lib/libvirt/images/disk1.qcow2"),
        StorageVolume(name="ubuntu.iso", path="/var/lib/libvirt/images/ubuntu.iso"),
    )
    dialog = _make_dialog(qtbot, monkeypatch, volumes=volumes)
    qtbot.waitUntil(lambda: dialog._iso_combo.count() == 2, timeout=1000)

    labels = [dialog._iso_combo.itemText(i) for i in range(dialog._iso_combo.count())]
    assert labels == ["(None — boot the new disk directly)", "ubuntu.iso"]
    assert dialog._iso_combo.itemData(1) == "/var/lib/libvirt/images/ubuntu.iso"


def test_accept_requires_a_name(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    dialog._on_accept()

    assert dialog._error_label.isVisible() is True
    assert "Name is required" in dialog._error_label.text()


def test_accept_calls_create_vm_with_expected_spec_and_closes_on_success(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("my-new-vm")
    dialog._memory_spin.setValue(4096)
    dialog._vcpus_spin.setValue(4)
    dialog._disk_spin.setValue(40)

    specs = []
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.create_vm_dialog.qemu_provisioning.create_vm",
        lambda host, spec: specs.append((host, spec)),
    )

    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._on_accept()

    qtbot.waitUntil(lambda: len(specs) == 1, timeout=1000)
    qtbot.waitUntil(lambda: accepted == [True], timeout=1000)

    host, spec = specs[0]
    assert host == HOST
    assert spec.name == "my-new-vm"
    assert spec.memory_mib == 4096
    assert spec.vcpus == 4
    assert spec.disk_gib == 40
    assert spec.pool == "default"
    assert spec.network == "default"
    assert spec.iso_path is None


def test_accept_surfaces_create_vm_error_and_reenables_buttons(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("my-new-vm")

    def fail(host, spec):
        raise RuntimeError("An install method must be specified")

    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.create_vm_dialog.qemu_provisioning.create_vm", fail
    )

    dialog._on_accept()

    qtbot.waitUntil(lambda: dialog._error_label.isVisible(), timeout=1000)
    assert "install method" in dialog._error_label.text()
    assert dialog._buttons.isEnabled() is True

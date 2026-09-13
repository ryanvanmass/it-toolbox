from PySide6.QtCore import Qt

from it_toolbox.modules.connection_manager.models import QemuHost, StoragePool, StorageVolume, VirtualNetwork
from it_toolbox.modules.connection_manager.ui.create_vm_dialog import CreateVmDialog

HOST = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
_DEFAULT_POOLS = (StoragePool(name="default", state="active"),)
_DEFAULT_NETWORKS = (VirtualNetwork(name="default", state="active"),)
_DEFAULT_OS_VARIANTS = ("generic", "almalinux10", "almalinux9", "win11", "ubuntu22.04")


def _make_dialog(
    qtbot, monkeypatch, pools=_DEFAULT_POOLS, networks=_DEFAULT_NETWORKS, volumes=(),
    os_variants=_DEFAULT_OS_VARIANTS, volumes_by_pool=None,
):
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
        lambda host, pool_name: list((volumes_by_pool or {}).get(pool_name, volumes)),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.create_vm_dialog.qemu_provisioning.list_os_variants",
        lambda: list(os_variants),
    )
    dialog = CreateVmDialog(HOST)
    qtbot.addWidget(dialog)
    dialog.show()  # isVisible() is otherwise always False for an unshown top-level widget
    qtbot.waitUntil(lambda: dialog._disk_pool_combo.count() == len(pools), timeout=1000)
    qtbot.waitUntil(lambda: dialog._os_variant_combo.count() == len(os_variants), timeout=1000)
    return dialog


def test_pools_and_networks_populate_and_enable_ok(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    assert dialog._disk_pool_combo.currentData() == "default"
    assert dialog._iso_pool_combo.currentData() == "default"
    assert dialog._network_combo.currentData() == "default"
    assert dialog._ok_button.isEnabled() is True


def test_disk_and_iso_pool_are_independent_combos(qtbot, monkeypatch):
    pools = (StoragePool(name="fast-local", state="active"), StoragePool(name="iso-share", state="active"))
    dialog = _make_dialog(qtbot, monkeypatch, pools=pools)

    dialog._disk_pool_combo.setCurrentIndex(0)
    dialog._iso_pool_combo.setCurrentIndex(1)

    assert dialog._disk_pool_combo.currentData() == "fast-local"
    assert dialog._iso_pool_combo.currentData() == "iso-share"


def test_changing_iso_pool_reloads_iso_combo_from_that_pool_only(qtbot, monkeypatch):
    pools = (StoragePool(name="pool-a", state="active"), StoragePool(name="pool-b", state="active"))
    volumes_by_pool = {
        "pool-a": [StorageVolume(name="a.iso", path="/pool-a/a.iso")],
        "pool-b": [StorageVolume(name="b.iso", path="/pool-b/b.iso")],
    }
    dialog = _make_dialog(qtbot, monkeypatch, pools=pools, volumes_by_pool=volumes_by_pool)
    qtbot.waitUntil(lambda: dialog._iso_combo.count() == 2, timeout=1000)
    assert dialog._iso_combo.itemText(1) == "a.iso"

    dialog._iso_pool_combo.setCurrentIndex(1)
    qtbot.waitUntil(lambda: dialog._iso_combo.itemText(1) == "b.iso" if dialog._iso_combo.count() > 1 else False, timeout=1000)

    assert [dialog._iso_combo.itemText(i) for i in range(dialog._iso_combo.count())] == [
        "(None — boot the new disk directly)", "b.iso",
    ]
    # Changing the ISO pool must not affect where the VM's own disk goes.
    assert dialog._disk_pool_combo.currentData() == "pool-a"


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


def test_iso_combo_is_searchable_over_a_large_library(qtbot, monkeypatch):
    volumes = tuple(
        StorageVolume(name=f"kubernetes-node-{i}.iso", path=f"/isos/kubernetes-node-{i}.iso")
        for i in range(20)
    ) + (
        StorageVolume(name="debian-12.iso", path="/isos/debian-12.iso"),
        StorageVolume(name="fedora-40.iso", path="/isos/fedora-40.iso"),
    )
    dialog = _make_dialog(qtbot, monkeypatch, volumes=volumes)
    qtbot.waitUntil(lambda: dialog._iso_combo.count() == len(volumes) + 1, timeout=1000)

    completer = dialog._iso_completer
    completer.setCompletionPrefix("debian")
    matches = {completer.completionModel().index(i, 0).data() for i in range(completer.completionCount())}
    assert matches == {"debian-12.iso"}

    # MatchContains, not just a prefix match -- a real library's names
    # commonly need matching a substring in the middle (e.g. a shared
    # "node" component across many otherwise-differently-named ISOs).
    completer.setCompletionPrefix("node-7")
    matches = {completer.completionModel().index(i, 0).data() for i in range(completer.completionCount())}
    assert matches == {"kubernetes-node-7.iso"}


def test_iso_combo_items_carry_full_path_as_tooltip(qtbot, monkeypatch):
    volumes = (StorageVolume(name="a-very-long-real-world-iso-filename-2026.iso", path="/isos/a-very-long-real-world-iso-filename-2026.iso"),)
    dialog = _make_dialog(qtbot, monkeypatch, volumes=volumes)
    qtbot.waitUntil(lambda: dialog._iso_combo.count() == 2, timeout=1000)

    assert dialog._iso_combo.itemData(1, Qt.ItemDataRole.ToolTipRole) == "/isos/a-very-long-real-world-iso-filename-2026.iso"


def test_iso_combo_defaults_to_none_after_reload(qtbot, monkeypatch):
    volumes = (StorageVolume(name="ubuntu.iso", path="/isos/ubuntu.iso"),)
    dialog = _make_dialog(qtbot, monkeypatch, volumes=volumes)
    qtbot.waitUntil(lambda: dialog._iso_combo.count() == 2, timeout=1000)

    assert dialog._iso_combo.currentData() is None
    assert dialog._iso_combo.currentText() == "(None — boot the new disk directly)"


def test_os_variant_defaults_to_generic_and_is_searchable(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    assert dialog._os_variant_combo.currentText() == "generic"
    all_items = [dialog._os_variant_combo.itemText(i) for i in range(dialog._os_variant_combo.count())]
    assert all_items == list(_DEFAULT_OS_VARIANTS)

    # The completer searches (matches substrings anywhere, not just a
    # prefix) over the same real, loaded list -- confirms it's wired to
    # the live model, not a stale/empty one from before the async load.
    completer = dialog._os_variant_completer
    completer.setCompletionPrefix("alma")
    matches = {completer.completionModel().index(i, 0).data() for i in range(completer.completionCount())}
    assert matches == {"almalinux10", "almalinux9"}


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
    dialog._os_variant_combo.setCurrentText("win11")

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
    assert spec.os_variant == "win11"
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

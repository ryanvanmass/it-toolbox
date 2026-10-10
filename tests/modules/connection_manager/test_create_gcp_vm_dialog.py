from it_toolbox.modules.connection_manager.models import (
    GcpImageChoice,
    GcpMachineType,
    GcpSubnetwork,
)
from it_toolbox.modules.connection_manager.ui.create_gcp_vm_dialog import (
    CreateGcpVmDialog,
    machine_type_label,
)

_MODULE = "it_toolbox.modules.connection_manager.ui.create_gcp_vm_dialog"
_ZONES = ("us-central1-a", "us-east1-b", "europe-west1-c")
_MACHINE_TYPES = (
    GcpMachineType("e2-micro", 2, 1024),
    GcpMachineType("e2-medium", 2, 4096),
    GcpMachineType("c4-standard-4", 4, 15360),
)
_DEBIAN = GcpImageChoice("Debian 12", "projects/debian-cloud/global/images/family/debian-12", 10, "linux")
_WINDOWS = GcpImageChoice("Windows Server 2022", "projects/windows-cloud/global/images/family/windows-2022", 50, "windows")


def _subnets(region):
    return [
        GcpSubnetwork(name="corp", network="corp-vpc", region=region, ip_cidr_range="10.9.0.0/24"),
        GcpSubnetwork(name="default", network="default", region=region, ip_cidr_range="10.128.0.0/20"),
    ]


def _make_dialog(
    qtbot, monkeypatch, zones=_ZONES, subnets=_subnets, public=(_DEBIAN, _WINDOWS), custom=(),
    default_zone=None, created=None, create_error=None,
):
    monkeypatch.setattr(f"{_MODULE}.gcp_auth.get_credentials", lambda: object())
    monkeypatch.setattr(f"{_MODULE}.gcp_client.list_zones", lambda creds, project: list(zones))
    monkeypatch.setattr(
        f"{_MODULE}.gcp_client.list_machine_types", lambda creds, project, zone: list(_MACHINE_TYPES)
    )
    monkeypatch.setattr(f"{_MODULE}.gcp_client.list_subnetworks", lambda creds, project, region: subnets(region))
    monkeypatch.setattr(f"{_MODULE}.gcp_client.resolve_public_images", lambda creds, project: list(public))
    monkeypatch.setattr(f"{_MODULE}.gcp_client.list_project_images", lambda creds, project: list(custom))

    def fake_create(creds, spec):
        if create_error is not None:
            raise create_error
        if created is not None:
            created.append(spec)

    monkeypatch.setattr(f"{_MODULE}.gcp_client.create_instance", fake_create)
    dialog = CreateGcpVmDialog("proj", default_zone=default_zone)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _wait_ready(qtbot, dialog):
    qtbot.waitUntil(dialog._ok_button.isEnabled, timeout=2000)


def test_loads_and_picks_sensible_defaults(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    _wait_ready(qtbot, dialog)

    assert dialog._zone_combo.currentText() == "us-central1-a"
    assert dialog._machine_type_combo.currentData() == "e2-medium"
    assert dialog._image_combo.currentData() == _DEBIAN
    # The "default" network's subnet wins over the alphabetically first one.
    assert dialog._subnetwork_combo.currentData().name == "default"
    assert dialog._subnetwork_combo.currentData().region == "us-central1"
    assert dialog._disk_type_combo.currentData() == "pd-balanced"
    assert dialog._external_ip_check.isChecked()


def test_default_zone_is_preselected_when_offered(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, default_zone="europe-west1-c")
    _wait_ready(qtbot, dialog)

    assert dialog._zone_combo.currentText() == "europe-west1-c"
    assert dialog._subnetwork_combo.currentData().region == "europe-west1"


def test_changing_zone_reloads_the_region_subnets(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    _wait_ready(qtbot, dialog)

    dialog._zone_combo.setCurrentIndex(dialog._zone_combo.findData("us-east1-b"))

    qtbot.waitUntil(
        lambda: dialog._ok_button.isEnabled() and dialog._subnetwork_combo.currentData().region == "us-east1",
        timeout=2000,
    )
    assert dialog._machine_type_combo.currentData() == "e2-medium"


def test_windows_image_raises_the_disk_minimum(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    _wait_ready(qtbot, dialog)
    assert dialog._disk_spin.value() == 20

    dialog._image_combo.setCurrentIndex(dialog._image_combo.findData(_WINDOWS))

    assert dialog._disk_spin.value() == 50
    assert dialog._disk_spin.minimum() == 50


def test_hyperdisk_only_machine_series_switches_disk_type(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    _wait_ready(qtbot, dialog)

    dialog._machine_type_combo.setCurrentIndex(dialog._machine_type_combo.findData("c4-standard-4"))
    assert dialog._disk_type_combo.currentData() == "hyperdisk-balanced"

    dialog._machine_type_combo.setCurrentIndex(dialog._machine_type_combo.findData("e2-micro"))
    assert dialog._disk_type_combo.currentData() == "pd-balanced"


def test_custom_images_are_listed_after_public_ones(qtbot, monkeypatch):
    golden = GcpImageChoice("golden", "projects/proj/global/images/golden", 30, "linux")
    dialog = _make_dialog(qtbot, monkeypatch, custom=(golden,))
    _wait_ready(qtbot, dialog)

    last = dialog._image_combo.count() - 1
    assert dialog._image_combo.itemText(last) == "golden (this project)"
    assert dialog._image_combo.itemData(last) == golden


def test_missing_subnet_in_region_blocks_create(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, subnets=lambda region: [])
    qtbot.waitUntil(dialog._error_label.isVisible, timeout=2000)

    assert "no subnet in us-central1" in dialog._error_label.text()
    assert dialog._ok_button.isEnabled() is False


def test_invalid_name_is_rejected(qtbot, monkeypatch):
    created = []
    dialog = _make_dialog(qtbot, monkeypatch, created=created)
    _wait_ready(qtbot, dialog)

    dialog._name_edit.setText("Web_Server")
    dialog._on_accept()

    assert created == []
    assert "lowercase" in dialog._error_label.text()


def test_create_submits_the_form_and_closes(qtbot, monkeypatch):
    created = []
    dialog = _make_dialog(qtbot, monkeypatch, created=created)
    _wait_ready(qtbot, dialog)
    dialog._name_edit.setText("web-1")
    dialog._disk_spin.setValue(40)
    dialog._external_ip_check.setChecked(False)

    dialog._on_accept()

    qtbot.waitUntil(lambda: dialog.result() == CreateGcpVmDialog.DialogCode.Accepted, timeout=2000)
    (spec,) = created
    assert spec.project_id == "proj"
    assert spec.name == "web-1"
    assert spec.zone == "us-central1-a"
    assert spec.machine_type == "e2-medium"
    assert spec.source_image == _DEBIAN.source_image
    assert spec.disk_size_gb == 40
    assert spec.disk_type == "pd-balanced"
    assert spec.subnetwork.name == "default"
    assert spec.external_ip is False


def test_create_error_is_shown_and_the_form_stays_open(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, create_error=RuntimeError("Quota 'CPUS' exceeded."))
    _wait_ready(qtbot, dialog)
    dialog._name_edit.setText("web-1")

    dialog._on_accept()

    qtbot.waitUntil(dialog._buttons.isEnabled, timeout=2000)
    assert dialog._error_label.text() == "Quota 'CPUS' exceeded."
    assert dialog.isVisible()
    assert dialog._ok_button.text() == "Create"


def test_machine_type_label():
    assert machine_type_label(GcpMachineType("e2-medium", 2, 4096)) == "e2-medium (2 vCPUs, 4 GB)"
    assert machine_type_label(GcpMachineType("f1-micro", 1, 614)) == "f1-micro (1 vCPU, 0.6 GB)"
    assert machine_type_label(GcpMachineType("e2-small", 2, 2048)) == "e2-small (2 vCPUs, 2 GB)"

""""Create VM…" dialog for a GCP project — the Compute Engine counterpart
of CreateVmDialog: name, zone, machine type, boot image and disk, and the
subnet its one NIC lands on. Creates and starts the VM via
gcp_client.create_instance and only closes once the insert operation has
actually finished, so quota/image/disk errors show up here instead of
being silently lost.
"""

import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from it_toolbox.core.auth import gcp_auth
from it_toolbox.modules.connection_manager import gcp_client
from it_toolbox.modules.connection_manager.models import (
    GcpImageChoice,
    GcpInstanceSpec,
    GcpMachineType,
    GcpSubnetwork,
)
from it_toolbox.modules.connection_manager.ui.searchable_combo import make_searchable, resolve_data

DEFAULT_ZONE = "us-central1-a"
DEFAULT_MACHINE_TYPE = "e2-medium"
DISK_TYPES = (
    ("Balanced persistent disk", "pd-balanced"),
    ("SSD persistent disk", "pd-ssd"),
    ("Standard persistent disk", "pd-standard"),
    ("Hyperdisk Balanced", "hyperdisk-balanced"),
)
# Newer machine series only take Hyperdisk, not persistent disks -- picking
# one of these switches the disk type over so the default just works.
HYPERDISK_ONLY_SERIES = {"c4", "c4a", "c4d", "n4", "x4", "m4", "a4", "h4d"}

# Compute Engine's own rule for instance names (RFC 1035 labels).
_NAME_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")


def machine_type_label(machine_type: GcpMachineType) -> str:
    memory_gb = machine_type.memory_mb / 1024
    memory = f"{memory_gb:g}" if memory_gb >= 1 else f"{memory_gb:.1f}"
    cpus = "vCPU" if machine_type.guest_cpus == 1 else "vCPUs"
    return f"{machine_type.name} ({machine_type.guest_cpus} {cpus}, {memory} GB)"


class CreateGcpVmDialog(QDialog):
    def __init__(
        self,
        project_id: str,
        default_zone: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._default_zone = default_zone or DEFAULT_ZONE
        self._zones_loaded = False
        self._loaded_zone: str | None = None
        self._machine_types_loaded = False
        self._subnetworks_loaded = False
        self._images_loaded = False
        self.setWindowTitle(f"Create VM in {project_id}")
        self.resize(500, 400)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("my-new-vm")

        self._zone_combo = QComboBox()
        self._zone_combo.setEnabled(False)
        make_searchable(self._zone_combo, self, "Loading zones…")
        self._zone_combo.currentIndexChanged.connect(self._on_zone_changed)
        # A zone typed out in full (not picked from the popup) doesn't move
        # currentIndex -- see resolve_data -- so check again on leaving it.
        self._zone_combo.lineEdit().editingFinished.connect(self._on_zone_changed)

        self._machine_type_combo = QComboBox()
        self._machine_type_combo.setEnabled(False)
        make_searchable(self._machine_type_combo, self, "Type to search")
        self._machine_type_combo.currentIndexChanged.connect(self._on_machine_type_changed)

        self._image_combo = QComboBox()
        self._image_combo.setEnabled(False)
        self._image_combo.currentIndexChanged.connect(self._on_image_changed)

        self._disk_spin = QSpinBox()
        self._disk_spin.setRange(10, 65_536)
        self._disk_spin.setSuffix(" GB")
        self._disk_spin.setValue(20)

        self._disk_type_combo = QComboBox()
        for label, disk_type in DISK_TYPES:
            self._disk_type_combo.addItem(label, disk_type)

        self._subnetwork_combo = QComboBox()
        self._subnetwork_combo.setEnabled(False)

        self._external_ip_check = QCheckBox("Assign an external IP address")
        self._external_ip_check.setChecked(True)
        self._external_ip_check.setToolTip(
            "Not needed to connect from this app (SSH, RDP and SFTP go through IAP), "
            "but the VM has no internet access without it unless the network has Cloud NAT."
        )

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: red;")
        self._error_label.setVisible(False)

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("Zone:", self._zone_combo)
        form.addRow("Machine type:", self._machine_type_combo)
        form.addRow("Image:", self._image_combo)
        form.addRow("Boot disk size:", self._disk_spin)
        form.addRow("Boot disk type:", self._disk_type_combo)
        form.addRow("Subnet:", self._subnetwork_combo)
        form.addRow("", self._external_ip_check)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText("Create")
        self._ok_button.setEnabled(False)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._error_label)
        layout.addWidget(self._buttons)

        self._load_zones()
        self._load_images()

    # -- loading -----------------------------------------------------------

    def _load_zones(self) -> None:
        project_id = self._project_id
        async_utils.run_in_background(
            lambda: gcp_client.list_zones(gcp_auth.get_credentials(), project_id),
            on_result=self._on_zones_loaded,
            on_error=self._on_load_error,
        )

    def _on_zones_loaded(self, zones: list[str]) -> None:
        if not zones:
            self._show_error(
                f"No zones available in {self._project_id}. Is the Compute Engine API enabled?"
            )
            return
        self._zone_combo.lineEdit().setPlaceholderText("Type to search")
        self._zone_combo.blockSignals(True)
        for zone in zones:
            self._zone_combo.addItem(zone, zone)
        index = self._zone_combo.findData(self._default_zone)
        self._zone_combo.setCurrentIndex(index if index != -1 else 0)
        self._zone_combo.blockSignals(False)
        self._zone_combo.setEnabled(True)
        self._zones_loaded = True
        self._on_zone_changed()

    def _current_zone(self) -> str | None:
        return resolve_data(self._zone_combo)

    def _on_zone_changed(self, _index: int = -1) -> None:
        zone = self._current_zone()
        if zone is None or zone == self._loaded_zone:
            return
        self._loaded_zone = zone
        self._machine_types_loaded = False
        self._subnetworks_loaded = False
        self._machine_type_combo.setEnabled(False)
        self._subnetwork_combo.setEnabled(False)
        self._update_ok_enabled()
        project_id = self._project_id
        async_utils.run_in_background(
            lambda: gcp_client.list_machine_types(gcp_auth.get_credentials(), project_id, zone),
            on_result=lambda types: self._on_machine_types_loaded(zone, types),
            on_error=self._on_load_error,
        )
        region = gcp_client.region_of_zone(zone)
        async_utils.run_in_background(
            lambda: gcp_client.list_subnetworks(gcp_auth.get_credentials(), project_id, region),
            on_result=lambda subnets: self._on_subnetworks_loaded(zone, subnets),
            on_error=self._on_load_error,
        )

    def _on_machine_types_loaded(self, zone: str, machine_types: list[GcpMachineType]) -> None:
        if zone != self._current_zone():
            return  # the zone changed again while this was loading
        # Keep the chosen machine type across zone changes when the new
        # zone offers it too; otherwise fall back to the default.
        previous = resolve_data(self._machine_type_combo) or DEFAULT_MACHINE_TYPE
        self._machine_type_combo.blockSignals(True)
        self._machine_type_combo.clear()
        for machine_type in machine_types:
            self._machine_type_combo.addItem(machine_type_label(machine_type), machine_type.name)
        index = self._machine_type_combo.findData(previous)
        if index == -1:
            index = self._machine_type_combo.findData(DEFAULT_MACHINE_TYPE)
        self._machine_type_combo.setCurrentIndex(index if index != -1 else 0)
        self._machine_type_combo.blockSignals(False)
        self._machine_type_combo.setEnabled(bool(machine_types))
        self._machine_types_loaded = bool(machine_types)
        self._on_machine_type_changed()
        if not machine_types:
            self._show_error(f"No machine types available in {zone}.")
        self._update_ok_enabled()

    def _on_subnetworks_loaded(self, zone: str, subnetworks: list[GcpSubnetwork]) -> None:
        if zone != self._current_zone():
            return
        previous = self._subnetwork_combo.currentData()
        self._subnetwork_combo.clear()
        for subnetwork in subnetworks:
            label = f"{subnetwork.network} / {subnetwork.name}"
            if subnetwork.ip_cidr_range:
                label += f" ({subnetwork.ip_cidr_range})"
            self._subnetwork_combo.addItem(label, subnetwork)
        index = self._subnetwork_combo.findData(previous) if previous is not None else -1
        if index == -1:
            # Prefer the "default" network's subnet when there is one.
            index = next(
                (i for i, s in enumerate(subnetworks) if s.network == "default"), 0
            )
        self._subnetwork_combo.setCurrentIndex(index)
        self._subnetwork_combo.setEnabled(bool(subnetworks))
        self._subnetworks_loaded = bool(subnetworks)
        if subnetworks:
            self._error_label.setVisible(False)
        else:
            self._show_error(
                f"{self._project_id} has no subnet in {gcp_client.region_of_zone(zone)}. "
                "Pick a zone in another region, or create a subnet there first."
            )
        self._update_ok_enabled()

    def _load_images(self) -> None:
        project_id = self._project_id

        def load() -> tuple[list[GcpImageChoice], list[GcpImageChoice]]:
            credentials = gcp_auth.get_credentials()
            public = gcp_client.resolve_public_images(credentials, project_id)
            try:
                custom = gcp_client.list_project_images(credentials, project_id)
            except gcp_client.GcpApiError:
                custom = []  # custom images are optional; public ones are enough
            return public, custom

        async_utils.run_in_background(load, on_result=self._on_images_loaded, on_error=self._on_load_error)

    def _on_images_loaded(self, result: tuple[list[GcpImageChoice], list[GcpImageChoice]]) -> None:
        public, custom = result
        self._image_combo.blockSignals(True)
        for image in public:
            self._image_combo.addItem(image.label, image)
        if public and custom:
            self._image_combo.insertSeparator(self._image_combo.count())
        for image in custom:
            self._image_combo.addItem(f"{image.label} (this project)", image)
        self._image_combo.blockSignals(False)
        if not public and not custom:
            self._show_error("Couldn't load any boot images.")
            return
        self._image_combo.setCurrentIndex(0)
        self._image_combo.setEnabled(True)
        self._images_loaded = True
        self._on_image_changed()
        self._update_ok_enabled()

    # -- field reactions -----------------------------------------------------

    def _on_image_changed(self, _index: int = -1) -> None:
        image = self._image_combo.currentData()
        if image is None:
            return
        # Never smaller than the image itself (Windows needs 50 GB); bumps
        # the size up when switching to a bigger image but leaves a size
        # the user already raised alone.
        self._disk_spin.setMinimum(max(10, image.min_disk_gb))
        if self._disk_spin.value() < image.min_disk_gb:
            self._disk_spin.setValue(image.min_disk_gb)

    def _on_machine_type_changed(self, _index: int = -1) -> None:
        machine_type = resolve_data(self._machine_type_combo)
        if machine_type is None:
            return
        series = machine_type.split("-", 1)[0]
        current = self._disk_type_combo.currentData()
        if series in HYPERDISK_ONLY_SERIES and current != "hyperdisk-balanced":
            self._disk_type_combo.setCurrentIndex(self._disk_type_combo.findData("hyperdisk-balanced"))
        elif series not in HYPERDISK_ONLY_SERIES and current == "hyperdisk-balanced":
            self._disk_type_combo.setCurrentIndex(self._disk_type_combo.findData("pd-balanced"))

    def _update_ok_enabled(self) -> None:
        self._ok_button.setEnabled(
            self._zones_loaded
            and self._machine_types_loaded
            and self._subnetworks_loaded
            and self._images_loaded
        )

    def _on_load_error(self, error: Exception) -> None:
        self._show_error(str(error))

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    # -- submit --------------------------------------------------------------

    def spec(self) -> GcpInstanceSpec | None:
        """The VM described by the form, or None (with the reason shown)
        if something is missing or invalid."""
        name = self._name_edit.text().strip()
        if not name:
            self._show_error("Name is required.")
            return None
        if not _NAME_RE.match(name):
            self._show_error(
                "Names must start with a lowercase letter, use only lowercase letters, "
                "digits and hyphens, not end with a hyphen, and be at most 63 characters."
            )
            return None
        zone = self._current_zone()
        machine_type = resolve_data(self._machine_type_combo)
        image = self._image_combo.currentData()
        subnetwork = self._subnetwork_combo.currentData()
        if zone is None or machine_type is None or image is None or subnetwork is None:
            self._show_error("Pick a zone, machine type, image and subnet.")
            return None
        return GcpInstanceSpec(
            project_id=self._project_id,
            name=name,
            zone=zone,
            machine_type=machine_type,
            source_image=image.source_image,
            disk_size_gb=self._disk_spin.value(),
            disk_type=self._disk_type_combo.currentData(),
            subnetwork=subnetwork,
            external_ip=self._external_ip_check.isChecked(),
        )

    def _on_accept(self) -> None:
        spec = self.spec()
        if spec is None:
            return
        self._error_label.setVisible(False)
        self._buttons.setEnabled(False)
        self._ok_button.setText("Creating…")
        async_utils.run_in_background(
            lambda: gcp_client.create_instance(gcp_auth.get_credentials(), spec),
            on_result=lambda _: self.accept(),
            on_error=self._on_create_error,
        )

    def _on_create_error(self, error: Exception) -> None:
        self._buttons.setEnabled(True)
        self._ok_button.setText("Create")
        self._show_error(str(error))

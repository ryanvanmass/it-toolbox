from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFormLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, settings
from it_toolbox.modules.identity_management import jumpcloud_client
from it_toolbox.modules.identity_management.models import Device, User
from it_toolbox.modules.identity_management.ui.api_key_dialog import ApiKeyDialog

DEVICE_ROLE = Qt.ItemDataRole.UserRole
USER_ROLE = Qt.ItemDataRole.UserRole


class IdentityManagementView(QWidget):
    """Devices/Users browser for JumpCloud — the first of what issue #15
    expects to grow into a small collection of identity-management tool
    integrations. No sidebar tree in this first version (unlike Connection
    Manager/Cloud Storage): there's no hierarchical navigation need yet,
    so this is just the two-tab main view; a "Set JumpCloud API Key…" /
    "Refresh" context menu (build_context_menu) covers the rest.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Cached in memory only for this session once successfully
        # decrypted — never re-persisted — so a passphrase-protected SSH
        # key isn't re-prompted on every single API call.
        self._cached_api_key: str | None = None
        self._selected_device: Device | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_devices_tab(), "Devices")
        tabs.addTab(self._build_users_tab(), "Users")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        self.refresh()

    # -- Devices tab --------------------------------------------------------

    def _build_devices_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self._device_status_label = QLabel("")
        self._device_status_label.setWordWrap(True)
        layout.addWidget(self._device_status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._devices_table = QTableWidget(0, 3)
        self._devices_table.setHorizontalHeaderLabels(["Name", "OS", "Last Contact"])
        self._devices_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._devices_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._devices_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._devices_table.currentItemChanged.connect(self._on_device_selection_changed)
        splitter.addWidget(self._devices_table)

        splitter.addWidget(self._build_device_detail_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        return container

    def _build_device_detail_panel(self) -> QWidget:
        panel = QWidget()
        panel.setEnabled(False)
        form = QFormLayout(panel)

        self._device_placeholder_label = QLabel("Select a device to see its details.")
        form.addRow(self._device_placeholder_label)

        self._device_fields = {
            "hostname": QLabel(""),
            "os_version": QLabel(""),
            "serial_number": QLabel(""),
            "agent_version": QLabel(""),
            "last_contact": QLabel(""),
        }
        form.addRow("Hostname:", self._device_fields["hostname"])
        form.addRow("OS Version:", self._device_fields["os_version"])
        form.addRow("Serial Number:", self._device_fields["serial_number"])
        form.addRow("Agent Version:", self._device_fields["agent_version"])
        form.addRow("Last Contact:", self._device_fields["last_contact"])

        # No public API exists to start a JumpCloud Remote Assist session
        # (WebRTC, negotiated entirely through their own console) — this
        # deep-links to the device's Admin Portal page instead, same as
        # clicking through from the console yourself.
        self._remote_assist_button = QPushButton("Launch Remote Assist")
        self._remote_assist_button.clicked.connect(self._on_launch_remote_assist_clicked)
        form.addRow(self._remote_assist_button)

        self._device_detail_panel = panel
        return panel

    def _on_device_selection_changed(self, current, previous) -> None:
        if current is None:
            self._selected_device = None
            self._device_detail_panel.setEnabled(False)
            self._device_placeholder_label.setVisible(True)
            return

        device: Device = self._devices_table.item(current.row(), 0).data(DEVICE_ROLE)
        self._selected_device = device
        self._device_detail_panel.setEnabled(True)
        self._device_placeholder_label.setVisible(False)
        # Instant partial render from the list row's own data, then
        # backfill the detail-only fields once get_device() resolves —
        # avoids a blank/loading flash on every click.
        self._device_fields["hostname"].setText(device.hostname)
        self._device_fields["os_version"].setText(device.os_version or "Loading…")
        self._device_fields["serial_number"].setText(device.serial_number or "Loading…")
        self._device_fields["agent_version"].setText(device.agent_version or "Loading…")
        self._device_fields["last_contact"].setText(device.last_contact or "Loading…")

        api_key = self._get_api_key()
        if api_key is None:
            return
        async_utils.run_in_background(
            lambda: jumpcloud_client.get_device(api_key, device.id),
            on_result=self._populate_device_detail,
            on_error=self._on_detail_error,
        )

    def _populate_device_detail(self, device: Device) -> None:
        try:
            # The selection may have moved on before this resolved.
            if self._selected_device is None or self._selected_device.id != device.id:
                return
            self._device_fields["os_version"].setText(device.os_version)
            self._device_fields["serial_number"].setText(device.serial_number)
            self._device_fields["agent_version"].setText(device.agent_version)
            self._device_fields["last_contact"].setText(device.last_contact)
        except RuntimeError:
            pass  # widget torn down mid-flight

    def _on_detail_error(self, error: Exception) -> None:
        try:
            QMessageBox.warning(self, "Failed to load device details", str(error))
        except RuntimeError:
            pass  # widget torn down mid-flight

    def _on_launch_remote_assist_clicked(self) -> None:
        if self._selected_device is None:
            return
        url = jumpcloud_client.remote_assist_url(self._selected_device.id)
        QDesktopServices.openUrl(QUrl(url))

    def _populate_devices(self, devices: list[Device]) -> None:
        try:
            self._device_status_label.setText("" if devices else "No devices found.")
            self._devices_table.setRowCount(len(devices))
            for row, device in enumerate(devices):
                name_item = QTableWidgetItem(device.display_name)
                name_item.setData(DEVICE_ROLE, device)
                self._devices_table.setItem(row, 0, name_item)
                self._devices_table.setItem(row, 1, QTableWidgetItem(device.os))
                self._devices_table.setItem(row, 2, QTableWidgetItem(device.last_contact))
        except RuntimeError:
            pass  # widget torn down mid-flight

    # -- Users tab ------------------------------------------------------------

    def _build_users_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self._user_status_label = QLabel("")
        self._user_status_label.setWordWrap(True)
        layout.addWidget(self._user_status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._users_table = QTableWidget(0, 2)
        self._users_table.setHorizontalHeaderLabels(["Username", "Email"])
        self._users_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._users_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._users_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._users_table.currentItemChanged.connect(self._on_user_selection_changed)
        splitter.addWidget(self._users_table)

        splitter.addWidget(self._build_user_detail_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        return container

    def _build_user_detail_panel(self) -> QWidget:
        panel = QWidget()
        panel.setEnabled(False)
        form = QFormLayout(panel)

        self._user_placeholder_label = QLabel("Select a user to see its details.")
        form.addRow(self._user_placeholder_label)

        self._user_fields = {
            "first_name": QLabel(""),
            "last_name": QLabel(""),
            "suspended": QLabel(""),
        }
        form.addRow("First Name:", self._user_fields["first_name"])
        form.addRow("Last Name:", self._user_fields["last_name"])
        form.addRow("Suspended:", self._user_fields["suspended"])

        self._user_detail_panel = panel
        return panel

    def _on_user_selection_changed(self, current, previous) -> None:
        if current is None:
            self._user_detail_panel.setEnabled(False)
            self._user_placeholder_label.setVisible(True)
            return

        # Unlike devices, list_users() already returns everything the
        # detail panel shows — no separate detail endpoint/async call
        # needed, just render straight from the row's stashed User.
        user: User = self._users_table.item(current.row(), 0).data(USER_ROLE)
        self._user_detail_panel.setEnabled(True)
        self._user_placeholder_label.setVisible(False)
        self._user_fields["first_name"].setText(user.first_name)
        self._user_fields["last_name"].setText(user.last_name)
        self._user_fields["suspended"].setText("Yes" if user.suspended else "No")

    def _populate_users(self, users: list[User]) -> None:
        try:
            self._user_status_label.setText("" if users else "No users found.")
            self._users_table.setRowCount(len(users))
            for row, user in enumerate(users):
                username_item = QTableWidgetItem(user.username)
                username_item.setData(USER_ROLE, user)
                self._users_table.setItem(row, 0, username_item)
                self._users_table.setItem(row, 1, QTableWidgetItem(user.email))
        except RuntimeError:
            pass  # widget torn down mid-flight

    # -- API key / refresh ----------------------------------------------------

    def build_context_menu(self, parent: QWidget) -> QMenu:
        """Shown when right-clicking this module's entry in the app
        sidebar — see IdentityManagementModule.build_context_menu().
        """
        menu = QMenu(parent)
        configured = settings.jumpcloud_api_key_path().is_file()
        label = "Change JumpCloud API Key…" if configured else "Set JumpCloud API Key…"
        menu.addAction(label).triggered.connect(self._on_set_api_key_clicked)
        menu.addAction("Refresh").triggered.connect(self.refresh)
        return menu

    def _on_set_api_key_clicked(self) -> None:
        dialog = ApiKeyDialog(parent=self)
        if dialog.exec() == ApiKeyDialog.DialogCode.Accepted:
            self._cached_api_key = None
            self.refresh()

    def _get_api_key(self) -> str | None:
        if self._cached_api_key is not None:
            return self._cached_api_key
        try:
            api_key = settings.load_jumpcloud_api_key()
        except settings.SecretDecryptionError:
            passphrase, ok = QInputDialog.getText(
                self,
                "SSH Key Passphrase",
                "Your SSH key is passphrase-protected — enter its passphrase to unlock "
                "the stored JumpCloud API key:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return None
            try:
                api_key = settings.load_jumpcloud_api_key(passphrase=passphrase)
            except settings.SecretDecryptionError as exc:
                QMessageBox.warning(self, "JumpCloud", str(exc))
                return None
        if api_key is not None:
            self._cached_api_key = api_key
        return api_key

    def refresh(self) -> None:
        api_key = self._get_api_key()
        if api_key is None:
            message = (
                "Couldn't unlock the stored JumpCloud API key — set it again via the "
                "sidebar menu."
                if settings.jumpcloud_api_key_path().is_file()
                else 'No JumpCloud API key configured yet — right-click "Identity '
                'Management" in the sidebar and choose "Set JumpCloud API Key…".'
            )
            self._devices_table.setRowCount(0)
            self._users_table.setRowCount(0)
            self._device_status_label.setText(message)
            self._user_status_label.setText(message)
            return

        self._device_status_label.setText("")
        self._user_status_label.setText("")
        async_utils.run_in_background(
            lambda: jumpcloud_client.list_devices(api_key),
            on_result=self._populate_devices,
            on_error=self._on_load_error,
        )
        async_utils.run_in_background(
            lambda: jumpcloud_client.list_users(api_key),
            on_result=self._populate_users,
            on_error=self._on_load_error,
        )

    def _on_load_error(self, error: Exception) -> None:
        try:
            QMessageBox.warning(self, "Failed to load from JumpCloud", str(error))
        except RuntimeError:
            pass  # widget torn down mid-flight

"""GL.iNet router management dashboard — embedded as a Connection Manager
tab (see ConnectionManagerView._open_glinet_dashboard), not itself
Connection-Manager-specific, same as BucketBrowserWidget/RdpWidget.

Five tabs: Overview, Clients, WiFi, VPN (status only — v1 doesn't support
editing tunnel configs, see docs/glinet-dashboard-status.md), and Reboot.
Every fetch/action goes through glinet_client, which opens and closes its
own GlInet session per call — nothing here holds a live connection open.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.modules.connection_manager import glinet_client
from it_toolbox.modules.connection_manager.models import (
    GlinetHost,
    GlinetVpnTunnel,
    GlinetWifiRadio,
)


class _WifiNetworkEditDialog(QDialog):
    """Edit one WiFi network's SSID/password -- opened via the WiFi
    tab's table (double-click a row, or select + "Edit…"), since the
    table itself is read-only like the VPN tab's."""

    def __init__(self, radio: GlinetWifiRadio, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit {radio.ssid or radio.iface_name}")

        self._ssid_edit = QLineEdit(radio.ssid)
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Leave blank to keep the existing password")
        status_label = QLabel("Enabled" if radio.enabled else "Disabled")

        form = QFormLayout()
        form.addRow("SSID:", self._ssid_edit)
        form.addRow("Password:", self._password_edit)
        form.addRow("Status:", status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def ssid(self) -> str:
        return self._ssid_edit.text().strip()

    def password(self) -> str:
        return self._password_edit.text()


class GlinetDashboardWidget(QWidget):
    def __init__(self, host: GlinetHost, password: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self._password = password

        if glinet_client.GlInet is None:
            layout = QVBoxLayout(self)
            label = QLabel(
                "python-glinet isn't installed — GL.iNet dashboards need it. See Settings "
                "for install instructions."
            )
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            return

        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(), "Overview")
        tabs.addTab(self._build_clients_tab(), "Clients")
        tabs.addTab(self._build_wifi_tab(), "WiFi")
        tabs.addTab(self._build_vpn_tab(), "VPN")
        tabs.addTab(self._build_reboot_tab(), "Reboot")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        self._reload_overview()
        self._reload_clients()
        self._reload_wifi()
        self._reload_vpn()

    # -- Overview -----------------------------------------------------------

    def _build_overview_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout()
        self._overview_fields = {
            "uptime": QLabel("Loading…"),
            "lan_ip": QLabel("Loading…"),
            "memory_used_pct": QLabel("Loading…"),
            "cpu_temp": QLabel("Loading…"),
            "wireless_client_count": QLabel("Loading…"),
            "cable_client_count": QLabel("Loading…"),
        }
        form.addRow("Uptime:", self._overview_fields["uptime"])
        form.addRow("LAN IP:", self._overview_fields["lan_ip"])
        form.addRow("Memory used:", self._overview_fields["memory_used_pct"])
        form.addRow("CPU temp:", self._overview_fields["cpu_temp"])
        form.addRow("Wireless clients:", self._overview_fields["wireless_client_count"])
        form.addRow("Cable clients:", self._overview_fields["cable_client_count"])

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_overview)

        layout = QVBoxLayout(widget)
        layout.addLayout(form)
        layout.addWidget(refresh_button)
        layout.addStretch(1)
        return widget

    def _reload_overview(self) -> None:
        async_utils.run_in_background(
            lambda: glinet_client.get_overview(self._host, self._password),
            on_result=self._on_overview_loaded,
            on_error=self._on_error,
        )

    def _on_overview_loaded(self, overview) -> None:
        self._overview = overview
        self._overview_fields["uptime"].setText(overview.uptime or "—")
        self._overview_fields["lan_ip"].setText(overview.lan_ip or "—")
        self._overview_fields["memory_used_pct"].setText(
            f"{overview.memory_used_pct}%" if overview.memory_used_pct is not None else "—"
        )
        self._overview_fields["cpu_temp"].setText(
            f"{overview.cpu_temp}°C" if overview.cpu_temp is not None else "—"
        )
        self._overview_fields["wireless_client_count"].setText(str(overview.wireless_client_count))
        self._overview_fields["cable_client_count"].setText(str(overview.cable_client_count))

    # -- Clients --------------------------------------------------------------

    def _build_clients_tab(self) -> QWidget:
        widget = QWidget()
        self._clients_table = QTableWidget(0, 4)
        self._clients_table.setHorizontalHeaderLabels(["Name", "MAC", "IP", "Online"])
        self._clients_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._clients_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_clients)

        layout = QVBoxLayout(widget)
        layout.addWidget(self._clients_table)
        layout.addWidget(refresh_button)
        return widget

    def _reload_clients(self) -> None:
        async_utils.run_in_background(
            lambda: glinet_client.list_clients(self._host, self._password),
            on_result=self._on_clients_loaded,
            on_error=self._on_error,
        )

    def _on_clients_loaded(self, clients) -> None:
        self._clients_table.setRowCount(len(clients))
        for row, client in enumerate(clients):
            self._clients_table.setItem(row, 0, QTableWidgetItem(client.name or "(unknown)"))
            self._clients_table.setItem(row, 1, QTableWidgetItem(client.mac))
            self._clients_table.setItem(row, 2, QTableWidgetItem(client.ip))
            self._clients_table.setItem(row, 3, QTableWidgetItem("Yes" if client.online else "No"))

    # -- WiFi -----------------------------------------------------------------

    def _build_wifi_tab(self) -> QWidget:
        widget = QWidget()
        self._wifi_radios: list[GlinetWifiRadio] = []
        self._wifi_table = QTableWidget(0, 5)
        self._wifi_table.setHorizontalHeaderLabels(["Network", "Device", "Band", "SSID", "Status"])
        self._wifi_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._wifi_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._wifi_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._wifi_table.itemDoubleClicked.connect(lambda _item: self._on_edit_wifi_clicked())

        edit_button = QPushButton("Edit…")
        edit_button.clicked.connect(self._on_edit_wifi_clicked)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_wifi)

        button_row = QHBoxLayout()
        button_row.addWidget(edit_button)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)

        layout = QVBoxLayout(widget)
        layout.addWidget(self._wifi_table)
        layout.addLayout(button_row)
        return widget

    def _reload_wifi(self) -> None:
        async_utils.run_in_background(
            lambda: glinet_client.get_wifi_config(self._host, self._password),
            on_result=self._on_wifi_loaded,
            on_error=self._on_error,
        )

    def _on_wifi_loaded(self, radios: list[GlinetWifiRadio]) -> None:
        # All Main networks (2.4G, 5G, ...) together, then all Guest
        # networks together -- rather than interleaved by physical radio.
        self._wifi_radios = [
            radio for is_guest in (False, True) for radio in radios if radio.guest is is_guest
        ]
        self._wifi_table.setRowCount(len(self._wifi_radios))
        for row, radio in enumerate(self._wifi_radios):
            band_label = "2.4G" if radio.band == "2G" else radio.band
            self._wifi_table.setItem(row, 0, QTableWidgetItem("Guest" if radio.guest else "Main"))
            self._wifi_table.setItem(row, 1, QTableWidgetItem(radio.device))
            self._wifi_table.setItem(row, 2, QTableWidgetItem(band_label))
            self._wifi_table.setItem(row, 3, QTableWidgetItem(radio.ssid))
            self._wifi_table.setItem(
                row, 4, QTableWidgetItem("Enabled" if radio.enabled else "Disabled")
            )

    def _on_edit_wifi_clicked(self) -> None:
        row = self._wifi_table.currentRow()
        if row < 0 or row >= len(self._wifi_radios):
            return
        radio = self._wifi_radios[row]
        dialog = _WifiNetworkEditDialog(radio, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_wifi_config(radio, dialog.ssid(), dialog.password())

    def _save_wifi_config(self, radio: GlinetWifiRadio, ssid: str, password: str) -> None:
        async_utils.run_in_background(
            lambda: glinet_client.set_wifi_config(
                self._host,
                self._password,
                device=radio.device,
                iface_name=radio.iface_name,
                ssid=ssid,
                key=password or None,
                enabled=radio.enabled,
            ),
            on_result=lambda _: self._reload_wifi(),
            on_error=self._on_error,
        )

    # -- VPN (status only — see module docstring) ------------------------------

    def _build_vpn_tab(self) -> QWidget:
        widget = QWidget()
        self._vpn_table = QTableWidget(0, 6)
        self._vpn_table.setHorizontalHeaderLabels(
            ["Name", "Type", "From", "To", "Via", "Status"]
        )
        self._vpn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._vpn_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_vpn)

        note = QLabel(
            "Status only — this dashboard doesn't yet support adding, editing, or "
            "toggling VPN tunnels."
        )
        note.setWordWrap(True)

        layout = QVBoxLayout(widget)
        layout.addWidget(self._vpn_table)
        layout.addWidget(refresh_button)
        layout.addWidget(note)
        return widget

    def _reload_vpn(self) -> None:
        async_utils.run_in_background(
            lambda: glinet_client.list_vpn_tunnels(self._host, self._password),
            on_result=self._on_vpn_loaded,
            on_error=self._on_error,
        )

    def _on_vpn_loaded(self, tunnels: list[GlinetVpnTunnel]) -> None:
        self._vpn_table.setRowCount(len(tunnels))
        for row, tunnel in enumerate(tunnels):
            status_text = "Up" if tunnel.up else ("Enabled" if tunnel.enabled else "Disabled")
            name_text = f"{tunnel.name} (Kill Switch)" if tunnel.killswitch else tunnel.name
            self._vpn_table.setItem(row, 0, QTableWidgetItem(name_text))
            self._vpn_table.setItem(row, 1, QTableWidgetItem(tunnel.type))

            from_item = QTableWidgetItem(tunnel.from_summary)
            if tunnel.from_detail:
                from_item.setToolTip(tunnel.from_detail)
            self._vpn_table.setItem(row, 2, from_item)

            to_item = QTableWidgetItem(tunnel.to_summary)
            if tunnel.to_detail:
                to_item.setToolTip(tunnel.to_detail)
            self._vpn_table.setItem(row, 3, to_item)

            self._vpn_table.setItem(row, 4, QTableWidgetItem(tunnel.via_summary))
            self._vpn_table.setItem(row, 5, QTableWidgetItem(status_text))

    # -- Reboot -----------------------------------------------------------

    def _build_reboot_tab(self) -> QWidget:
        widget = QWidget()
        reboot_button = QPushButton("Reboot Router")
        reboot_button.clicked.connect(self._on_reboot_clicked)

        layout = QVBoxLayout(widget)
        layout.addStretch(1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(reboot_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)
        return widget

    def _on_reboot_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reboot Router",
            f"Reboot {self._host.name}? Every device connected to it will briefly lose "
            "network access.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        async_utils.run_in_background(
            lambda: glinet_client.reboot(self._host, self._password),
            on_result=lambda _: None,
            on_error=self._on_error,
        )

    # -- Shared -------------------------------------------------------------

    def _on_error(self, error: Exception) -> None:
        QMessageBox.warning(self, "GL.iNet error", str(error))

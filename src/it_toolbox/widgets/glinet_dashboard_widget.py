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
    QFormLayout,
    QGroupBox,
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
from it_toolbox.modules.connection_manager.models import GlinetHost, GlinetWifiRadio


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
        self._update_vpn_labels(overview)

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
        self._wifi_container = QWidget()
        self._wifi_layout = QVBoxLayout(self._wifi_container)
        self._wifi_layout.addWidget(QLabel("Loading…"))
        self._wifi_layout.addStretch(1)
        return self._wifi_container

    def _reload_wifi(self) -> None:
        async_utils.run_in_background(
            lambda: glinet_client.get_wifi_config(self._host, self._password),
            on_result=self._on_wifi_loaded,
            on_error=self._on_error,
        )

    def _on_wifi_loaded(self, radios: list[GlinetWifiRadio]) -> None:
        while self._wifi_layout.count():
            item = self._wifi_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        if not radios:
            self._wifi_layout.addWidget(QLabel("No WiFi radios reported."))
        for radio in radios:
            self._wifi_layout.addWidget(self._build_radio_group(radio))
        self._wifi_layout.addStretch(1)

    def _build_radio_group(self, radio: GlinetWifiRadio) -> QGroupBox:
        box = QGroupBox(f"{radio.device} ({radio.band})" if radio.band else radio.device)
        form = QFormLayout()

        ssid_edit = QLineEdit(radio.ssid)
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        password_edit.setPlaceholderText("Leave blank to keep the existing password")
        enabled_label = QLabel("Enabled" if radio.enabled else "Disabled")

        form.addRow("SSID:", ssid_edit)
        form.addRow("Password:", password_edit)
        form.addRow("Status:", enabled_label)

        save_button = QPushButton("Save")
        save_button.clicked.connect(
            lambda: self._save_wifi_config(radio, ssid_edit.text().strip(), password_edit.text())
        )

        layout = QVBoxLayout(box)
        layout.addLayout(form)
        layout.addWidget(save_button)
        return box

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
        form = QFormLayout()
        self._vpn_fields = {
            "wg_client": QLabel("Loading…"),
            "wg_server": QLabel("Loading…"),
            "ovpn_client": QLabel("Loading…"),
            "ovpn_server": QLabel("Loading…"),
        }
        form.addRow("WireGuard client:", self._vpn_fields["wg_client"])
        form.addRow("WireGuard server:", self._vpn_fields["wg_server"])
        form.addRow("OpenVPN client:", self._vpn_fields["ovpn_client"])
        form.addRow("OpenVPN server:", self._vpn_fields["ovpn_server"])

        note = QLabel(
            "Status only — this dashboard doesn't yet support adding or editing VPN "
            "tunnel configs."
        )
        note.setWordWrap(True)

        layout = QVBoxLayout(widget)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch(1)
        return widget

    def _update_vpn_labels(self, overview) -> None:
        def status_text(up: bool) -> str:
            return "Up" if up else "Down"

        self._vpn_fields["wg_client"].setText(status_text(overview.wg_client_up))
        self._vpn_fields["wg_server"].setText(status_text(overview.wg_server_up))
        self._vpn_fields["ovpn_client"].setText(status_text(overview.ovpn_client_up))
        self._vpn_fields["ovpn_server"].setText(status_text(overview.ovpn_server_up))

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

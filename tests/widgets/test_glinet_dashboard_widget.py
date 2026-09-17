from PySide6.QtWidgets import QLabel, QMessageBox

from it_toolbox.modules.connection_manager.models import (
    GlinetClientInfo,
    GlinetHost,
    GlinetOverview,
    GlinetVpnTunnel,
    GlinetWifiRadio,
)
from it_toolbox.widgets.glinet_dashboard_widget import GlinetDashboardWidget

HOST = GlinetHost(name="Travel Router", url="https://192.168.8.1/rpc")

OVERVIEW = GlinetOverview(
    uptime="1d 2h",
    lan_ip="192.168.8.1",
    memory_used_pct=42.0,
    cpu_temp=50.0,
    wireless_client_count=2,
    cable_client_count=1,
    wifi_radios=(),
)


def _make_dashboard(qtbot, monkeypatch, glinet_available=True, overview=OVERVIEW, clients=(),
                     wifi_radios=(), vpn_tunnels=()):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    monkeypatch.setattr(module.glinet_client, "GlInet", object() if glinet_available else None)
    monkeypatch.setattr(module.glinet_client, "get_overview", lambda host, password: overview)
    monkeypatch.setattr(module.glinet_client, "list_clients", lambda host, password: list(clients))
    monkeypatch.setattr(
        module.glinet_client, "get_wifi_config", lambda host, password: list(wifi_radios)
    )
    monkeypatch.setattr(
        module.glinet_client, "list_vpn_tunnels", lambda host, password: list(vpn_tunnels)
    )
    dashboard = GlinetDashboardWidget(HOST, "secret")
    qtbot.addWidget(dashboard)
    return dashboard


def test_shows_not_installed_message_when_glinet_missing(qtbot, monkeypatch):
    dashboard = _make_dashboard(qtbot, monkeypatch, glinet_available=False)

    # No tab widget (and none of the per-tab state) is built at all when
    # pyglinet is unavailable -- just the fallback QLabel.
    assert not hasattr(dashboard, "_overview_fields")
    labels = dashboard.findChildren(QLabel)
    assert any("isn't installed" in label.text() for label in labels)


def test_overview_tab_populates_from_get_overview(qtbot, monkeypatch):
    dashboard = _make_dashboard(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: dashboard._overview_fields["uptime"].text() == "1d 2h", timeout=2000)

    assert dashboard._overview_fields["lan_ip"].text() == "192.168.8.1"
    assert dashboard._overview_fields["memory_used_pct"].text() == "42.0%"
    assert dashboard._overview_fields["cpu_temp"].text() == "50.0°C"
    assert dashboard._overview_fields["wireless_client_count"].text() == "2"
    assert dashboard._overview_fields["cable_client_count"].text() == "1"


def test_vpn_tab_populates_from_list_vpn_tunnels(qtbot, monkeypatch):
    tunnels = [
        GlinetVpnTunnel(name="Bonkcloud", type="wireguard", enabled=True, up=True,
                         from_summary="1 connection type", from_detail="lan",
                         to_summary="3 addresses",
                         to_detail="192.168.2.0/24\n172.16.42.0/24\n192.168.50.0/24",
                         via_summary="Bonkcloud / WireGuard-Server-GLINet", killswitch=True),
        GlinetVpnTunnel(name="Guest Wifi", type="wireguard", enabled=True, up=True,
                         from_summary="All clients", to_summary="All targets",
                         via_summary="Bonkcloud / Privacy-VPN-Client-1", killswitch=True),
        GlinetVpnTunnel(name="Backup Tunnel", type="openvpn", enabled=False, up=False),
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, vpn_tunnels=tunnels)
    qtbot.waitUntil(lambda: dashboard._vpn_table.rowCount() == 3, timeout=2000)

    assert dashboard._vpn_table.item(0, 0).text() == "Bonkcloud (Kill Switch)"
    assert dashboard._vpn_table.item(0, 1).text() == "wireguard"
    assert dashboard._vpn_table.item(0, 2).text() == "1 connection type"
    assert dashboard._vpn_table.item(0, 2).toolTip() == "lan"
    assert dashboard._vpn_table.item(0, 3).text() == "3 addresses"
    assert dashboard._vpn_table.item(0, 3).toolTip() == "192.168.2.0/24\n172.16.42.0/24\n192.168.50.0/24"
    assert dashboard._vpn_table.item(0, 4).text() == "Bonkcloud / WireGuard-Server-GLINet"
    # "All clients"/"All targets" already say everything -- no tooltip.
    assert dashboard._vpn_table.item(1, 2).toolTip() == ""
    assert dashboard._vpn_table.item(0, 5).text() == "Up"
    assert dashboard._vpn_table.item(2, 0).text() == "Backup Tunnel"
    assert dashboard._vpn_table.item(2, 5).text() == "Disabled"


def test_vpn_tab_shows_enabled_but_not_connected(qtbot, monkeypatch):
    tunnels = [GlinetVpnTunnel(name="Flaky", type="wireguard", enabled=True, up=False)]
    dashboard = _make_dashboard(qtbot, monkeypatch, vpn_tunnels=tunnels)
    qtbot.waitUntil(lambda: dashboard._vpn_table.rowCount() == 1, timeout=2000)

    assert dashboard._vpn_table.item(0, 5).text() == "Enabled"


def test_clients_tab_populates_from_list_clients(qtbot, monkeypatch):
    clients = [GlinetClientInfo(mac="aa:bb", name="phone", ip="192.168.8.10", online=True)]
    dashboard = _make_dashboard(qtbot, monkeypatch, clients=clients)
    qtbot.waitUntil(lambda: dashboard._clients_table.rowCount() == 1, timeout=2000)

    assert dashboard._clients_table.item(0, 0).text() == "phone"
    assert dashboard._clients_table.item(0, 3).text() == "Yes"


def test_wifi_tab_populates_from_get_wifi_config(qtbot, monkeypatch):
    radios = [
        GlinetWifiRadio(device="radio0", iface_name="default_radio0", band="2G",
                          ssid="MyWifi", enabled=True)
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: dashboard._wifi_table.rowCount() == 1, timeout=2000)

    assert dashboard._wifi_table.item(0, 0).text() == "Main"
    assert dashboard._wifi_table.item(0, 1).text() == "radio0"
    assert dashboard._wifi_table.item(0, 2).text() == "2.4G"
    assert dashboard._wifi_table.item(0, 3).text() == "MyWifi"
    assert dashboard._wifi_table.item(0, 4).text() == "Enabled"


def test_wifi_tab_lists_main_networks_before_guest(qtbot, monkeypatch):
    # Regression test: main and guest networks otherwise interleave in
    # whatever order the router happens to report them -- list all Main
    # networks first, then all Guest networks.
    radios = [
        GlinetWifiRadio(device="radio0", iface_name="guest2g", band="2G",
                          ssid="Guest-2G", enabled=True, guest=True),
        GlinetWifiRadio(device="radio0", iface_name="wifi2g", band="2G",
                          ssid="Main-2G", enabled=True, guest=False),
        GlinetWifiRadio(device="radio1", iface_name="wifi5g", band="5G",
                          ssid="Main-5G", enabled=True, guest=False),
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: dashboard._wifi_table.rowCount() == 3, timeout=2000)

    ssids = [dashboard._wifi_table.item(row, 3).text() for row in range(3)]
    assert ssids == ["Main-2G", "Main-5G", "Guest-2G"]


def test_edit_wifi_network_opens_dialog_and_saves(qtbot, monkeypatch):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    radios = [
        GlinetWifiRadio(device="radio0", iface_name="default_radio0", band="2.4G",
                          ssid="MyWifi", enabled=True)
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: dashboard._wifi_table.rowCount() == 1, timeout=2000)
    dashboard._wifi_table.selectRow(0)

    calls = []
    monkeypatch.setattr(
        module.glinet_client,
        "set_wifi_config",
        lambda host, password, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        module._WifiNetworkEditDialog, "exec",
        lambda self: module.QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(module._WifiNetworkEditDialog, "ssid", lambda self: "NewName")
    monkeypatch.setattr(module._WifiNetworkEditDialog, "password", lambda self: "newpass")

    dashboard._on_edit_wifi_clicked()

    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)
    assert calls == [
        {"device": "radio0", "iface_name": "default_radio0", "ssid": "NewName",
         "key": "newpass", "enabled": True}
    ]


def test_edit_wifi_network_does_nothing_without_a_selected_row(qtbot, monkeypatch):
    radios = [
        GlinetWifiRadio(device="radio0", iface_name="default_radio0", band="2.4G",
                          ssid="MyWifi", enabled=True)
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: dashboard._wifi_table.rowCount() == 1, timeout=2000)
    dashboard._wifi_table.clearSelection()

    dashboard._on_edit_wifi_clicked()  # should not raise


def test_reboot_confirms_before_calling_reboot(qtbot, monkeypatch):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    dashboard = _make_dashboard(qtbot, monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    reboot_calls = []
    monkeypatch.setattr(
        module.glinet_client, "reboot", lambda host, password: reboot_calls.append(host)
    )

    dashboard._on_reboot_clicked()

    qtbot.waitUntil(lambda: len(reboot_calls) == 1, timeout=2000)


def test_reboot_does_nothing_when_confirmation_declined(qtbot, monkeypatch):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    dashboard = _make_dashboard(qtbot, monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    reboot_calls = []
    monkeypatch.setattr(
        module.glinet_client, "reboot", lambda host, password: reboot_calls.append(host)
    )

    dashboard._on_reboot_clicked()

    assert reboot_calls == []


def test_fetch_error_surfaces_via_message_box_not_a_crash(qtbot, monkeypatch):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    monkeypatch.setattr(module.glinet_client, "GlInet", object())

    def raise_error(host, password):
        raise module.glinet_client.GlinetApiError("connection refused")

    monkeypatch.setattr(module.glinet_client, "get_overview", raise_error)
    monkeypatch.setattr(module.glinet_client, "list_clients", lambda host, password: [])
    monkeypatch.setattr(module.glinet_client, "get_wifi_config", lambda host, password: [])
    monkeypatch.setattr(module.glinet_client, "list_vpn_tunnels", lambda host, password: [])

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a) or QMessageBox.StandardButton.Ok
    )

    dashboard = GlinetDashboardWidget(HOST, "secret")
    qtbot.addWidget(dashboard)

    qtbot.waitUntil(lambda: len(warnings) == 1, timeout=2000)

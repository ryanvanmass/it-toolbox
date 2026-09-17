from PySide6.QtWidgets import QGroupBox, QLabel, QMessageBox

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
                         from_summary="1 connection type", to_summary="3 addresses",
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
    assert dashboard._vpn_table.item(0, 3).text() == "3 addresses"
    assert dashboard._vpn_table.item(0, 4).text() == "Bonkcloud / WireGuard-Server-GLINet"
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


def _wifi_tab_loaded(dashboard) -> bool:
    """True once the WiFi tab's async load has actually replaced the
    initial "Loading…" QLabel placeholder with real content.
    count() > 1 alone is NOT a safe wait condition here -- the
    placeholder state (QLabel + trailing stretch) already satisfies it,
    and for some radio counts even matches the final count exactly,
    letting a test read stale placeholder content as if it were loaded
    (found the hard way: a device_box.title() AttributeError against
    what turned out to still be the QLabel).
    """
    first_item = dashboard._wifi_layout.itemAt(0)
    return first_item is not None and isinstance(first_item.widget(), QGroupBox)


def test_wifi_tab_builds_a_group_per_radio(qtbot, monkeypatch):
    radios = [
        GlinetWifiRadio(device="radio0", iface_name="default_radio0", band="2.4G",
                          ssid="MyWifi", enabled=True)
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: _wifi_tab_loaded(dashboard), timeout=2000)

    assert dashboard._wifi_layout.count() == 2  # one QGroupBox + the trailing stretch


def test_wifi_tab_groups_main_and_guest_into_separate_boxes(qtbot, monkeypatch):
    # Regression test: main and guest networks otherwise render as flat,
    # unlabeled-as-a-set sibling boxes -- group all Main networks
    # together and all Guest networks together instead, Main first,
    # rather than by physical radio.
    radios = [
        GlinetWifiRadio(device="radio0", iface_name="wifi2g", band="2G",
                          ssid="MyWifi", enabled=True, guest=False),
        GlinetWifiRadio(device="radio0", iface_name="guest2g", band="2G",
                          ssid="MyWifi-Guest", enabled=True, guest=True),
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: _wifi_tab_loaded(dashboard), timeout=2000)

    # Two top-level boxes (Main, Guest) + the trailing stretch.
    assert dashboard._wifi_layout.count() == 3
    titles = [
        dashboard._wifi_layout.itemAt(i).widget().title()
        for i in range(dashboard._wifi_layout.count())
        if dashboard._wifi_layout.itemAt(i).widget() is not None
    ]
    assert titles == ["Main", "Guest"]

    main_box = dashboard._wifi_layout.itemAt(0).widget()
    assert main_box.layout().itemAt(0).widget().title() == "radio0 (2.4G)"


def test_wifi_tab_groups_all_bands_of_the_same_network_type_together(qtbot, monkeypatch):
    # The main request this shape exists for: 2.4G and 5G Main networks
    # (different physical radios) should appear one after another under
    # a single "Main" box, not split into separate per-radio boxes.
    radios = [
        GlinetWifiRadio(device="radio0", iface_name="wifi2g", band="2G",
                          ssid="MyWifi", enabled=True, guest=False),
        GlinetWifiRadio(device="radio1", iface_name="wifi5g", band="5G",
                          ssid="MyWifi", enabled=True, guest=False),
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: _wifi_tab_loaded(dashboard), timeout=2000)

    # Only Main networks exist here -- one top-level box + the stretch.
    assert dashboard._wifi_layout.count() == 2
    main_box = dashboard._wifi_layout.itemAt(0).widget()
    assert main_box.title() == "Main"

    nested_titles = [
        main_box.layout().itemAt(i).widget().title()
        for i in range(main_box.layout().count())
    ]
    assert nested_titles == ["radio0 (2.4G)", "radio1 (5G)"]


def test_wifi_save_calls_set_wifi_config_with_expected_params(qtbot, monkeypatch):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    radios = [
        GlinetWifiRadio(device="radio0", iface_name="default_radio0", band="2.4G",
                          ssid="MyWifi", enabled=True)
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: _wifi_tab_loaded(dashboard), timeout=2000)

    calls = []
    monkeypatch.setattr(
        module.glinet_client,
        "set_wifi_config",
        lambda host, password, **kwargs: calls.append(kwargs),
    )

    dashboard._save_wifi_config(radios[0], "NewName", "newpass")

    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)
    assert calls == [
        {"device": "radio0", "iface_name": "default_radio0", "ssid": "NewName",
         "key": "newpass", "enabled": True}
    ]


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

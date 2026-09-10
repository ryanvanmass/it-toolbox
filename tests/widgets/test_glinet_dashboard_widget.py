from PySide6.QtWidgets import QLabel, QMessageBox

from it_toolbox.modules.connection_manager.models import (
    GlinetClientInfo,
    GlinetHost,
    GlinetOverview,
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
    wg_client_up=True,
    wg_server_up=False,
    ovpn_client_up=False,
    ovpn_server_up=True,
)


def _make_dashboard(qtbot, monkeypatch, glinet_available=True, overview=OVERVIEW, clients=(),
                     wifi_radios=()):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    monkeypatch.setattr(module.glinet_client, "GlInet", object() if glinet_available else None)
    monkeypatch.setattr(module.glinet_client, "get_overview", lambda host, password: overview)
    monkeypatch.setattr(module.glinet_client, "list_clients", lambda host, password: list(clients))
    monkeypatch.setattr(
        module.glinet_client, "get_wifi_config", lambda host, password: list(wifi_radios)
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


def test_vpn_tab_populates_from_overview(qtbot, monkeypatch):
    dashboard = _make_dashboard(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: dashboard._vpn_fields["wg_client"].text() == "Up", timeout=2000)

    assert dashboard._vpn_fields["wg_server"].text() == "Down"
    assert dashboard._vpn_fields["ovpn_client"].text() == "Down"
    assert dashboard._vpn_fields["ovpn_server"].text() == "Up"


def test_clients_tab_populates_from_list_clients(qtbot, monkeypatch):
    clients = [GlinetClientInfo(mac="aa:bb", name="phone", ip="192.168.8.10", online=True)]
    dashboard = _make_dashboard(qtbot, monkeypatch, clients=clients)
    qtbot.waitUntil(lambda: dashboard._clients_table.rowCount() == 1, timeout=2000)

    assert dashboard._clients_table.item(0, 0).text() == "phone"
    assert dashboard._clients_table.item(0, 3).text() == "Yes"


def test_wifi_tab_builds_a_group_per_radio(qtbot, monkeypatch):
    radios = [
        GlinetWifiRadio(device="radio0", iface_name="default_radio0", band="2.4G",
                          ssid="MyWifi", enabled=True)
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: dashboard._wifi_layout.count() > 1, timeout=2000)

    assert dashboard._wifi_layout.count() == 2  # one QGroupBox + the trailing stretch


def test_wifi_save_calls_set_wifi_config_with_expected_params(qtbot, monkeypatch):
    import it_toolbox.widgets.glinet_dashboard_widget as module

    radios = [
        GlinetWifiRadio(device="radio0", iface_name="default_radio0", band="2.4G",
                          ssid="MyWifi", enabled=True)
    ]
    dashboard = _make_dashboard(qtbot, monkeypatch, wifi_radios=radios)
    qtbot.waitUntil(lambda: dashboard._wifi_layout.count() > 1, timeout=2000)

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

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a) or QMessageBox.StandardButton.Ok
    )

    dashboard = GlinetDashboardWidget(HOST, "secret")
    qtbot.addWidget(dashboard)

    qtbot.waitUntil(lambda: len(warnings) == 1, timeout=2000)

import json

import pytest

from it_toolbox.core import settings
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.modules.connection_manager.models import GlinetOverview
from it_toolbox.modules.infrastructure import glinet, products
from it_toolbox.modules.infrastructure.glinet import GlinetProduct
from it_toolbox.modules.infrastructure.ui import main_view
from it_toolbox.modules.infrastructure.ui.main_view import InfrastructureView
from it_toolbox.widgets.glinet_dashboard_widget import GlinetDashboardWidget

LEGACY = {
    "name": "Travel Router",
    "url": "https://192.168.8.1/rpc",
    "username": "root",
    "verify_ssl": False,
    "password_encrypted": "ZW5jOnBhc3M=",  # base64 of b"enc:pass"
}


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    return d


@pytest.fixture
def view(qtbot, monkeypatch):
    monkeypatch.setattr(main_view, "PRODUCT_CLASSES", [GlinetProduct])
    monkeypatch.setattr(
        settings, "decrypt_infrastructure_secret", lambda b, passphrase=None: b.decode().removeprefix("enc:")
    )

    def make():
        v = InfrastructureView()
        qtbot.addWidget(v)
        return v

    return make


def test_glinet_is_a_shipped_product():
    assert GlinetProduct in products.PRODUCT_CLASSES
    assert GlinetProduct.token_id_label == "Username:"


def test_connection_manager_era_hosts_are_migrated_once(data_dir):
    already = InfrastructureHost(name="Office", url="https://10.0.0.1:443", token_id="admin").to_dict()
    (data_dir / "glinet_hosts.json").write_text(json.dumps([LEGACY, already]))

    glinet.migrate_legacy_hosts()

    first, second = json.loads((data_dir / "glinet_hosts.json").read_text())
    assert first == {
        "name": "Travel Router",
        "url": "https://192.168.8.1",
        "token_id": "root",
        "secret_encrypted": "ZW5jOnBhc3M=",
        "verify_ssl": False,
        "fingerprint": None,
        "ssh_username": "root",
    }
    assert second == already
    host = InfrastructureHost.from_dict(first)
    assert host.secret_encrypted == b"enc:pass"

    before = (data_dir / "glinet_hosts.json").read_text()
    glinet.migrate_legacy_hosts()
    assert (data_dir / "glinet_hosts.json").read_text() == before


def test_migration_without_a_hosts_file_is_a_no_op(data_dir):
    glinet.migrate_legacy_hosts()
    assert not (data_dir / "glinet_hosts.json").exists()


def test_migrated_host_shows_under_the_glinet_root(view, data_dir):
    (data_dir / "glinet_hosts.json").write_text(json.dumps([LEGACY]))
    v = view()
    root = v.sidebar_tree.topLevelItem(0)
    assert root.text(0) == "GL.iNet"
    host_item = root.child(1)
    assert host_item.text(0) == "Travel Router"
    assert host_item.childCount() == 0  # a router is just its dashboard


def test_dashboard_gets_the_rpc_url_and_stored_password(view, data_dir, qtbot, monkeypatch):
    (data_dir / "glinet_hosts.json").write_text(json.dumps([LEGACY]))
    monkeypatch.setattr(glinet.glinet_client, "GlInet", None)  # dashboard shows "not installed", no calls
    v = view()
    host_item = v.sidebar_tree.topLevelItem(0).child(1)
    v._on_item_double_clicked(host_item, 0)
    dashboard = v.tabs.currentWidget()
    assert isinstance(dashboard, GlinetDashboardWidget)
    assert dashboard._host.url == "https://192.168.8.1/rpc"
    assert dashboard._host.username == "root"
    assert dashboard._password == "pass"
    assert v.tabs.tabText(v.tabs.currentIndex()) == "GL.iNet: Travel Router"
    assert v.try_close_tab(dashboard) is True


def test_to_glinet_host_never_carries_the_secret():
    host = InfrastructureHost(name="r", url="https://192.168.8.1:443/", token_id="", secret_encrypted=b"x")
    glinet_host = glinet.to_glinet_host(host)
    assert glinet_host.url == "https://192.168.8.1:443/rpc"
    assert glinet_host.username == "root"
    assert glinet_host.password_encrypted is None


def test_test_connection_summary(monkeypatch):
    seen = {}

    def overview(host, password):
        seen["args"] = (host.url, password)
        return GlinetOverview(
            uptime="3h 2m", lan_ip="192.168.8.1", memory_used_pct=None, cpu_temp=None,
            wireless_client_count=0, cable_client_count=0, wifi_radios=(),
        )

    monkeypatch.setattr(glinet.glinet_client, "get_overview", overview)
    product = GlinetProduct.__new__(GlinetProduct)
    host = InfrastructureHost(name="r", url="https://192.168.8.1:443", token_id="root")
    assert product.test_connection(host, "pw") == "GL.iNet router, LAN 192.168.8.1, up 3h 2m"
    assert seen["args"] == ("https://192.168.8.1:443/rpc", "pw")

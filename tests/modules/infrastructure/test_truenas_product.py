import pytest
from truenas_fake import API_KEY, FakeTrueNas

from it_toolbox.core import settings
from it_toolbox.modules.infrastructure import products, truenas
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.modules.infrastructure.truenas import TrueNasProduct
from it_toolbox.modules.infrastructure.ui import main_view
from it_toolbox.modules.infrastructure.ui.main_view import NODE_ROLE, InfrastructureView
from it_toolbox.widgets.truenas_dashboard_widget import AREAS, TrueNasDashboardWidget


@pytest.fixture
def nas(tmp_path):
    with FakeTrueNas(tmp_path) as server:
        yield server


@pytest.fixture
def view(qtbot, nas, tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: data)
    monkeypatch.setattr(main_view, "PRODUCT_CLASSES", [TrueNasProduct])
    monkeypatch.setattr(settings, "decrypt_infrastructure_secret", lambda b, passphrase=None: b.decode())
    host = InfrastructureHost(name="nas01", url=nas.url, secret_encrypted=API_KEY.encode(), fingerprint=nas.fingerprint)
    settings.save_infrastructure_hosts("truenas", [host.to_dict()])
    v = InfrastructureView()
    qtbot.addWidget(v)
    yield v
    v.close_all_sessions()


def host_item(view):
    return view.sidebar_tree.topLevelItem(0).child(1)


def test_truenas_is_a_shipped_product():
    assert TrueNasProduct in products.PRODUCT_CLASSES
    assert TrueNasProduct.token_id_label is None


def test_host_lists_the_dashboard_areas(view):
    item = host_item(view)
    assert [item.child(i).text(0) for i in range(item.childCount())] == list(AREAS)
    assert item.child(3).data(0, NODE_ROLE) == "Data protection"


def test_expanding_a_host_colours_its_health_dot(view, qtbot):
    item = host_item(view)
    item.setExpanded(True)
    qtbot.waitUntil(lambda: "Warnings" in host_item(view).toolTip(0), timeout=5000)


def test_double_clicking_an_area_opens_the_dashboard_there(view, qtbot):
    item = host_item(view)
    view._on_item_double_clicked(item.child(5), 0)  # Apps
    dashboard = view.tabs.currentWidget()
    assert isinstance(dashboard, TrueNasDashboardWidget)
    assert view.tabs.tabText(view.tabs.currentIndex()) == "TrueNAS: nas01"
    assert dashboard.tabs.tabText(dashboard.tabs.currentIndex()) == "Apps"
    qtbot.waitUntil(lambda: dashboard.apps_table.rowCount() == 1, timeout=5000)

    view._on_item_double_clicked(host_item(view).child(6), 0)  # VMs, same tab reused
    assert view.tabs.count() == 1
    assert dashboard.tabs.tabText(dashboard.tabs.currentIndex()) == "VMs"


def test_test_connection(nas, view):
    product = view.products[0]
    host = InfrastructureHost(name="n", url=nas.url, fingerprint=nas.fingerprint)
    assert product.test_connection(host, API_KEY) == "TrueNAS 25.04.2.1, nas01"


def test_health_icon_colours():
    assert not truenas.health_icon("red").isNull()

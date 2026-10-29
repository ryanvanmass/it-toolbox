import pytest
from PySide6.QtWidgets import QMenu

from it_toolbox.core import async_utils, settings
from it_toolbox.core import proxmox_client as pc
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.core.proxmox_models import (
    LXC,
    QEMU,
    ClusterResources,
    GuestDetails,
    GuestInterface,
    NodeStatus,
    ProxmoxGuest,
    ProxmoxNode,
    ProxmoxStorage,
    ProxmoxTask,
    SdnOverview,
    SdnSubnet,
    SdnVnet,
    SdnZone,
    SdnZoneStatus,
)
from it_toolbox.modules.infrastructure import proxmox
from it_toolbox.modules.infrastructure.proxmox import GUEST, SDN, ProxmoxProduct
from it_toolbox.modules.infrastructure.ui import main_view
from it_toolbox.modules.infrastructure.ui.main_view import NODE_ROLE, InfrastructureView
from it_toolbox.widgets import proxmox_dashboard_widget as dw

HOST = InfrastructureHost(
    name="pve1", url="https://pve1.lan:8006", token_id="root@pam!tb", secret_encrypted=b"enc:s", fingerprint="AA"
)
DC01 = ProxmoxGuest(vmid=100, name="dc01", node="pve1", type=QEMU, status="running", maxcpu=4, maxmem=4 << 30)
WEB = ProxmoxGuest(vmid=101, name="web", node="pve1", type=QEMU, status="stopped")
PIHOLE = ProxmoxGuest(vmid=200, name="pihole", node="pve1", type=LXC, status="running")
TMPL = ProxmoxGuest(vmid=9000, name="alma10-tmpl", node="pve1", type=QEMU, status="stopped", template=True)
NODE = ProxmoxNode(name="pve1", status="online", maxcpu=8)
RESOURCES = ClusterResources(
    nodes=(NODE,),
    guests=(DC01, WEB, PIHOLE, TMPL),
    storages=(ProxmoxStorage(storage="local", node="pve1", plugin="dir", status="available", used=1, total=4,
                             content=("iso",)),),
    sdn_zones=("lab",),
)
STATUS = NodeStatus(node="pve1", pve_version="pve-manager/9.0.3", kernel="6.14", cpu_model="Xeon", cpus=8,
                    cpu=0.25, loadavg=("0.1", "0.2", "0.3"), mem_used=1 << 30, mem_total=4 << 30, swap_used=0,
                    swap_total=0, rootfs_used=1, rootfs_total=2, uptime=7200)


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    monkeypatch.setattr(settings, "decrypt_infrastructure_secret", lambda b, passphrase=None: "s")
    settings.save_infrastructure_hosts("proxmox", [HOST.to_dict()])
    return d


@pytest.fixture(autouse=True)
def only_proxmox(monkeypatch):
    monkeypatch.setattr(main_view, "PRODUCT_CLASSES", [ProxmoxProduct])


@pytest.fixture(autouse=True)
def synchronous(monkeypatch):
    def run(fn, on_result=None, on_error=None):
        try:
            result = fn()
        except Exception as error:  # noqa: BLE001 -- mirrors run_in_background
            if on_error is not None:
                on_error(error)
            return
        if on_result is not None:
            on_result(result)

    monkeypatch.setattr(async_utils, "run_in_background", run)


@pytest.fixture
def api(monkeypatch):
    calls = []

    def resources(host, secret):
        calls.append(("resources", secret))
        return RESOURCES

    monkeypatch.setattr(pc, "list_resources", resources)
    monkeypatch.setattr(pc, "get_node_status", lambda host, secret, node: STATUS)
    monkeypatch.setattr(pc, "list_tasks", lambda host, secret: [
        ProxmoxTask(upid="U1", node="pve1", type="qmstart", id="100", user="root@pam", starttime=10, endtime=12,
                    status="OK")])
    monkeypatch.setattr(pc, "get_task_log", lambda host, secret, node, upid: ["starting", "TASK OK"])
    return calls


def _view(qtbot):
    view = InfrastructureView()
    qtbot.addWidget(view)
    return view


def _host_item(view):
    return view._tree.topLevelItem(0).child(1)


def _children(item):
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_proxmox_is_a_shipped_product():
    from it_toolbox.modules.infrastructure.products import PRODUCT_CLASSES

    assert ProxmoxProduct in PRODUCT_CLASSES


def test_expanding_a_single_node_host_lists_guests_templates_and_sdn(qtbot, api):
    view = _view(qtbot)
    item = _host_item(view)
    assert _children(item) == ["Expand to load guests"]

    item.setExpanded(True)

    assert _children(item) == ["● 100 dc01", "○ 101 web", "● 200 pihole (CT)", "Templates", "SDN"]
    assert _children(item.child(3)) == ["9000 alma10-tmpl"]
    assert item.child(0).data(0, NODE_ROLE) == (GUEST, DC01)
    assert item.child(4).data(0, NODE_ROLE) == (SDN, None)
    assert item.child(4).toolTip(0) == "lab"

    item.setExpanded(False)
    item.setExpanded(True)
    assert api == [("resources", "s")]  # loaded once


def test_a_clustered_host_gets_a_node_level(qtbot, monkeypatch):
    other = ProxmoxNode(name="pve2", status="offline")
    moved = ProxmoxGuest(vmid=300, name="db", node="pve2", type=QEMU, status="stopped")
    monkeypatch.setattr(pc, "list_resources", lambda h, s: ClusterResources(nodes=(NODE, other),
                                                                            guests=(DC01, moved)))
    view = _view(qtbot)
    item = _host_item(view)
    item.setExpanded(True)
    assert _children(item) == ["pve1 (online)", "pve2 (offline)", "SDN"]
    assert _children(item.child(1)) == ["○ 300 db"]


def test_a_failed_load_shows_the_error_under_the_host(qtbot, monkeypatch):
    def fail(host, secret):
        raise pc.ProxmoxApiError("Proxmox rejected the API token")

    monkeypatch.setattr(pc, "list_resources", fail)
    view = _view(qtbot)
    item = _host_item(view)
    item.setExpanded(True)
    assert _children(item) == ["Couldn't connect: Proxmox rejected the API token"]


def test_guest_menu_and_double_click_open_a_summary_tab(qtbot, api, monkeypatch):
    monkeypatch.setattr(pc, "get_guest_details", lambda host, secret, guest: GuestDetails(
        guest=guest, config={"vga": "qxl", "agent": "1", "serial0": "socket"}, agent_running=True,
        interfaces=(GuestInterface(name="eth0", mac="aa", addresses=("10.0.0.5/24",)),)))
    view = _view(qtbot)
    item = _host_item(view)
    item.setExpanded(True)
    product = view.products[0]

    menu = QMenu()
    product.add_item_actions(menu, item.child(0), HOST, (GUEST, DC01))
    assert [a.text() for a in menu.actions()] == ["Show Summary", "Open Console in Browser", "Open in Web UI"]
    menu = QMenu()
    product.add_item_actions(menu, item.child(3).child(0), HOST, (GUEST, TMPL))
    assert [a.text() for a in menu.actions()] == ["Show Summary", "Open in Web UI"]

    view._on_item_double_clicked(item.child(0), 0)
    assert view.tabs.tabText(0) == "Proxmox: dc01"
    widget = view.tabs.widget(0)
    assert isinstance(widget, dw.ProxmoxGuestWidget)
    labels = {widget._form.itemAt(i, widget._form.ItemRole.LabelRole).widget().text():
              widget._form.itemAt(i, widget._form.ItemRole.FieldRole).widget().text()
              for i in range(widget._form.rowCount())}
    assert labels["IPv4:"] == "10.0.0.5"
    assert labels["Guest agent:"] == "running"
    assert labels["Display:"] == "qxl"
    assert labels["Serial console:"] == "serial0: socket"


def test_dashboard_shows_nodes_storage_guests_and_tasks(qtbot, api):
    widget = dw.ProxmoxDashboardWidget(HOST, "s")
    qtbot.addWidget(widget)

    assert widget._nodes_box.count() == 1
    assert widget._storage_table.rowCount() == 1
    assert widget._storage_table.item(0, 4).text() == "1 B of 4 B (25%)"
    assert widget._guest_table.rowCount() == 4
    names = {widget._guest_table.item(r, 1).text(): widget._guest_table.item(r, 2).text()
             for r in range(4)}
    assert names == {"dc01": "VM", "web": "VM", "pihole": "CT", "alma10-tmpl": "template"}

    widget._tabs.setCurrentWidget(widget._tasks_tab)
    assert widget._task_table.rowCount() == 1
    widget._task_table.selectRow(0)
    assert widget._task_log.toPlainText() == "starting\nTASK OK"
    widget.close_session()
    assert not widget._timer.isActive()


def test_dashboard_sdn_tab_marks_pending_changes(qtbot, api, monkeypatch):
    sdn = SdnOverview(
        zones=(SdnZone(zone="lab", type="vlan", bridge="vmbr0"),),
        vnets=(SdnVnet(vnet="vnet10", zone="lab", tag=10, state="changed"),),
        subnets=(SdnSubnet(subnet="10.10.0.0/24", vnet="vnet10", gateway="10.10.0.1"),),
        zone_status=(SdnZoneStatus(zone="lab", node="pve1", status="available"),),
        ipams=({"ipam": "pve", "type": "pve"},),
    )
    monkeypatch.setattr(pc, "get_sdn", lambda host, secret, nodes: sdn)
    monkeypatch.setattr(pc, "guests_by_bridge", lambda host, secret, guests: {"vnet10": ["100 dc01"]})
    view = _view(qtbot)
    item = _host_item(view)
    item.setExpanded(True)

    view._on_item_double_clicked(item.child(4), 0)

    dashboard = view.tabs.widget(0)
    assert view.tabs.tabText(0) == "Proxmox: pve1"
    assert dashboard._tabs.currentWidget() is dashboard._sdn_tab
    assert not dashboard._sdn_pending.isHidden()
    assert dashboard._zone_table.item(0, 3).text() == "pve1: available"
    assert dashboard._vnet_table.item(0, 4).text() == "100 dc01"
    assert dashboard._vnet_table.item(0, 5).text() == "changed (pending)"
    assert dashboard._subnet_table.item(0, 2).text() == "10.10.0.1"
    assert "IPAMs: pve (pve)" in dashboard._plugins.text()


@pytest.mark.parametrize(
    "value, expected",
    [(0, "0 B"), (1536, "1.5 KiB"), (3 << 30, "3.0 GiB")],
)
def test_format_bytes(value, expected):
    assert dw.format_bytes(value) == expected


@pytest.mark.parametrize("seconds, expected", [(0, "—"), (59 * 60, "59m"), (7200, "2h 0m"), (90000, "1d 1h")])
def test_format_uptime(seconds, expected):
    assert dw.format_uptime(seconds) == expected


def test_status_dots_cover_paused():
    assert proxmox.STATUS_DOTS["paused"] == "◐"

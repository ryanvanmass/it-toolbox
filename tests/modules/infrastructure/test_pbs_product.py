import pytest
from PySide6.QtWidgets import QMenu

from it_toolbox.core import async_utils, pbs_client, settings
from it_toolbox.core.pbs_models import BackupGroup, DatastoreUsage, NodeStatus, PbsJob, PbsTask, Snapshot
from it_toolbox.modules.infrastructure import pbs_product
from it_toolbox.modules.infrastructure.hosts import InfrastructureHost
from it_toolbox.modules.infrastructure.pbs_product import (
    DatastoreNode,
    GroupNode,
    NamespaceNode,
    PbsProduct,
    datastore_web_url,
)
from it_toolbox.modules.infrastructure.products import PRODUCT_CLASSES
from it_toolbox.modules.infrastructure.ui import main_view
from it_toolbox.modules.infrastructure.ui.main_view import NODE_ROLE, InfrastructureView
from it_toolbox.widgets import pbs_dashboard_widget
from it_toolbox.widgets.pbs_dashboard_widget import (
    PbsDashboardWidget,
    estimated_full_label,
    format_age,
    format_bytes,
)
from it_toolbox.widgets.pbs_datastore_widget import PbsDatastoreWidget, snapshot_matches

PBS = InfrastructureHost(
    name="pbs1",
    url="https://pbs1.lan:8007",
    token_id="backup@pbs!toolbox",
    secret_encrypted=b"enc:s3cret",
    fingerprint="AA:BB",
)

LOCAL = DatastoreUsage(store="local", used=900, total=1000, comment="Main")
OFFSITE = DatastoreUsage(store="offsite", used=10, total=1000, backend_type="s3")
UNMOUNTED = DatastoreUsage(store="usb", mount_status="notmounted")
GROUPS = [
    BackupGroup("vm", "101", backup_count=3, last_backup=1000, comment="dc01"),
    BackupGroup("ct", "105", backup_count=1, last_backup=2000),
]
SNAPSHOTS = [
    Snapshot("vm", "101", 300, size=2048, protected=True, verify_state="ok", comment="before upgrade"),
    Snapshot("vm", "101", 200, size=1024, verify_state="failed"),
    Snapshot("ct", "105", 250, encrypted=True, owner="root@pam"),
]


class FakeApi:
    """Stands in for pbs_client, recording calls."""

    def __init__(self):
        self.calls = []
        self.namespaces = {"local": [""], "offsite": ["", "site-a"]}
        self.fail_groups_for: set[str] = set()

    def install(self, monkeypatch):
        for name in (
            "list_datastores",
            "list_namespaces",
            "list_groups",
            "list_snapshots",
            "get_node_status",
            "list_jobs",
            "list_tasks",
            "get_task_log",
        ):
            monkeypatch.setattr(pbs_client, name, getattr(self, name))

    def list_datastores(self, host, secret):
        self.calls.append(("datastores", secret))
        return [LOCAL, OFFSITE, UNMOUNTED]

    def list_namespaces(self, host, secret, store):
        return self.namespaces[store]

    def list_groups(self, host, secret, store, ns=""):
        if store in self.fail_groups_for:
            raise pbs_client.PbsApiError("permission check failed", 403)
        return GROUPS if ns == "" else GROUPS[:1]

    def list_snapshots(self, host, secret, store, ns="", group=None):
        self.calls.append(("snapshots", store, ns))
        return SNAPSHOTS

    def get_node_status(self, host, secret):
        return NodeStatus(version="4.2.8", cpu=0.5, cpus=4, memory_used=1, memory_total=2, uptime=90061, subscription="active")

    def list_jobs(self, host, secret):
        return [
            PbsJob("gc", "local", "local", schedule="daily", last_run_state="OK"),
            PbsJob("verify", "v1", "local", schedule="sat", last_run_state="verification failed"),
        ]

    def list_tasks(self, host, secret, limit=50, errors_only=False):
        return [
            PbsTask("UPID:ok", "backup", "vm/101", starttime=30, endtime=40, status="OK"),
            PbsTask("UPID:bad", "verify", "local", starttime=10, endtime=20, status="verification failed"),
            PbsTask("UPID:run", "garbage_collection", "local", starttime=50),
        ]

    def get_task_log(self, host, secret, upid, limit=500):
        return ["line 1"]


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    settings.save_infrastructure_hosts("pbs", [PBS.to_dict()])
    return d


@pytest.fixture(autouse=True)
def fake_crypto(monkeypatch):
    monkeypatch.setattr(
        settings, "decrypt_infrastructure_secret", lambda b, passphrase=None: b.decode().removeprefix("enc:")
    )


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
    fake = FakeApi()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def view(qtbot, monkeypatch):
    monkeypatch.setattr(main_view, "PRODUCT_CLASSES", [PbsProduct])
    view = InfrastructureView()
    qtbot.addWidget(view)
    return view


def _host_item(view):
    return view._tree.topLevelItem(0).child(1)


def _children(item):
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_pbs_is_a_shipped_product():
    assert PbsProduct in PRODUCT_CLASSES
    assert PbsProduct.id == "pbs" and PbsProduct.default_port == 8007


def test_host_starts_with_a_placeholder(view):
    assert view._tree.topLevelItem(0).text(0) == "PBS"
    assert _children(_host_item(view)) == ["Expand to load"]


def test_expanding_loads_datastores_namespaces_and_groups(view, api):
    item = _host_item(view)
    item.setExpanded(True)

    assert _children(item) == ["⚠ local (90%)", "offsite (1%)", "usb"]
    local, offsite, usb = (item.child(i) for i in range(3))
    assert local.data(0, NODE_ROLE) == DatastoreNode("local")
    assert "Main" in local.toolTip(0)
    # One namespace: groups sit straight under the datastore.
    assert [t.split("  ·  ")[0] for t in _children(local)] == ["vm/101", "ct/105"]
    assert "dc01" in local.child(0).text(0)
    assert local.child(0).data(0, NODE_ROLE) == GroupNode("local", "", "vm/101")
    # Several namespaces: a level for each.
    assert _children(offsite) == ["(root)", "site-a"]
    assert offsite.child(1).data(0, NODE_ROLE) == NamespaceNode("offsite", "site-a")
    assert offsite.child(1).childCount() == 1
    # An unmounted removable datastore is listed but not read.
    assert usb.childCount() == 0 and "not mounted" in usb.toolTip(0)
    assert api.calls[0] == ("datastores", "s3cret")


def test_expanding_again_does_not_reload(view, api):
    item = _host_item(view)
    item.setExpanded(True)
    item.setExpanded(False)
    item.setExpanded(True)
    assert [c for c in api.calls if c[0] == "datastores"] == [("datastores", "s3cret")]


def test_refresh_reloads(view, api):
    item = _host_item(view)
    item.setExpanded(True)
    view._refresh(view.products[0], PBS)
    assert len([c for c in api.calls if c[0] == "datastores"]) == 2


def test_a_datastore_whose_groups_fail_shows_the_error(view, api):
    api.fail_groups_for.add("local")
    item = _host_item(view)
    item.setExpanded(True)
    assert _children(item.child(0)) == ["Error: permission check failed"]
    assert item.child(1).childCount() == 2  # the others still load


def test_load_failure_shows_under_the_host(view, monkeypatch):
    def boom(host, secret):
        raise pbs_client.PbsApiError("Couldn't reach https://pbs1.lan:8007")

    monkeypatch.setattr(pbs_client, "list_datastores", boom)
    item = _host_item(view)
    item.setExpanded(True)
    assert _children(item) == ["Error: Couldn't reach https://pbs1.lan:8007"]


def test_double_clicking_a_group_opens_the_datastore_tab_filtered(view, api):
    item = _host_item(view)
    item.setExpanded(True)
    group = item.child(0).child(0)
    view._on_item_double_clicked(group, 0)

    tab = view.tabs.currentWidget()
    assert isinstance(tab, PbsDatastoreWidget)
    assert view.tabs.tabText(view.tabs.currentIndex()) == "PBS: pbs1 / local"
    assert tab._search.text() == "vm/101"
    assert tab._table.rowCount() == 2


def test_a_datastore_tab_is_reused_for_another_namespace(view, api):
    item = _host_item(view)
    item.setExpanded(True)
    offsite = item.child(1)
    view._on_item_double_clicked(offsite, 0)
    view._on_item_double_clicked(offsite.child(1), 0)
    assert view.tabs.count() == 1
    tab = view.tabs.currentWidget()
    assert tab.namespace == "site-a"
    assert api.calls[-1] == ("snapshots", "offsite", "site-a")


def test_double_clicking_the_host_opens_the_dashboard(view, api):
    view._on_item_double_clicked(_host_item(view), 0)
    assert isinstance(view.tabs.currentWidget(), PbsDashboardWidget)
    assert view.tabs.tabText(0) == "PBS: pbs1"


def test_datastore_menu_entries(view, api):
    item = _host_item(view)
    item.setExpanded(True)
    menu = QMenu()
    product = view.products[0]
    product.add_item_actions(menu, item.child(0), PBS, DatastoreNode("local"))
    assert [a.text() for a in menu.actions()] == ["Show Snapshots", "Open Datastore in Web UI"]
    host_menu = QMenu()
    product.add_item_actions(host_menu, item, PBS, None)
    assert host_menu.actions() == []


def test_datastore_web_url():
    assert datastore_web_url(PBS, "local") == "https://pbs1.lan:8007/#DataStore-local"


# -- Dashboard -------------------------------------------------------------------


@pytest.fixture
def dashboard(qtbot, api, monkeypatch):
    monkeypatch.setattr(pbs_client, "list_datastores", lambda h, s: [LOCAL, OFFSITE])
    widget = PbsDashboardWidget(PBS, "s3cret")
    qtbot.addWidget(widget)
    return widget


def test_dashboard_fills_every_section(dashboard):
    assert dashboard._host_fields["version"].text() == "Proxmox Backup Server 4.2.8"
    assert dashboard._host_fields["cpu"].text() == "50% of 4 CPUs"
    assert dashboard._host_fields["uptime"].text() == "1d 1h"
    assert dashboard._datastores_table.rowCount() == 2
    assert dashboard._datastores_table.item(0, 3).text() == "90.0%"
    assert dashboard._datastores_table.item(1, 5).text() == "S3"
    jobs = dashboard._jobs_table
    assert [jobs.item(r, 0).text() for r in range(jobs.rowCount())] == ["Verify", "Garbage collection"]
    assert jobs.item(0, 5).text() == "verification failed"


def test_dashboard_lists_failed_tasks_first_then_running(dashboard):
    tasks = dashboard._tasks_table
    assert [tasks.item(r, 4).text() for r in range(tasks.rowCount())] == ["verification failed", "Running", "OK"]


def test_dashboard_shows_errors(qtbot, api, monkeypatch):
    def boom(host, secret):
        raise pbs_client.PbsApiError("permission check failed")

    monkeypatch.setattr(pbs_client, "list_jobs", boom)
    widget = PbsDashboardWidget(PBS, "s3cret")
    qtbot.addWidget(widget)
    assert not widget._error_label.isHidden()
    assert widget._error_label.text() == "permission check failed"


def test_dashboard_timer_refreshes_only_while_visible(dashboard, monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "refresh", lambda: calls.append(1))
    dashboard._on_timer()
    assert calls == []  # never shown
    dashboard.show()
    dashboard._on_timer()
    assert calls == [1]
    dashboard.close_session()
    assert not dashboard._timer.isActive()


# -- Datastore tab and formatting -------------------------------------------------


def test_datastore_tab_summary_and_filter(qtbot, api):
    widget = PbsDatastoreWidget(PBS, "s3cret", "local")
    qtbot.addWidget(widget)
    assert widget._table.rowCount() == 3
    assert widget._table.item(0, 3).text() == "OK"
    assert widget._table.item(1, 3).text() == "Failed"
    assert widget._table.item(2, 5).text() == "Yes"
    assert widget._status_label.text().startswith("3 snapshots in 2 groups")
    widget._search.setText("105")
    assert widget._table.rowCount() == 1
    assert "(filtered from 3)" in widget._status_label.text()


def test_namespace_picker_is_disabled_with_only_the_root(qtbot, api):
    widget = PbsDatastoreWidget(PBS, "s3cret", "local")
    qtbot.addWidget(widget)
    assert not widget._ns_combo.isEnabled()
    other = PbsDatastoreWidget(PBS, "s3cret", "offsite", ns="site-a")
    qtbot.addWidget(other)
    assert other._ns_combo.isEnabled() and other.namespace == "site-a"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", True), ("vm/101", True), ("101", True), ("UPGRADE", True), ("ct/", False), ("root@", False)],
)
def test_snapshot_matches(text, expected):
    assert snapshot_matches(SNAPSHOTS[0], text) is expected


def test_formatting_helpers():
    assert format_bytes(None) == "—"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_age(0) == "never"
    assert format_age(1000, now=1000 + 7200) == "2h ago"
    assert format_age(1000, now=1000 + 3 * 86400) == "3d ago"
    assert estimated_full_label(DatastoreUsage("x")) == "Not enough data yet"
    assert estimated_full_label(DatastoreUsage("x", estimated_full_date=100), now=200) == "Not filling up"
    assert estimated_full_label(DatastoreUsage("x", estimated_full_date=4102444800 + 43200), now=0) == "2100-01-01"


def test_usage_warning_matches_the_spec():
    assert pbs_dashboard_widget.USAGE_WARNING == 0.85
    assert pbs_product.needs_attention(LOCAL)
    assert not pbs_product.needs_attention(OFFSITE)

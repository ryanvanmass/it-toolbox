import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from it_toolbox.modules.connection_manager.models import (
    GcpProject,
    GcsBucket,
    Instance,
    ManualConnection,
    QemuHost,
    QemuVm,
)
from it_toolbox.modules.connection_manager.ui.main_view import ConnectionManagerView
from it_toolbox.widgets.terminal_widget import TerminalWidget


class _FakeTunnel:
    def __init__(self, port=2222):
        self.port = port
        self.stopped = False

    def start(self):
        return self.port

    def stop(self, timeout=5):
        self.stopped = True


def _make_view(qtbot, monkeypatch, qemu_hosts=(), manual_connections=()):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.is_available",
        lambda: False,
    )
    # QEMU hosts and manual connections are loaded unconditionally
    # (independent of GCP sign-in) — stub both out so tests don't depend
    # on this machine's real qemu_hosts.json/manual_connections.json.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.settings.load_qemu_hosts",
        lambda: list(qemu_hosts),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.settings.load_manual_connections",
        lambda: list(manual_connections),
    )
    view = ConnectionManagerView()
    qtbot.addWidget(view)
    return view


def test_projects_are_nested_under_a_gcp_category(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]

    view._apply_project_selection({"p1"})

    # GCP, QEMU, and Manual are independent top-level roots (QEMU/Manual
    # lists are empty here, but the roots themselves are always present).
    assert view._tree.topLevelItemCount() == 3
    gcp_category = view._tree.topLevelItem(0)
    assert gcp_category.text(0) == "GCP"
    assert gcp_category.isExpanded()
    assert gcp_category.childCount() == 1
    project_item = gcp_category.child(0)
    assert project_item.text(0) == "Project One"

    qemu_category = view._tree.topLevelItem(1)
    assert qemu_category.text(0) == "QEMU"

    manual_category = view._tree.topLevelItem(2)
    assert manual_category.text(0) == "Manual"


def test_project_has_vms_and_buckets_categories(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import (
        CATEGORY_BUCKETS,
        CATEGORY_ROLE,
        CATEGORY_VMS,
    )

    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    project_item = view._tree.topLevelItem(0).child(0)
    assert project_item.childCount() == 2
    assert project_item.child(0).text(0) == "VMs"
    assert project_item.child(0).data(0, CATEGORY_ROLE) == CATEGORY_VMS
    assert project_item.child(1).text(0) == "Buckets"
    assert project_item.child(1).data(0, CATEGORY_ROLE) == CATEGORY_BUCKETS


def test_expanding_buckets_category_populates_bucket_items(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import BUCKET_ROLE

    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    buckets_item = view._tree.topLevelItem(0).child(0).child(1)

    bucket = GcsBucket(name="my-bucket", project_id="p1")
    view._populate_buckets(buckets_item, [bucket])

    assert buckets_item.childCount() == 1
    assert buckets_item.child(0).text(0) == "my-bucket"
    assert buckets_item.child(0).data(0, BUCKET_ROLE) == bucket


def test_expanding_vms_category_populates_instance_items(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    vms_item = view._tree.topLevelItem(0).child(0).child(0)

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view._populate_instances(vms_item, [instance])

    assert vms_item.childCount() == 1
    assert vms_item.child(0).text(0) == "vm-1"


def test_double_clicking_a_bucket_opens_a_browser_tab(qtbot, monkeypatch):
    import it_toolbox.widgets.bucket_browser_widget as browser_module

    monkeypatch.setattr(
        browser_module.gcp_client, "list_objects", lambda creds, bucket, prefix: []
    )
    view = _make_view(qtbot, monkeypatch)
    bucket = GcsBucket(name="my-bucket", project_id="p1")

    view._open_bucket_browser(bucket)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "my-bucket"


def test_closing_a_bucket_browser_tab_just_removes_it(qtbot, monkeypatch):
    import it_toolbox.widgets.bucket_browser_widget as browser_module

    monkeypatch.setattr(
        browser_module.gcp_client, "list_objects", lambda creds, bucket, prefix: []
    )
    view = _make_view(qtbot, monkeypatch)
    bucket = GcsBucket(name="my-bucket", project_id="p1")
    view._open_bucket_browser(bucket)

    view._on_tab_close_requested(0)

    assert view._tabs.count() == 0
    assert view._active_sessions == {}  # not tracked as a session


def test_gcp_root_context_menu_offers_select_projects_and_sign_out(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"

    menu = view._build_gcp_root_menu()

    assert [action.text() for action in menu.actions()] == ["Select Projects…", "Sign out"]


def test_gcp_root_context_menu_is_none_when_not_signed_in(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._account = None

    assert view._build_gcp_root_menu() is None


def test_gcp_root_item_is_marked_with_is_gcp_root_role(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import IS_GCP_ROOT_ROLE

    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    root = view._tree.topLevelItem(0)
    assert root.data(0, IS_GCP_ROOT_ROLE) is True


def test_ssh_connect_embeds_terminal_and_registers_session(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "test-vm"
    assert len(view._active_sessions) == 1
    assert len(view._session_tab_widgets) == 1


def test_ssh_connect_gives_the_terminal_keyboard_focus(qtbot, monkeypatch):
    # Regression test: keyPressEvent() only ever fires for the widget that
    # actually has Qt focus. A prior version created the terminal tab but
    # never called setFocus() on it, so real keystrokes silently went
    # nowhere — invisible in a test that calls keyPressEvent() directly
    # instead of exercising real focus, which is exactly how this was
    # missed originally.
    view = _make_view(qtbot, monkeypatch)
    view.show()
    qtbot.waitExposed(view)
    tunnel = _FakeTunnel()

    # A real `ssh` against a closed port fails almost instantly, tearing
    # the tab back down while this test is still polling it — a long-lived
    # shell exercises the same focus-wiring path deterministically instead.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.TerminalWidget",
        lambda argv: TerminalWidget(["/bin/sh"]),
    )

    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    terminal = view._tabs.widget(0)
    qtbot.waitUntil(lambda: terminal.hasFocus(), timeout=2000)
    terminal.close_session()


def test_closing_tab_disconnects_and_stops_tunnel(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()
    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    view._on_tab_close_requested(0)

    assert view._tabs.count() == 0
    assert view._active_sessions == {}
    assert view._session_tab_widgets == {}
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)


class _FakeRdpWidget(QWidget):
    """Stands in for the real RdpWidget in main_view tests — the real one
    spawns a background thread that immediately drives actual libfreerdp
    ctypes calls, which needs a real reachable RDP server and isn't
    something a unit test should depend on. Exposes the same contract
    main_view relies on: a `finished` signal and close_session()."""

    finished = Signal()

    def __init__(self, host, port, username, password, domain=""):
        super().__init__()
        self.host, self.port, self.username, self.password = host, port, username, password

    def close_session(self):
        pass


def test_rdp_connect_embeds_widget_and_registers_session(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.RdpWidget", _FakeRdpWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_tunnel_ready(tunnel, "test-vm", "rdp", "alice", "secret")

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "test-vm"
    widget = view._tabs.widget(0)
    assert (widget.host, widget.port, widget.username, widget.password) == (
        "127.0.0.1",
        2222,
        "alice",
        "secret",
    )
    assert len(view._active_sessions) == 1


def test_rdp_widget_finishing_disconnects_and_stops_tunnel(qtbot, monkeypatch):
    # Covers both a connect failure and the remote side dropping the
    # connection — RdpWidget.finished fires in either case, and main_view
    # must tear the tab/session/tunnel down the same way for both.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.RdpWidget", _FakeRdpWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_tunnel_ready(tunnel, "test-vm", "rdp", None, None)
    widget = view._tabs.widget(0)
    widget.finished.emit()

    assert view._tabs.count() == 0
    assert view._active_sessions == {}
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)


# -- QEMU hosts / VMs --------------------------------------------------------


def test_populate_qemu_hosts_creates_lazy_loading_host_items(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import CHILDREN_LOADED_ROLE, HOST_ROLE

    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    view = _make_view(qtbot, monkeypatch, qemu_hosts=[{"name": host.name, "uri": host.uri}])

    assert view._tree.topLevelItemCount() == 2  # gcloud unavailable, so QEMU + Manual only
    qemu_root = view._tree.topLevelItem(0)
    assert qemu_root.text(0) == "QEMU"
    assert qemu_root.childCount() == 1
    host_item = qemu_root.child(0)
    assert host_item.text(0) == "lab"
    assert host_item.data(0, HOST_ROLE) == host
    assert host_item.data(0, CHILDREN_LOADED_ROLE) is False
    assert host_item.child(0).text(0) == "Loading…"


def test_populate_qemu_vms_creates_items_with_roles(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import HOST_ROLE, VM_ROLE

    view = _make_view(qtbot, monkeypatch)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    host_item = QTreeWidgetItem(["lab"])
    vm = QemuVm(id="1", name="myvm", state="running")

    view._populate_qemu_vms(host_item, host, [vm])

    assert host_item.childCount() == 1
    vm_item = host_item.child(0)
    assert vm_item.text(0) == "myvm"
    assert vm_item.data(0, HOST_ROLE) == host
    assert vm_item.data(0, VM_ROLE) == vm


def test_populate_qemu_vms_shows_placeholder_when_empty(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    host_item = QTreeWidgetItem(["lab"])

    view._populate_qemu_vms(host_item, host, [])

    assert host_item.childCount() == 1
    assert host_item.child(0).text(0) == "(no VMs)"


class _FakeSpiceWidget(QWidget):
    """Stands in for the real SpiceWidget — the real one spawns a
    background thread that immediately drives actual SpiceClientGLib
    calls against a real SPICE server. Exposes the same contract
    main_view relies on: a `finished` signal and close_session()."""

    finished = Signal()

    def __init__(self, host, port, password=""):
        super().__init__()
        self.host, self.port, self.password = host, port, password

    def close_session(self):
        pass


def test_qemu_connect_embeds_widget_and_registers_session(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.SpiceWidget", _FakeSpiceWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel(port=5901)
    vm = QemuVm(id="1", name="myvm", state="running")

    view._on_qemu_tunnel_ready(tunnel, vm)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "myvm"
    widget = view._tabs.widget(0)
    assert (widget.host, widget.port) == ("127.0.0.1", 5901)
    assert len(view._active_sessions) == 1
    assert view._active_sessions[next(iter(view._active_sessions))][0] == "spice"


def test_spice_widget_finishing_disconnects_and_stops_tunnel(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.SpiceWidget", _FakeSpiceWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel(port=5901)
    vm = QemuVm(id="1", name="myvm", state="running")

    view._on_qemu_tunnel_ready(tunnel, vm)
    widget = view._tabs.widget(0)
    widget.finished.emit()

    assert view._tabs.count() == 0
    assert view._active_sessions == {}
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)


def test_start_qemu_tunnel_raises_when_no_spice_port(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    monkeypatch.setattr(main_view_module.qemu_client, "get_vm_spice_port", lambda host, name: None)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    vm = QemuVm(id="1", name="myvm", state="shut off")

    with pytest.raises(main_view_module.QemuApiError, match="no SPICE port"):
        ConnectionManagerView._start_qemu_tunnel(host, vm)


def test_qemu_power_action_calls_client_and_refreshes_vm_list(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    calls = []
    monkeypatch.setattr(
        main_view_module.qemu_client,
        "power_action",
        lambda host, vm_name, action: calls.append((host, vm_name, action)),
    )
    monkeypatch.setattr(main_view_module.qemu_client, "list_vms", lambda host: [])

    view = _make_view(qtbot, monkeypatch)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    view._qemu_root_item = QTreeWidgetItem(["QEMU"])
    host_item = QTreeWidgetItem(["lab"])
    host_item.setData(0, main_view_module.HOST_ROLE, host)
    view._qemu_root_item.addChild(host_item)
    vm = QemuVm(id="1", name="myvm", state="running")

    view._run_qemu_power_action(host, vm, "shutdown")

    qtbot.waitUntil(lambda: calls == [(host, "myvm", "shutdown")], timeout=2000)
    qtbot.waitUntil(lambda: host_item.childCount() == 1, timeout=2000)
    assert host_item.child(0).text(0) == "(no VMs)"


def test_manage_hosts_dialog_roundtrips_through_settings(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    saved = {}
    monkeypatch.setattr(
        main_view_module.settings, "save_qemu_hosts", lambda hosts: saved.setdefault("hosts", hosts)
    )
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")

    view = _make_view(qtbot, monkeypatch)
    view._save_qemu_hosts([host])

    assert saved["hosts"] == [{"name": "lab", "uri": "qemu+ssh://user@lab-host/system"}]


# -- Manually-configured RDP/SSH connections --------------------------------


def test_populate_manual_connections_creates_items(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import MANUAL_CONNECTION_ROLE

    connection = ManualConnection(name="my-box", host="10.0.0.5", port=3389, kind="rdp")
    view = _make_view(
        qtbot,
        monkeypatch,
        manual_connections=[
            {"name": connection.name, "host": connection.host, "port": connection.port, "kind": connection.kind}
        ],
    )

    manual_root = None
    for i in range(view._tree.topLevelItemCount()):
        if view._tree.topLevelItem(i).text(0) == "Manual":
            manual_root = view._tree.topLevelItem(i)
    assert manual_root is not None
    assert manual_root.childCount() == 1
    item = manual_root.child(0)
    assert item.text(0) == "my-box"
    assert item.data(0, MANUAL_CONNECTION_ROLE) == connection


def test_manual_ssh_connect_embeds_terminal_without_tunnel(qtbot, monkeypatch):
    # No tunnel is involved for a manual connection — it dials host:port
    # directly, so _active_sessions must stay empty (nothing to stop on
    # disconnect) while _session_tab_widgets still tracks the tab.
    view = _make_view(qtbot, monkeypatch)
    connection = ManualConnection(name="my-box", host="10.0.0.5", port=2222, kind="ssh", username="alice")

    view._start_session_from_manual_connection(connection)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "my-box"
    assert view._active_sessions == {}
    assert len(view._session_tab_widgets) == 1


def test_manual_rdp_connect_embeds_widget_without_tunnel(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    monkeypatch.setattr(main_view_module, "RdpWidget", _FakeRdpWidget)
    monkeypatch.setattr(
        main_view_module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("secret", True))
    )
    view = _make_view(qtbot, monkeypatch)
    connection = ManualConnection(name="my-box", host="10.0.0.5", port=3389, kind="rdp", username="alice")

    view._start_session_from_manual_connection(connection)

    assert view._tabs.count() == 1
    widget = view._tabs.widget(0)
    assert (widget.host, widget.port, widget.username, widget.password) == (
        "10.0.0.5",
        3389,
        "alice",
        "secret",
    )
    assert view._active_sessions == {}


def test_manual_connections_roundtrip_through_settings(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    saved = {}
    monkeypatch.setattr(
        main_view_module.settings,
        "save_manual_connections",
        lambda connections: saved.setdefault("connections", connections),
    )
    connection = ManualConnection(name="my-box", host="10.0.0.5", port=3389, kind="rdp", username="alice")

    view = _make_view(qtbot, monkeypatch)
    view._save_manual_connections([connection])

    assert saved["connections"] == [
        {"name": "my-box", "host": "10.0.0.5", "port": 3389, "kind": "rdp", "username": "alice"}
    ]

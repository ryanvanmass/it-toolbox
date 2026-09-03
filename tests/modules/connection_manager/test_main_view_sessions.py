from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from it_toolbox.modules.connection_manager.models import GcpProject, GcsBucket, Instance
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


def _make_view(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.is_available",
        lambda: False,
    )
    view = ConnectionManagerView()
    qtbot.addWidget(view)
    return view


def test_projects_are_nested_under_a_gcp_category(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]

    view._apply_project_selection({"p1"})

    assert view._tree.topLevelItemCount() == 1
    gcp_category = view._tree.topLevelItem(0)
    assert gcp_category.text(0) == "GCP"
    assert gcp_category.isExpanded()
    assert gcp_category.childCount() == 1
    project_item = gcp_category.child(0)
    assert project_item.text(0) == "Project One"


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

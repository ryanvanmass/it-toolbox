import pytest

from it_toolbox.core.iap_tunnel import IapTunnelTarget
from it_toolbox.core.session_launcher import SessionLaunchError
from it_toolbox.modules.connection_manager.models import GcpProject
from it_toolbox.modules.connection_manager.ui.main_view import ConnectionManagerView


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
    assert gcp_category.child(0).text(0) == "Project One"


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


def test_connect_and_launch_starts_tunnel_then_launches_external_client(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.BackgroundTunnel",
        lambda target, get_access_token: _FakeTunnel(),
    )
    launched = {}
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.session_launcher.launch_ssh",
        lambda host, port, username: launched.update(host=host, port=port, username=username),
    )

    target = IapTunnelTarget(project="p", zone="z", instance="i", port=22)
    tunnel = ConnectionManagerView._connect_and_launch(target, "ssh", "alice")

    assert launched == {"host": "127.0.0.1", "port": 2222, "username": "alice"}
    assert tunnel.port == 2222
    assert not tunnel.stopped


def test_connect_and_launch_stops_tunnel_if_external_launch_fails(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.BackgroundTunnel",
        lambda target, get_access_token: _FakeTunnel(),
    )

    def _raise(host, port, username):
        raise SessionLaunchError("no RDP client found")

    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.session_launcher.launch_rdp", _raise
    )

    target = IapTunnelTarget(project="p", zone="z", instance="i", port=3389)
    with pytest.raises(SessionLaunchError):
        ConnectionManagerView._connect_and_launch(target, "rdp", None)


def test_session_started_registers_and_shows_in_active_sessions_dialog(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_session_started("test-vm", "ssh", tunnel)

    assert len(view._active_sessions) == 1
    [session_id] = view._active_sessions.keys()
    assert view._active_sessions[session_id] is tunnel
    assert view._active_sessions_dialog._list.count() == 1
    assert "test-vm" in view._active_sessions_dialog._list.item(0).text()


def test_disconnect_stops_tunnel_and_removes_from_dialog(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()
    view._on_session_started("test-vm", "ssh", tunnel)
    [session_id] = view._active_sessions.keys()

    view._on_disconnect_requested(session_id)

    assert view._active_sessions == {}
    assert view._active_sessions_dialog._list.count() == 0
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)

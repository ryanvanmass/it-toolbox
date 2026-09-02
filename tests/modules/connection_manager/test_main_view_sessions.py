from it_toolbox.modules.connection_manager.models import GcpProject
from it_toolbox.modules.connection_manager.ui.main_view import ConnectionManagerView


class _FakeTunnel:
    def __init__(self, port=2222):
        self.port = port
        self.stopped = False

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


def test_ssh_connect_embeds_terminal_and_registers_session(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    assert view._session_tabs.count() == 1
    assert view._session_tabs.tabText(0) == "test-vm"
    assert len(view._active_sessions) == 1
    assert len(view._session_tab_widgets) == 1


def test_closing_tab_disconnects_and_stops_tunnel(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()
    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    view._on_tab_close_requested(0)

    assert view._session_tabs.count() == 0
    assert view._active_sessions == {}
    assert view._session_tab_widgets == {}
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)


def test_rdp_connect_on_non_windows_falls_back_to_external(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    launched = {}
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.session_launcher.launch_rdp",
        lambda host, port, username: launched.update(host=host, port=port, username=username),
    )

    view._on_tunnel_ready(tunnel, "test-vm", "rdp", "alice")

    assert launched == {"host": "127.0.0.1", "port": 2222, "username": "alice"}
    assert view._session_tabs.count() == 0  # no embedded tab for external sessions
    assert len(view._active_sessions) == 1

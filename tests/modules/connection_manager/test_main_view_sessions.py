from it_toolbox.modules.connection_manager.models import GcpProject
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


def test_rdp_connect_launches_external_client_not_a_tab(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    launched = {}
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.session_launcher.launch_rdp",
        lambda host, port, username: launched.update(host=host, port=port, username=username),
    )

    view._on_tunnel_ready(tunnel, "test-vm", "rdp", "alice")

    assert launched == {"host": "127.0.0.1", "port": 2222, "username": "alice"}
    assert view._tabs.count() == 0  # RDP never embeds
    assert len(view._active_sessions) == 1


def test_rdp_connect_failure_stops_tunnel_and_does_not_register_session(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from it_toolbox.core.session_launcher import SessionLaunchError

    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    def _raise(host, port, username):
        raise SessionLaunchError("no RDP client found")

    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.session_launcher.launch_rdp", _raise
    )
    # QMessageBox.warning() is modal and would otherwise block this test
    # forever waiting for a click that will never come.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    view._on_tunnel_ready(tunnel, "test-vm", "rdp", None)

    assert view._active_sessions == {}
    assert tunnel.stopped

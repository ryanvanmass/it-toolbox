import pytest
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox, QWidget

from it_toolbox.core import async_utils, settings
from it_toolbox.core import cockpit_machines as cm
from it_toolbox.core import remote_helper as rh
from it_toolbox.core.cockpit_machines import CockpitMachine
from it_toolbox.modules.cockpit.ui import main_view
from it_toolbox.modules.cockpit.ui.main_view import (
    IS_ADD_ITEM_ROLE,
    MACHINE_KEY_ROLE,
    TOOL_ROLE,
    CockpitView,
    MachineDialog,
)

WEB = CockpitMachine(name="web", host="web.lan", username="admin")


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    return d


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
def remote(monkeypatch):
    """A fake MachineConnection: `tools` is what detection finds, and
    `needs_sudo` makes connect() demand a sudo password first."""

    class Remote:
        tools = ["hosting", "scheduler"]
        needs_sudo = False
        logins: list[dict] = []

    class FakeConnection:
        def __init__(self, machine, **credentials):
            self.server = machine
            self.credentials = credentials

        def connect(self):
            Remote.logins.append(self.credentials)
            if Remote.needs_sudo and "sudo_password" not in self.credentials:
                raise rh.SudoPasswordRequired()

        def detect_tools(self):
            return list(Remote.tools)

        def close(self):
            pass

    Remote.logins = []
    monkeypatch.setattr(cm, "MachineConnection", FakeConnection)
    return Remote


@pytest.fixture
def fake_managers(monkeypatch):
    class FakeManager(QWidget):
        def __init__(self, server, credentials=None):
            super().__init__()
            self.server = server
            self.credentials = credentials
            self.closed = False

        def close_session(self):
            self.closed = True

    monkeypatch.setattr(main_view, "manager_widget_class", lambda tool: FakeManager)
    return FakeManager


def _view(qtbot):
    view = CockpitView()
    qtbot.addWidget(view)
    return view


def _children(item):
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_migrates_the_managers_saved_servers_into_machines(qtbot):
    settings.save_proftpd_servers([{"name": "nas", "host": "nas.lan", "username": "admin"}])
    settings.save_scheduler_servers([{"name": "nas", "host": "nas.lan", "username": "admin"}])

    view = _view(qtbot)

    assert view._tree.topLevelItem(0).data(0, IS_ADD_ITEM_ROLE) is True
    nas = view._tree.topLevelItem(1)
    assert nas.text(0) == "nas" and nas.toolTip(0) == "admin@nas.lan:22"
    assert _children(nas) == ["ProFTPD Manager", "Scheduler Manager"]
    assert nas.child(1).data(0, TOOL_ROLE) == "scheduler"
    assert [m["name"] for m in settings.load_cockpit_machines()] == ["nas"]


def test_expanding_a_new_machine_detects_its_tools(qtbot, remote):
    settings.save_cockpit_machines([WEB.to_dict()])
    view = _view(qtbot)
    web = view._tree.topLevelItem(1)
    assert _children(web) == ["Expand to check for Cockpit modules"]

    web.setExpanded(True)

    assert _children(web) == ["Hosting Manager", "Scheduler Manager"]
    assert settings.load_cockpit_machines()[0]["tools"] == ["hosting", "scheduler"]


def test_proftpd_without_a_helper_is_still_listed(qtbot, remote):
    remote.tools = ["proftpd-no-helper"]
    settings.save_cockpit_machines([WEB.to_dict()])
    view = _view(qtbot)

    view.detect(view.machines()[0])

    assert _children(view._tree.topLevelItem(1)) == ["ProFTPD Manager (helper not installed)"]


def test_no_modules_found(qtbot, remote):
    remote.tools = []
    settings.save_cockpit_machines([WEB.to_dict()])
    view = _view(qtbot)

    view.detect(view.machines()[0])

    assert _children(view._tree.topLevelItem(1)) == ["(no supported Cockpit modules found)"]


def test_sudo_password_is_asked_once_and_reused_by_the_tabs(qtbot, monkeypatch, remote, fake_managers):
    remote.needs_sudo = True
    settings.save_cockpit_machines([WEB.to_dict()])
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (asked.append(1) or "pw", True))
    view = _view(qtbot)

    view.detect(view.machines()[0])
    tab = view.open_tool(view.machines()[0], cm.HOSTING)

    assert len(asked) == 1
    assert remote.logins[-1] == {"sudo_password": "pw"}
    assert tab.credentials == {"sudo_password": "pw"}
    assert tab.credentials is view._credentials[WEB.key]


def test_a_failed_detection_shows_the_error_under_the_machine(qtbot, monkeypatch, remote):
    def refuse(self):
        raise rh.RemoteHelperError("Connection refused")

    monkeypatch.setattr(cm.MachineConnection, "connect", refuse)
    settings.save_cockpit_machines([WEB.to_dict()])
    view = _view(qtbot)

    view.detect(view.machines()[0])

    assert _children(view._tree.topLevelItem(1)) == ["Couldn't connect: Connection refused"]


def test_double_clicking_a_tool_opens_one_tab_per_machine_and_tool(qtbot, fake_managers):
    settings.save_cockpit_machines([CockpitMachine(name="web", host="web.lan", username="admin",
                                                   tools=["hosting", "scheduler"]).to_dict()])
    view = _view(qtbot)
    web = view._tree.topLevelItem(1)

    view._on_item_double_clicked(web.child(0), 0)
    view._on_item_double_clicked(web.child(0), 0)
    view._on_item_double_clicked(web.child(1), 0)

    assert [view._tabs.tabText(i) for i in range(view._tabs.count())] == ["Hosting: web", "Scheduler: web"]
    hosting = view._tabs.widget(0)
    assert hosting.server.host == "web.lan" and type(hosting.server).__name__ == "HostingServer"

    assert view.try_close_tab(hosting)
    assert hosting.closed and view._tabs.count() == 1
    assert not view.try_close_tab(QWidget())


def test_add_machine_saves_it_and_detects(qtbot, monkeypatch, remote):
    view = _view(qtbot)
    monkeypatch.setattr(MachineDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(MachineDialog, "server", lambda self: CockpitMachine(**vars(WEB)))

    view._on_item_double_clicked(view._tree.topLevelItem(0), 0)

    web = view._tree.topLevelItem(1)
    assert web.data(0, MACHINE_KEY_ROLE) == WEB.key
    assert _children(web) == ["Hosting Manager", "Scheduler Manager"]


def test_remove_machine(qtbot, monkeypatch):
    settings.save_cockpit_machines([WEB.to_dict()])
    view = _view(qtbot)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    view._remove_machine(WEB.key)

    assert settings.load_cockpit_machines() == []
    assert view._tree.topLevelItemCount() == 1


def test_machine_dialog_keeps_the_proftpd_container(qtbot):
    dialog = MachineDialog(CockpitMachine(name="nas", host="nas.lan", username="admin",
                                          proftpd_container="ftp"))
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Edit Machine"
    dialog._container.setText(" ftp2 ")

    machine = dialog.server()
    assert isinstance(machine, CockpitMachine) and machine.proftpd_container == "ftp2"


def test_module_menu_offers_add_machine(qtbot):
    view = _view(qtbot)
    assert [a.text() for a in view.build_context_menu(view).actions()] == ["Add Machine…"]

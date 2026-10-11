import pytest
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from it_toolbox.core import settings
from it_toolbox.core.hosting_manager import HostingServer
from it_toolbox.modules.general_tools.ui import hosting_tool
from it_toolbox.modules.general_tools.ui.hosting_tool import (
    IS_ADD_ITEM_ROLE,
    SERVER_INDEX_ROLE,
)
from it_toolbox.modules.general_tools.ui.main_view import GeneralToolsView

WEB = HostingServer(name="web", host="web.lan", username="admin")


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    return d


@pytest.fixture
def fake_manager(monkeypatch):
    class FakeManager(QWidget):
        def __init__(self, server):
            super().__init__()
            self.server = server
            self.closed = False

        def close_session(self):
            self.closed = True

    monkeypatch.setattr(hosting_tool, "HostingManagerWidget", FakeManager)
    return FakeManager


def _view(qtbot):
    view = GeneralToolsView()
    qtbot.addWidget(view)
    return view


def test_lists_saved_servers_under_add_server(qtbot):
    settings.save_hosting_servers([WEB.to_dict(), {"broken": True}])
    item = _view(qtbot).hosting.item

    assert item.text(0) == "Hosting Manager"
    assert item.childCount() == 2
    assert item.child(0).data(0, IS_ADD_ITEM_ROLE) is True
    assert item.child(1).text(0) == "web"
    assert item.child(1).toolTip(0) == "admin@web.lan:22"
    assert item.child(1).data(0, SERVER_INDEX_ROLE) == 0


def test_add_server_saves_and_opens_it(qtbot, monkeypatch, fake_manager):
    view = _view(qtbot)
    monkeypatch.setattr(hosting_tool.ServerDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(hosting_tool.ServerDialog, "server", lambda self: WEB)

    view.hosting.activate(view.hosting.item.child(0))

    assert settings.load_hosting_servers() == [WEB.to_dict()]
    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "Hosting: web"


def test_opening_an_open_server_switches_to_its_tab(qtbot, fake_manager):
    settings.save_hosting_servers([WEB.to_dict()])
    view = _view(qtbot)

    first = view.hosting.open_server(view.hosting.servers()[0])
    second = view.hosting.open_server(view.hosting.servers()[0])

    assert first is second and view._tabs.count() == 1


def test_closing_the_tab_closes_the_session(qtbot, fake_manager):
    view = _view(qtbot)
    manager = view.hosting.open_server(WEB)

    assert view.try_close_tab(manager)
    assert manager.closed and view._tabs.count() == 0


def test_remove_server(qtbot, monkeypatch):
    settings.save_hosting_servers([WEB.to_dict()])
    view = _view(qtbot)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    view.hosting._remove_server(0)

    assert settings.load_hosting_servers() == []
    assert view.hosting.item.childCount() == 1


def test_server_dialog_builds_a_hosting_server(qtbot):
    dialog = hosting_tool.ServerDialog("Hosting Manager", HostingServer)
    qtbot.addWidget(dialog)
    dialog._host.setText(" web.lan ")
    dialog._username.setText("admin")

    server = dialog.server()
    assert isinstance(server, HostingServer)
    assert server == HostingServer(name="web.lan", host="web.lan", username="admin")

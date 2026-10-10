import pytest
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from it_toolbox.core import settings
from it_toolbox.core.scheduler_manager import SchedulerServer
from it_toolbox.modules.general_tools.ui import scheduler_tool
from it_toolbox.modules.general_tools.ui.scheduler_tool import (
    IS_ADD_ITEM_ROLE,
    SERVER_INDEX_ROLE,
)
from it_toolbox.modules.general_tools.ui.main_view import GeneralToolsView

WEB = SchedulerServer(name="web", host="web.lan", username="admin")


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

    monkeypatch.setattr(scheduler_tool, "SchedulerManagerWidget", FakeManager)
    return FakeManager


def _view(qtbot):
    view = GeneralToolsView()
    qtbot.addWidget(view)
    return view


def test_lists_saved_servers_under_add_server(qtbot):
    settings.save_scheduler_servers([WEB.to_dict(), {"broken": True}])
    item = _view(qtbot).scheduler.item

    assert item.text(0) == "Scheduler Manager"
    assert item.childCount() == 2
    assert item.child(0).data(0, IS_ADD_ITEM_ROLE) is True
    assert item.child(1).text(0) == "web"
    assert item.child(1).toolTip(0) == "admin@web.lan:22"
    assert item.child(1).data(0, SERVER_INDEX_ROLE) == 0


def test_add_server_saves_and_opens_it(qtbot, monkeypatch, fake_manager):
    view = _view(qtbot)
    monkeypatch.setattr(scheduler_tool.ServerDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(scheduler_tool.ServerDialog, "server", lambda self: WEB)

    view.scheduler.activate(view.scheduler.item.child(0))

    assert settings.load_scheduler_servers() == [WEB.to_dict()]
    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "Scheduler: web"


def test_opening_an_open_server_switches_to_its_tab(qtbot, fake_manager):
    settings.save_scheduler_servers([WEB.to_dict()])
    view = _view(qtbot)

    first = view.scheduler.open_server(view.scheduler.servers()[0])
    second = view.scheduler.open_server(view.scheduler.servers()[0])

    assert first is second and view._tabs.count() == 1


def test_closing_the_tab_closes_the_session(qtbot, fake_manager):
    view = _view(qtbot)
    manager = view.scheduler.open_server(WEB)

    assert view.try_close_tab(manager)
    assert manager.closed and view._tabs.count() == 0


def test_remove_server(qtbot, monkeypatch):
    settings.save_scheduler_servers([WEB.to_dict()])
    view = _view(qtbot)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    view.scheduler._remove_server(0)

    assert settings.load_scheduler_servers() == []
    assert view.scheduler.item.childCount() == 1


def test_server_dialog_builds_a_scheduler_server(qtbot):
    dialog = scheduler_tool.ServerDialog("Scheduler Manager", SchedulerServer)
    qtbot.addWidget(dialog)
    dialog._host.setText(" web.lan ")
    dialog._username.setText("admin")

    server = dialog.server()
    assert isinstance(server, SchedulerServer)
    assert server == SchedulerServer(name="web.lan", host="web.lan", username="admin")

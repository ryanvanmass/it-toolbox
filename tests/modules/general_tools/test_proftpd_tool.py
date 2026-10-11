import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from it_toolbox.core import settings
from it_toolbox.core.proftpd_manager import ProftpdServer
from it_toolbox.modules.general_tools.ui import proftpd_tool
from it_toolbox.modules.general_tools.ui.main_view import GeneralToolsView
from it_toolbox.modules.general_tools.ui.proftpd_tool import IS_ADD_ITEM_ROLE, SERVER_INDEX_ROLE

NAS = ProftpdServer(name="nas", host="nas.lan", username="admin")


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    return d




@pytest.fixture
def fake_manager(monkeypatch):
    from PySide6.QtWidgets import QWidget

    class FakeManager(QWidget):
        def __init__(self, server):
            super().__init__()
            self.server = server
            self.closed = False

        def close_session(self):
            self.closed = True

    monkeypatch.setattr(proftpd_tool, "ProftpdManagerWidget", FakeManager)
    return FakeManager


def _view(qtbot):
    view = GeneralToolsView()
    qtbot.addWidget(view)
    return view


def test_lists_saved_servers_under_add_server(qtbot):
    settings.save_proftpd_servers([NAS.to_dict(), {"broken": True}])
    view = _view(qtbot)
    item = view.proftpd.item

    assert item.childCount() == 2
    assert item.child(0).data(0, IS_ADD_ITEM_ROLE) is True
    assert item.child(1).text(0) == "nas"
    assert item.child(1).data(0, SERVER_INDEX_ROLE) == 0


def test_add_server_saves_and_opens_it(qtbot, monkeypatch, fake_manager):
    view = _view(qtbot)
    monkeypatch.setattr(proftpd_tool.ServerDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(proftpd_tool.ServerDialog, "server", lambda self: NAS)

    view._on_item_double_clicked(view.proftpd.item.child(0), 0)

    assert settings.load_proftpd_servers() == [NAS.to_dict()]
    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "ProFTPD: nas"


def test_opening_an_open_server_switches_to_its_tab(qtbot, fake_manager):
    settings.save_proftpd_servers([NAS.to_dict()])
    view = _view(qtbot)

    first = view.proftpd.open_server(NAS)
    again = view.proftpd.open_server(ProftpdServer.from_dict(NAS.to_dict()))

    assert again is first
    assert view._tabs.count() == 1


def test_closing_a_tab_closes_its_session(qtbot, fake_manager):
    view = _view(qtbot)
    manager = view.proftpd.open_server(NAS)

    assert view.try_close_tab(manager) is True

    assert manager.closed
    assert view._tabs.count() == 0


def test_remove_server_asks_first(qtbot, monkeypatch):
    settings.save_proftpd_servers([NAS.to_dict()])
    view = _view(qtbot)
    monkeypatch.setattr(proftpd_tool.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    view.proftpd._remove_server(0)

    assert settings.load_proftpd_servers() == []
    assert view.proftpd.item.childCount() == 1

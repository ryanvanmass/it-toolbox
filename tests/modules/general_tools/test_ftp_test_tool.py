import pytest
from PySide6.QtWidgets import QMenu, QTabWidget, QWidget

from it_toolbox.core import settings
from it_toolbox.modules.general_tools.ui.ftp_test_tool import FtpTestTool
from it_toolbox.modules.general_tools.ui.sftp_test_tool import SAVED_TEST_NAME_ROLE
from it_toolbox.widgets.ftp_server_test_widget import FtpServerTestWidget


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)


def _make(qtbot):
    view = QWidget()
    tabs = QTabWidget()
    qtbot.addWidget(view)
    qtbot.addWidget(tabs)
    return FtpTestTool(view, tabs), tabs


def test_new_test_opens_an_ftp_tab(qtbot):
    tool, tabs = _make(qtbot)
    menu = QMenu()
    tool.add_category_actions(menu)

    assert tool.item.text(0) == "FTP Server Test"
    assert [a.text() for a in menu.actions()] == ["New FTP Server Test…"]
    menu.actions()[0].trigger()
    assert isinstance(tabs.currentWidget(), FtpServerTestWidget)
    assert tabs.tabText(0) == "FTP Server Test"


def test_lists_only_ftp_saved_tests(qtbot):
    settings.save_ftp_server_test_configs({"NAS": {"host": "nas.lan", "username": "ryan"}})
    settings.save_sftp_server_test_configs({"Prod": {"host": "prod"}})
    tool, tabs = _make(qtbot)

    child = tool.item.child(1)
    assert tool.item.childCount() == 2
    assert child.data(0, SAVED_TEST_NAME_ROLE) == "NAS"
    assert child.toolTip(0).startswith("ryan@nas.lan:21")

    tool.activate(child)
    assert tabs.currentWidget()._host_edit.text() == "nas.lan"
    assert tabs.tabText(0) == "FTP Test: NAS"

import pytest
from PySide6.QtWidgets import QMenu, QTabWidget, QWidget

from it_toolbox.core import settings
from it_toolbox.modules.general_tools.ui.sftp_test_tool import IS_NEW_TEST_ITEM_ROLE, SftpTestTool
from it_toolbox.widgets.sftp_server_test_widget import SftpServerTestWidget


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)


def _make(qtbot):
    view = QWidget()
    tabs = QTabWidget()
    qtbot.addWidget(view)
    qtbot.addWidget(tabs)
    return SftpTestTool(view, tabs), tabs


def test_sidebar_offers_a_new_test_entry(qtbot):
    tool, _ = _make(qtbot)

    assert tool.item.text(0) == "SFTP Server Test"
    assert tool.item.childCount() == 1
    assert tool.item.child(0).data(0, IS_NEW_TEST_ITEM_ROLE) is True


def test_activating_new_test_opens_a_tab_each_time(qtbot):
    tool, tabs = _make(qtbot)

    tool.activate(tool.item.child(0))
    tool.activate(tool.item.child(0))

    assert tabs.count() == 2
    assert isinstance(tabs.currentWidget(), SftpServerTestWidget)
    assert tabs.tabText(0) == "SFTP Server Test"


def test_tab_title_follows_the_tested_host(qtbot):
    tool, tabs = _make(qtbot)
    widget = tool.new_test()

    widget.title_changed.emit("SFTP Test: sftp.example.com")

    assert tabs.tabText(tabs.indexOf(widget)) == "SFTP Test: sftp.example.com"


def test_closing_only_handles_its_own_tabs(qtbot):
    tool, tabs = _make(qtbot)
    widget = tool.new_test()
    other = QWidget()
    tabs.addTab(other, "other")

    assert tool.try_close_tab(other) is False
    assert tool.try_close_tab(widget) is True
    assert tabs.count() == 1


def test_context_menu_action(qtbot):
    tool, tabs = _make(qtbot)
    menu = QMenu()
    tool.add_category_actions(menu)

    assert [a.text() for a in menu.actions()] == ["New SFTP Server Test…"]
    menu.actions()[0].trigger()
    assert tabs.count() == 1

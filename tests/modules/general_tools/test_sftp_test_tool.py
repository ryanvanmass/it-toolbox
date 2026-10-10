import pytest
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QTabWidget, QWidget

from it_toolbox.core import settings
from it_toolbox.modules.general_tools.ui.sftp_test_tool import (
    IS_NEW_TEST_ITEM_ROLE,
    SAVED_TEST_NAME_ROLE,
    SftpTestTool,
)
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


def _saved_names(tool):
    return [tool.item.child(i).data(0, SAVED_TEST_NAME_ROLE) for i in range(1, tool.item.childCount())]


def test_saved_tests_are_listed_under_new_test(qtbot):
    settings.save_sftp_server_test_configs(
        {"zeta": {"host": "z.example.com", "username": "ryan", "port": 2222}, "Alpha": {"host": "a.example.com"}}
    )
    tool, _ = _make(qtbot)

    assert tool.item.child(0).data(0, IS_NEW_TEST_ITEM_ROLE) is True
    assert _saved_names(tool) == ["Alpha", "zeta"]
    assert "ryan@z.example.com:2222" in tool.item.child(2).toolTip(0)


def test_activating_a_saved_test_opens_it_in_a_new_tab(qtbot):
    settings.save_sftp_server_test_configs({"NAS": {"host": "nas.lan", "workers": 12}})
    tool, tabs = _make(qtbot)

    tool.activate(tool.item.child(1))

    widget = tabs.currentWidget()
    assert isinstance(widget, SftpServerTestWidget)
    assert widget._host_edit.text() == "nas.lan"
    assert widget._workers_spin.value() == 12
    assert widget.saved_name == "NAS"
    assert tabs.tabText(0) == "SFTP Test: NAS"


def test_saving_from_a_tab_adds_it_to_the_sidebar(qtbot, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("New box", True))
    tool, _ = _make(qtbot)
    widget = tool.new_test()
    widget._host_edit.setText("box.example.com")

    widget.save_test_config()

    assert _saved_names(tool) == ["New box"]


def test_saved_test_context_menu_renames_and_deletes(qtbot, monkeypatch):
    settings.save_sftp_server_test_configs({"Old": {"host": "h"}})
    tool, _ = _make(qtbot)
    widget = tool.open_saved_test("Old")
    menu = QMenu()
    tool.add_item_actions(menu, tool.item.child(1))
    assert [a.text() for a in menu.actions()] == ["Open", "Rename…", "Delete…"]

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("New", True))
    tool.rename_saved_test("Old")
    assert _saved_names(tool) == ["New"]
    assert list(settings.load_sftp_server_test_configs()) == ["New"]
    assert widget.saved_name == "New"

    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    tool.delete_saved_test("New")
    assert _saved_names(tool) == []
    assert settings.load_sftp_server_test_configs() == {}
    assert widget.saved_name is None

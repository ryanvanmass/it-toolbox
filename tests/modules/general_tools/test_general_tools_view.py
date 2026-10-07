import pytest

from it_toolbox.core import settings
from it_toolbox.modules.general_tools.ui import recent_files_tool
from it_toolbox.modules.general_tools.ui.main_view import GeneralToolsView
from it_toolbox.modules.general_tools.ui.mbox_tool import IS_OPEN_ITEM_ROLE, PATH_ROLE


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    return d


def _make_view(qtbot):
    view = GeneralToolsView()
    qtbot.addWidget(view)
    return view


def test_each_tool_is_a_top_level_category(qtbot):
    view = _make_view(qtbot)

    assert view._tree.topLevelItemCount() == 2
    assert view._tree.topLevelItem(1).text(0) == "EML Viewer"
    mbox_item = view._tree.topLevelItem(0)
    assert mbox_item.text(0) == "Mbox Browser"
    assert mbox_item.isExpanded()
    assert mbox_item.childCount() == 1
    assert mbox_item.child(0).data(0, IS_OPEN_ITEM_ROLE) is True


def test_module_context_menu_offers_tool_actions(qtbot):
    view = _make_view(qtbot)

    menu = view.build_context_menu(view)

    assert [a.text() for a in menu.actions()] == [
        "Open Mbox File…",
        "Clear Recent Mbox Files",
        "",
        "Open EML File…",
        "Clear Recent EML Files",
    ]


def test_opening_a_file_adds_a_tab_and_remembers_it(qtbot, sample_mbox):
    view = _make_view(qtbot)
    path = sample_mbox("a.mbox")

    browser = view.mbox.open_file(str(path))
    qtbot.waitSignal(browser.loaded, timeout=5000).wait()

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "a.mbox"
    assert settings.load_recent_mbox_files() == [str(path.resolve())]
    assert view.mbox.item.child(1).data(0, PATH_ROLE) == str(path.resolve())


def test_double_clicking_a_recent_file_opens_it(qtbot, sample_mbox):
    settings.save_recent_mbox_files([str(sample_mbox("a.mbox").resolve())])
    view = _make_view(qtbot)

    view._on_item_double_clicked(view.mbox.item.child(1), 0)

    assert view._tabs.count() == 1


def test_reopening_an_open_file_switches_to_its_tab(qtbot, sample_mbox, tmp_path):
    view = _make_view(qtbot)
    first = view.mbox.open_file(str(sample_mbox("a.mbox")))
    view.mbox.open_file(str(sample_mbox("b.mbox")))

    again = view.mbox.open_file(str(tmp_path / "a.mbox"))

    assert again is first
    assert view._tabs.count() == 2
    assert view._tabs.currentWidget() is first
    assert [p.rsplit("/", 1)[-1] for p in settings.load_recent_mbox_files()] == [
        "a.mbox",
        "b.mbox",
    ]


def test_closing_a_tab_tears_it_down(qtbot, sample_mbox):
    view = _make_view(qtbot)
    browser = view.mbox.open_file(str(sample_mbox("a.mbox")))
    qtbot.waitUntil(lambda: browser._reader is not None, timeout=5000)

    assert view.try_close_tab(browser)
    assert view._tabs.count() == 0
    assert browser._reader is None
    assert not view.try_close_tab(browser)


def test_missing_recent_file_is_disabled(qtbot, tmp_path):
    settings.save_recent_mbox_files([str(tmp_path / "gone.mbox")])
    view = _make_view(qtbot)

    item = view.mbox.item.child(1)
    assert item.isDisabled()
    assert "not found" in item.toolTip(0)


def test_prompt_open_file(qtbot, sample_mbox, monkeypatch):
    view = _make_view(qtbot)
    path = sample_mbox("a.mbox")
    monkeypatch.setattr(
        recent_files_tool.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), "")
    )

    view.mbox.prompt_open_file()

    assert view._tabs.count() == 1


def test_recent_files_are_capped():
    settings.save_recent_mbox_files([f"/x/{i}.mbox" for i in range(20)])
    assert len(settings.load_recent_mbox_files()) == settings.RECENT_FILES_LIMIT


def test_opening_an_eml_file_adds_a_viewer_tab(qtbot, sample_eml):
    view = _make_view(qtbot)
    path = sample_eml()

    viewer = view.eml.open_file(str(path))
    qtbot.waitSignal(viewer.loaded, timeout=5000).wait()

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "invoice.eml"
    assert settings.load_recent_eml_files() == [str(path.resolve())]
    assert settings.load_recent_mbox_files() == []
    assert view.eml.item.child(1).data(0, PATH_ROLE) == str(path.resolve())
    assert "Subject: Invoice" in viewer._view._headers_label.text()


def test_closing_an_eml_tab_is_handled_by_its_tool(qtbot, sample_eml):
    view = _make_view(qtbot)
    viewer = view.eml.open_file(str(sample_eml()))

    assert view.try_close_tab(viewer)
    assert view._tabs.count() == 0
    assert viewer._closed

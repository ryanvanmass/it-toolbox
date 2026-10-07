import pytest

from it_toolbox.core import settings
from it_toolbox.modules.mbox_browser.ui import main_view
from it_toolbox.modules.mbox_browser.ui.main_view import (
    IS_OPEN_ITEM_ROLE,
    PATH_ROLE,
    MboxBrowserView,
)


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    return d


def _make_view(qtbot):
    view = MboxBrowserView()
    qtbot.addWidget(view)
    return view





def test_sidebar_starts_with_open_entry_only(qtbot):
    view = _make_view(qtbot)

    assert view._tree.topLevelItemCount() == 1
    assert view._tree.topLevelItem(0).data(0, IS_OPEN_ITEM_ROLE) is True


def test_opening_a_file_adds_a_tab_and_remembers_it(qtbot, sample_mbox, tmp_path):
    view = _make_view(qtbot)
    path = sample_mbox("a.mbox")

    browser = view.open_file(str(path))
    qtbot.waitSignal(browser.loaded, timeout=5000).wait()

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "a.mbox"
    assert settings.load_recent_mbox_files() == [str(path.resolve())]
    assert view._tree.topLevelItem(1).data(0, PATH_ROLE) == str(path.resolve())


def test_reopening_an_open_file_switches_to_its_tab(qtbot, sample_mbox, tmp_path):
    view = _make_view(qtbot)
    first = view.open_file(str(sample_mbox("a.mbox")))
    view.open_file(str(sample_mbox("b.mbox")))

    again = view.open_file(str(tmp_path / "a.mbox"))

    assert again is first
    assert view._tabs.count() == 2
    assert view._tabs.currentWidget() is first
    assert [p.rsplit("/", 1)[-1] for p in settings.load_recent_mbox_files()] == [
        "a.mbox",
        "b.mbox",
    ]


def test_closing_a_tab_tears_it_down(qtbot, sample_mbox, tmp_path):
    view = _make_view(qtbot)
    browser = view.open_file(str(sample_mbox("a.mbox")))
    qtbot.waitUntil(lambda: browser._reader is not None, timeout=5000)

    assert view.try_close_tab(browser)
    assert view._tabs.count() == 0
    assert browser._reader is None
    assert not view.try_close_tab(browser)


def test_missing_recent_file_is_disabled(qtbot, sample_mbox, tmp_path):
    settings.save_recent_mbox_files([str(tmp_path / "gone.mbox")])
    view = _make_view(qtbot)

    item = view._tree.topLevelItem(1)
    assert item.isDisabled()
    assert "not found" in item.toolTip(0)


def test_prompt_open_file(qtbot, sample_mbox, tmp_path, monkeypatch):
    view = _make_view(qtbot)
    path = sample_mbox("a.mbox")
    monkeypatch.setattr(
        main_view.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), "")
    )

    view.prompt_open_file()

    assert view._tabs.count() == 1


def test_recent_files_are_capped(qtbot, data_dir):
    settings.save_recent_mbox_files([f"/x/{i}.mbox" for i in range(20)])
    assert len(settings.load_recent_mbox_files()) == settings.RECENT_MBOX_FILES_LIMIT

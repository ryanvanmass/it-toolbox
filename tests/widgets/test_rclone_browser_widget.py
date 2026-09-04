from it_toolbox.modules.cloud_storage.models import RcloneEntry
from it_toolbox.widgets.rclone_browser_widget import RcloneBrowserWidget


def _make_browser(qtbot, monkeypatch, entries_by_path, remote_name="myRemote", start_path=""):
    import it_toolbox.widgets.rclone_browser_widget as module

    monkeypatch.setattr(
        module.rclone_client,
        "list_directory",
        lambda remote, path: entries_by_path[path],
    )
    browser = RcloneBrowserWidget(remote_name, start_path=start_path)
    qtbot.addWidget(browser)
    return browser


def test_browser_loads_root_listing_on_creation(qtbot, monkeypatch):
    entries = {
        "": [
            RcloneEntry(name="photos", path="photos", is_dir=True),
            RcloneEntry(name="readme.txt", path="readme.txt", is_dir=False, size=42),
        ]
    }
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 2, timeout=2000)

    assert "photos" in browser._table.item(0, 0).text()
    assert browser._up_button.isEnabled() is False


def test_double_clicking_a_folder_navigates_into_it(qtbot, monkeypatch):
    entries = {
        "": [RcloneEntry(name="photos", path="photos", is_dir=True)],
        "photos": [RcloneEntry(name="a.jpg", path="a.jpg", is_dir=False, size=10)],
    }
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    browser._on_item_double_clicked(browser._table.item(0, 0))

    assert browser._path == "photos"

    def _shows_a_jpg() -> bool:
        item = browser._table.item(0, 0)
        return item is not None and item.text() == "a.jpg"

    qtbot.waitUntil(_shows_a_jpg, timeout=2000)
    assert browser._up_button.isEnabled() is True


def test_navigating_into_a_folder_from_a_nonempty_start_path_joins_correctly(qtbot, monkeypatch):
    entries = {
        "some/base": [RcloneEntry(name="sub", path="sub", is_dir=True)],
        "some/base/sub": [],
    }
    browser = _make_browser(qtbot, monkeypatch, entries, start_path="some/base")
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    browser._on_item_double_clicked(browser._table.item(0, 0))

    assert browser._path == "some/base/sub"


def test_up_button_navigates_back_to_parent(qtbot, monkeypatch):
    entries = {
        "": [RcloneEntry(name="root-file", path="root-file", is_dir=False)],
        "photos/2024": [],
        "photos": [],
    }
    browser = _make_browser(qtbot, monkeypatch, entries)
    browser._path = "photos/2024"

    browser._go_up()
    assert browser._path == "photos"

    browser._go_up()
    assert browser._path == ""
    assert browser._up_button.isEnabled() is False


def test_close_session_is_a_harmless_noop(qtbot, monkeypatch):
    browser = _make_browser(qtbot, monkeypatch, {"": []})
    browser.close_session()  # must not raise

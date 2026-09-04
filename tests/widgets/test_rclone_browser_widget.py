from PySide6.QtWidgets import QMessageBox

from it_toolbox.modules.cloud_storage.models import RcloneEntry
from it_toolbox.widgets.rclone_browser_widget import ENTRY_ROLE, RcloneBrowserWidget


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


def test_upload_sends_local_file_to_current_path_and_reloads(qtbot, monkeypatch):
    import it_toolbox.widgets.rclone_browser_widget as module

    entries = {"some/dir": []}
    browser = _make_browser(qtbot, monkeypatch, entries, start_path="some/dir")
    qtbot.waitUntil(lambda: browser._table.rowCount() == 0, timeout=2000)

    monkeypatch.setattr(
        module.QFileDialog, "getOpenFileName", lambda *a, **k: ("/tmp/local.txt", "")
    )
    captured = {}
    monkeypatch.setattr(
        module.rclone_client,
        "upload",
        lambda remote, local_path, dest_path: captured.update(
            remote=remote, local_path=local_path, dest_path=dest_path
        ),
    )

    browser._on_upload_clicked()

    qtbot.waitUntil(lambda: captured.get("remote") == "myRemote", timeout=2000)
    assert captured["local_path"] == "/tmp/local.txt"
    assert captured["dest_path"] == "some/dir/local.txt"


def test_upload_does_nothing_on_cancel(qtbot, monkeypatch):
    import it_toolbox.widgets.rclone_browser_widget as module

    browser = _make_browser(qtbot, monkeypatch, {"": []})
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    called = []
    monkeypatch.setattr(
        module.rclone_client, "upload", lambda *a, **k: called.append(True)
    )

    browser._on_upload_clicked()

    assert called == []


def test_delete_file_confirms_then_calls_delete_file(qtbot, monkeypatch):
    import it_toolbox.widgets.rclone_browser_widget as module

    entries = {"": [RcloneEntry(name="a.txt", path="a.txt", is_dir=False, size=1)]}
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    monkeypatch.setattr(module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    captured = {}
    monkeypatch.setattr(
        module.rclone_client,
        "delete_file",
        lambda remote, path: captured.update(remote=remote, path=path),
    )

    entry = browser._table.item(0, 0).data(module.ENTRY_ROLE)
    browser._delete_entry(entry)

    qtbot.waitUntil(lambda: captured.get("path") == "a.txt", timeout=2000)
    assert captured["remote"] == "myRemote"


def test_delete_folder_calls_delete_directory(qtbot, monkeypatch):
    import it_toolbox.widgets.rclone_browser_widget as module

    entries = {"": [RcloneEntry(name="sub", path="sub", is_dir=True)]}
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    monkeypatch.setattr(module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    captured = {}
    monkeypatch.setattr(
        module.rclone_client,
        "delete_directory",
        lambda remote, path: captured.update(remote=remote, path=path),
    )

    entry = browser._table.item(0, 0).data(module.ENTRY_ROLE)
    browser._delete_entry(entry)

    qtbot.waitUntil(lambda: captured.get("path") == "sub", timeout=2000)


def test_delete_does_nothing_without_confirmation(qtbot, monkeypatch):
    import it_toolbox.widgets.rclone_browser_widget as module

    entries = {"": [RcloneEntry(name="a.txt", path="a.txt", is_dir=False)]}
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    monkeypatch.setattr(module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    called = []
    monkeypatch.setattr(module.rclone_client, "delete_file", lambda *a, **k: called.append(True))

    entry = browser._table.item(0, 0).data(module.ENTRY_ROLE)
    browser._delete_entry(entry)

    assert called == []


def test_entry_menu_hides_download_for_folders(qtbot, monkeypatch):
    entries = {"": [RcloneEntry(name="sub", path="sub", is_dir=True)]}
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    entry = browser._table.item(0, 0).data(ENTRY_ROLE)
    menu, download_action, delete_action = browser._build_entry_menu(entry)

    assert [action.text() for action in menu.actions()] == ["Delete"]
    assert download_action is None
    assert delete_action is not None


def test_entry_menu_offers_download_for_files(qtbot, monkeypatch):
    entries = {"": [RcloneEntry(name="a.txt", path="a.txt", is_dir=False)]}
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    entry = browser._table.item(0, 0).data(ENTRY_ROLE)
    menu, download_action, delete_action = browser._build_entry_menu(entry)

    assert [action.text() for action in menu.actions()] == ["Download", "Delete"]
    assert download_action is not None

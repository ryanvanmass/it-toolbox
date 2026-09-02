from it_toolbox.modules.connection_manager.models import GcsBucket, GcsEntry
from it_toolbox.widgets.bucket_browser_widget import BucketBrowserWidget, format_size


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1024 * 1024 * 1024) == "1.0 GB"


def _make_browser(qtbot, monkeypatch, entries_by_prefix):
    import it_toolbox.widgets.bucket_browser_widget as module

    monkeypatch.setattr(
        module.gcp_client, "list_objects", lambda creds, bucket, prefix: entries_by_prefix[prefix]
    )
    bucket = GcsBucket(name="my-bucket", project_id="proj")
    browser = BucketBrowserWidget(bucket, get_credentials=lambda: object())
    qtbot.addWidget(browser)
    return browser


def test_browser_loads_root_listing_on_creation(qtbot, monkeypatch):
    entries = {
        "": [
            GcsEntry(name="photos", full_path="photos/", is_folder=True),
            GcsEntry(name="readme.txt", full_path="readme.txt", is_folder=False, size=42),
        ]
    }
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 2, timeout=2000)

    assert "photos" in browser._table.item(0, 0).text()
    assert browser._up_button.isEnabled() is False


def test_double_clicking_a_folder_navigates_into_it(qtbot, monkeypatch):
    entries = {
        "": [GcsEntry(name="photos", full_path="photos/", is_folder=True)],
        "photos/": [GcsEntry(name="a.jpg", full_path="photos/a.jpg", is_folder=False, size=10)],
    }
    browser = _make_browser(qtbot, monkeypatch, entries)
    qtbot.waitUntil(lambda: browser._table.rowCount() == 1, timeout=2000)

    browser._on_item_double_clicked(browser._table.item(0, 0))

    assert browser._prefix == "photos/"

    def _shows_a_jpg() -> bool:
        item = browser._table.item(0, 0)
        return item is not None and item.text() == "a.jpg"

    qtbot.waitUntil(_shows_a_jpg, timeout=2000)
    assert browser._up_button.isEnabled() is True


def test_up_button_navigates_back_to_parent(qtbot, monkeypatch):
    entries = {
        "": [GcsEntry(name="root-file", full_path="root-file", is_folder=False)],
        "photos/2024/": [],
        "photos/": [],
    }
    browser = _make_browser(qtbot, monkeypatch, entries)
    browser._prefix = "photos/2024/"

    browser._go_up()
    assert browser._prefix == "photos/"

    browser._go_up()
    assert browser._prefix == ""
    assert browser._up_button.isEnabled() is False


def test_close_session_is_a_harmless_noop(qtbot, monkeypatch):
    browser = _make_browser(qtbot, monkeypatch, {"": []})
    browser.close_session()  # must not raise

from PySide6.QtWidgets import QMessageBox

from it_toolbox.modules.cloud_storage.models import RemoteConfig
from it_toolbox.modules.cloud_storage.ui.main_view import (
    IS_REMOTES_ROOT_ROLE,
    REMOTE_ROLE,
    CloudStorageView,
)


def _make_view(qtbot, monkeypatch, remotes=(), available=True):
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.rclone_client.is_available",
        lambda: available,
    )
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.rclone_client.list_remotes",
        lambda: list(remotes),
    )
    view = CloudStorageView()
    qtbot.addWidget(view)
    return view


def test_remotes_root_is_the_only_top_level_item(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    assert view._tree.topLevelItemCount() == 1
    root = view._tree.topLevelItem(0)
    assert root.text(0) == "Remotes"
    assert root.data(0, IS_REMOTES_ROOT_ROLE) is True
    assert root.isExpanded()


def test_remotes_are_grouped_by_type(qtbot, monkeypatch):
    remotes = [
        RemoteConfig(name="myBucket", type="s3"),
        RemoteConfig(name="myLocal", type="local"),
        RemoteConfig(name="otherBucket", type="s3"),
    ]
    view = _make_view(qtbot, monkeypatch, remotes=remotes)

    root = view._tree.topLevelItem(0)
    qtbot.waitUntil(lambda: root.childCount() == 2, timeout=1000)

    # Type categories sorted alphabetically ("local" before "s3").
    local_category = root.child(0)
    s3_category = root.child(1)
    assert local_category.text(0) == "local"
    assert s3_category.text(0) == "s3"
    assert local_category.isExpanded()

    assert local_category.childCount() == 1
    assert local_category.child(0).text(0) == "myLocal"
    assert local_category.child(0).data(0, REMOTE_ROLE) == remotes[1]

    # Remotes within a type category keep list_remotes()'s name order.
    assert [s3_category.child(i).text(0) for i in range(s3_category.childCount())] == [
        "myBucket",
        "otherBucket",
    ]


def test_refresh_repopulates_the_tree(qtbot, monkeypatch):
    remotes = [RemoteConfig(name="myLocal", type="local")]
    view = _make_view(qtbot, monkeypatch, remotes=remotes)
    root = view._tree.topLevelItem(0)
    qtbot.waitUntil(lambda: root.childCount() == 1, timeout=1000)

    remotes.append(RemoteConfig(name="myBucket", type="s3"))
    view.refresh_remotes()

    qtbot.waitUntil(lambda: root.childCount() == 2, timeout=1000)


def test_unavailable_rclone_shows_no_remotes_without_erroring(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, available=False)

    root = view._tree.topLevelItem(0)
    assert root.childCount() == 1
    assert "rclone CLI not found" in root.child(0).text(0)


def test_sidebar_entry_menu_offers_set_rclone_location_and_refresh(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.settings.load_rclone_path", lambda: None
    )
    view = _make_view(qtbot, monkeypatch)

    menu = view.build_context_menu(view)

    assert [action.text() for action in menu.actions()] == [
        "Set rclone Location…",
        "Refresh",
    ]


def test_sidebar_entry_menu_offers_change_and_clear_when_override_is_set(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.settings.load_rclone_path",
        lambda: "/opt/rclone/rclone",
    )
    view = _make_view(qtbot, monkeypatch)

    menu = view.build_context_menu(view)

    assert [action.text() for action in menu.actions()] == [
        "Change rclone Location…",
        "Use rclone from PATH",
        "Refresh",
    ]


def test_set_rclone_path_saves_chosen_path_and_refreshes(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.settings.save_rclone_path",
        lambda path: saved.append(path),
    )
    monkeypatch.setattr(
        "it_toolbox.widgets.rclone_location_picker.QFileDialog.getOpenFileName",
        lambda *a, **k: ("/opt/rclone/rclone", ""),
    )

    view._on_set_rclone_path_clicked()

    assert saved == ["/opt/rclone/rclone"]


def test_set_rclone_path_does_nothing_on_cancel(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.settings.save_rclone_path",
        lambda path: saved.append(path),
    )
    monkeypatch.setattr(
        "it_toolbox.widgets.rclone_location_picker.QFileDialog.getOpenFileName",
        lambda *a, **k: ("", ""),
    )

    view._on_set_rclone_path_clicked()

    assert saved == []


def test_clear_rclone_path_saves_none_and_refreshes(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.settings.save_rclone_path",
        lambda path: saved.append(path),
    )

    view._on_clear_rclone_path_clicked()

    assert saved == [None]


def test_double_clicking_a_remote_opens_a_browser_tab(qtbot, monkeypatch):
    remotes = [RemoteConfig(name="myLocal", type="local")]
    view = _make_view(qtbot, monkeypatch, remotes=remotes)
    root = view._tree.topLevelItem(0)
    qtbot.waitUntil(lambda: root.childCount() == 1, timeout=1000)
    category = root.child(0)
    qtbot.waitUntil(lambda: category.childCount() == 1, timeout=1000)
    monkeypatch.setattr(
        "it_toolbox.widgets.rclone_browser_widget.rclone_client.list_directory",
        lambda remote, path: [],
    )

    view._on_tree_item_double_clicked(category.child(0), 0)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "myLocal"


def test_browse_context_action_opens_a_browser_tab(qtbot, monkeypatch):
    remotes = [RemoteConfig(name="myLocal", type="local")]
    view = _make_view(qtbot, monkeypatch, remotes=remotes)
    monkeypatch.setattr(
        "it_toolbox.widgets.rclone_browser_widget.rclone_client.list_directory",
        lambda remote, path: [],
    )

    view._open_browser(remotes[0])

    assert view._tabs.count() == 1


def test_closing_a_browser_tab_removes_it(qtbot, monkeypatch):
    remotes = [RemoteConfig(name="myLocal", type="local")]
    view = _make_view(qtbot, monkeypatch, remotes=remotes)
    monkeypatch.setattr(
        "it_toolbox.widgets.rclone_browser_widget.rclone_client.list_directory",
        lambda remote, path: [],
    )
    view._open_browser(remotes[0])
    assert view._tabs.count() == 1

    widget = view._tabs.widget(0)
    assert view.try_close_tab(widget) is True
    assert view._tabs.count() == 0


def test_removing_a_remote_deletes_it_and_refreshes(qtbot, monkeypatch):
    remotes = [RemoteConfig(name="myLocal", type="local")]
    view = _make_view(qtbot, monkeypatch, remotes=remotes)
    root = view._tree.topLevelItem(0)
    qtbot.waitUntil(lambda: root.childCount() == 1, timeout=1000)
    category = root.child(0)
    qtbot.waitUntil(lambda: category.childCount() == 1, timeout=1000)

    deleted = []
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.rclone_client.delete_remote",
        lambda name: deleted.append(name),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    remotes.clear()

    view._remove_remote(category.child(0).data(0, REMOTE_ROLE))

    qtbot.waitUntil(lambda: deleted == ["myLocal"], timeout=1000)
    qtbot.waitUntil(lambda: root.childCount() == 0, timeout=1000)

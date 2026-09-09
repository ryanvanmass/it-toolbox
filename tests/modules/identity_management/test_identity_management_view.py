from PySide6.QtCore import QUrl

from it_toolbox.modules.identity_management.models import Device, User
from it_toolbox.modules.identity_management.ui.main_view import (
    DEVICE_ROLE,
    USER_ROLE,
    IdentityManagementView,
)


class _FakePath:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def is_file(self) -> bool:
        return self._exists


def _make_view(qtbot, monkeypatch, api_key="jca_test", devices=(), users=()):
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.settings.load_jumpcloud_api_key",
        lambda: api_key,
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.settings.jumpcloud_api_key_path",
        lambda: _FakePath(exists=api_key is not None),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.list_devices",
        lambda key: list(devices),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.list_users",
        lambda key: list(users),
    )
    view = IdentityManagementView()
    qtbot.addWidget(view)
    return view


def test_devices_populate_as_tree_children(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows", hostname="alpha-host"),
        Device(id="d2", display_name="beta", os="linux", hostname="beta-host"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)

    qtbot.waitUntil(lambda: view._devices_category.childCount() == 2, timeout=2000)
    assert view._devices_category.child(0).text(0) == "alpha"
    assert view._devices_category.child(0).data(0, DEVICE_ROLE) == devices[0]
    assert view._devices_category.child(1).text(0) == "beta"


def test_devices_category_shows_placeholder_when_empty(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, devices=[])

    qtbot.waitUntil(
        lambda: view._devices_category.child(0).text(0) == "No devices found.", timeout=2000
    )


def test_users_populate_as_tree_children(qtbot, monkeypatch):
    users = [User(id="u1", username="alice", email="alice@example.com")]
    view = _make_view(qtbot, monkeypatch, users=users)

    # A single real user collides in count with the "Loading…" placeholder
    # refresh() adds synchronously up front (both are exactly 1 child) —
    # wait for the actual data role instead of just a child count.
    qtbot.waitUntil(
        lambda: view._users_category.child(0).data(0, USER_ROLE) is not None, timeout=2000
    )
    assert view._users_category.child(0).text(0) == "alice"
    assert view._users_category.child(0).data(0, USER_ROLE) == users[0]


# -- Search -------------------------------------------------------------


def test_search_hides_non_matching_devices(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_category.childCount() == 2, timeout=2000)

    view._search_box.setText("alp")

    assert not view._devices_category.child(0).isHidden()  # alpha
    assert view._devices_category.child(1).isHidden()  # beta


def test_search_hides_non_matching_users(qtbot, monkeypatch):
    users = [
        User(id="u1", username="alice", email="alice@example.com"),
        User(id="u2", username="bob", email="bob@example.com"),
    ]
    view = _make_view(qtbot, monkeypatch, users=users)
    qtbot.waitUntil(lambda: view._users_category.childCount() == 2, timeout=2000)

    view._search_box.setText("ali")

    assert not view._users_category.child(0).isHidden()  # alice
    assert view._users_category.child(1).isHidden()  # bob


def test_search_is_case_insensitive(qtbot, monkeypatch):
    devices = [Device(id="d1", display_name="AlphaHost", os="windows")]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(
        lambda: view._devices_category.child(0).data(0, DEVICE_ROLE) is not None, timeout=2000
    )

    view._search_box.setText("alphahost")

    assert not view._devices_category.child(0).isHidden()


def test_search_hides_a_category_with_no_matches(qtbot, monkeypatch):
    devices = [Device(id="d1", display_name="alpha", os="windows")]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(
        lambda: view._devices_category.child(0).data(0, DEVICE_ROLE) is not None, timeout=2000
    )

    view._search_box.setText("no-such-device")

    assert view._devices_category.isHidden()


def test_clearing_search_shows_everything_again(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_category.childCount() == 2, timeout=2000)
    view._search_box.setText("alp")
    assert view._devices_category.child(1).isHidden()

    view._search_box.setText("")

    assert not view._devices_category.child(0).isHidden()
    assert not view._devices_category.child(1).isHidden()
    assert not view._devices_category.isHidden()


def test_search_is_reapplied_after_refresh(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_category.childCount() == 2, timeout=2000)
    view._search_box.setText("alp")
    qtbot.waitUntil(lambda: view._devices_category.child(1).isHidden())

    view.refresh()
    qtbot.waitUntil(lambda: view._devices_category.childCount() == 2, timeout=2000)

    assert not view._devices_category.child(0).isHidden()  # alpha
    assert view._devices_category.child(1).isHidden()  # beta, still filtered out


def test_selecting_a_device_renders_partial_then_backfills_detail(qtbot, monkeypatch):
    device = Device(id="d1", display_name="alpha", os="windows", hostname="alpha-host")
    detail = Device(
        id="d1",
        display_name="alpha",
        os="windows",
        hostname="alpha-host",
        os_version="10.0.19045",
        serial_number="ABC123",
        agent_version="1.2.3",
        last_contact="2026-09-05T00:00:00Z",
    )
    view = _make_view(qtbot, monkeypatch, devices=[device])
    # A single real device collides in count with the "Loading…"
    # placeholder refresh() adds synchronously up front (both are exactly
    # 1 child) — wait for the actual data role instead of just a count.
    qtbot.waitUntil(
        lambda: view._devices_category.child(0).data(0, DEVICE_ROLE) is not None, timeout=2000
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.get_device",
        lambda key, device_id: detail,
    )

    view._tree.setCurrentItem(view._devices_category.child(0))

    assert view._stack.currentIndex() == 1
    assert view._device_fields["hostname"].text() == "alpha-host"
    qtbot.waitUntil(
        lambda: view._device_fields["serial_number"].text() == "ABC123", timeout=2000
    )
    assert view._device_fields["os_version"].text() == "10.0.19045"
    assert view._device_fields["agent_version"].text() == "1.2.3"


def test_clearing_selection_shows_the_placeholder_page(qtbot, monkeypatch):
    device = Device(id="d1", display_name="alpha", os="windows")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    # A single real device collides in count with the "Loading…"
    # placeholder refresh() adds synchronously up front (both are exactly
    # 1 child) — wait for the actual data role instead of just a count.
    qtbot.waitUntil(
        lambda: view._devices_category.child(0).data(0, DEVICE_ROLE) is not None, timeout=2000
    )
    view._tree.setCurrentItem(view._devices_category.child(0))
    assert view._stack.currentIndex() == 1

    view._tree.setCurrentItem(None)

    assert view._stack.currentIndex() == 0


def test_selecting_a_user_renders_synchronously_from_tree_item_data(qtbot, monkeypatch):
    user = User(
        id="u1",
        username="alice",
        email="alice@example.com",
        first_name="Alice",
        last_name="Anderson",
        suspended=True,
    )
    view = _make_view(qtbot, monkeypatch, users=[user])
    qtbot.waitUntil(
        lambda: view._users_category.child(0).data(0, USER_ROLE) is not None, timeout=2000
    )

    view._tree.setCurrentItem(view._users_category.child(0))

    assert view._stack.currentIndex() == 2
    assert view._user_fields["first_name"].text() == "Alice"
    assert view._user_fields["last_name"].text() == "Anderson"
    assert view._user_fields["suspended"].text() == "Yes"


def test_launch_remote_assist_opens_the_device_console_url(qtbot, monkeypatch):
    device = Device(id="d1", display_name="alpha", os="windows")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    # A single real device collides in count with the "Loading…"
    # placeholder refresh() adds synchronously up front (both are exactly
    # 1 child) — wait for the actual data role instead of just a count.
    qtbot.waitUntil(
        lambda: view._devices_category.child(0).data(0, DEVICE_ROLE) is not None, timeout=2000
    )
    view._tree.setCurrentItem(view._devices_category.child(0))

    opened = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.QDesktopServices.openUrl",
        lambda url: opened.append(url),
    )

    view._on_launch_remote_assist_clicked()

    assert opened == [QUrl("https://console.jumpcloud.com/devices/d1")]


def test_launch_remote_assist_does_nothing_without_a_selection(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    opened = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.QDesktopServices.openUrl",
        lambda url: opened.append(url),
    )

    view._on_launch_remote_assist_clicked()

    assert opened == []


def test_refresh_shows_placeholder_when_no_api_key_configured(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.list_devices",
        lambda key: calls.append(key) or [],
    )
    view = _make_view(qtbot, monkeypatch, api_key=None)

    assert calls == []  # never called — no key means no API traffic at all
    assert "No JumpCloud API key configured" in view._devices_category.child(0).text(0)
    assert "No JumpCloud API key configured" in view._users_category.child(0).text(0)


def test_jumpcloud_root_menu_offers_only_refresh(qtbot, monkeypatch):
    # _build_jumpcloud_root_menu is split out precisely so this can be
    # checked without ever calling QMenu.exec() — see its docstring and
    # app.py's _build_session_tab_menu, which hit the same "monkeypatching
    # exec() hangs the test" problem this split avoids. Setting the API
    # key itself moved to the Settings page — this menu is action-only now.
    view = _make_view(qtbot, monkeypatch)

    menu = view._build_jumpcloud_root_menu()

    assert [a.text() for a in menu.actions()] == ["Refresh"]


def test_populate_device_detail_after_teardown_does_not_raise(qtbot, monkeypatch):
    # Exercises the try/except RuntimeError guard: a get_device() result
    # can arrive after the widget backing it was already torn down —
    # simulated here without an actual Qt-level deletion (which would
    # conflict with qtbot's own widget-close-at-teardown tracking) by
    # having a field widget raise the same RuntimeError Qt itself would.
    device = Device(id="d1", display_name="alpha", os="windows")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    # A single real device collides in count with the "Loading…"
    # placeholder refresh() adds synchronously up front (both are exactly
    # 1 child) — wait for the actual data role instead of just a count.
    qtbot.waitUntil(
        lambda: view._devices_category.child(0).data(0, DEVICE_ROLE) is not None, timeout=2000
    )
    view._tree.setCurrentItem(view._devices_category.child(0))

    def _raise_deleted(*args, **kwargs):
        raise RuntimeError("Internal C++ object already deleted.")

    monkeypatch.setattr(view._device_fields["os_version"], "setText", _raise_deleted)

    detail = Device(id="d1", display_name="alpha", os="windows", os_version="1.0")
    view._populate_device_detail(detail)  # must not raise

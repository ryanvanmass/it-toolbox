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


def test_devices_table_populates_from_list_devices(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows", hostname="alpha-host"),
        Device(id="d2", display_name="beta", os="linux", hostname="beta-host"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)

    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)
    assert view._devices_table.item(0, 0).text() == "alpha"
    assert view._devices_table.item(0, 1).text() == "windows"
    assert view._devices_table.item(0, 0).data(DEVICE_ROLE) == devices[0]


def test_users_table_populates_from_list_users(qtbot, monkeypatch):
    users = [User(id="u1", username="alice", email="alice@example.com")]
    view = _make_view(qtbot, monkeypatch, users=users)

    qtbot.waitUntil(lambda: view._users_table.rowCount() == 1, timeout=2000)
    assert view._users_table.item(0, 0).text() == "alice"
    assert view._users_table.item(0, 0).data(USER_ROLE) == users[0]


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
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.get_device",
        lambda key, device_id: detail,
    )

    view._devices_table.setCurrentCell(0, 0)

    assert view._device_detail_panel.isEnabled()
    assert view._device_fields["hostname"].text() == "alpha-host"
    qtbot.waitUntil(
        lambda: view._device_fields["serial_number"].text() == "ABC123", timeout=2000
    )
    assert view._device_fields["os_version"].text() == "10.0.19045"
    assert view._device_fields["agent_version"].text() == "1.2.3"


def test_clearing_device_selection_disables_detail_panel(qtbot, monkeypatch):
    device = Device(id="d1", display_name="alpha", os="windows")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)
    view._devices_table.setCurrentCell(0, 0)
    assert view._device_detail_panel.isEnabled()

    view._devices_table.setCurrentCell(-1, -1)

    assert not view._device_detail_panel.isEnabled()


def test_selecting_a_user_renders_synchronously_from_row_data(qtbot, monkeypatch):
    user = User(
        id="u1",
        username="alice",
        email="alice@example.com",
        first_name="Alice",
        last_name="Anderson",
        suspended=True,
    )
    view = _make_view(qtbot, monkeypatch, users=[user])
    qtbot.waitUntil(lambda: view._users_table.rowCount() == 1, timeout=2000)

    view._users_table.setCurrentCell(0, 0)

    assert view._user_detail_panel.isEnabled()
    assert view._user_fields["first_name"].text() == "Alice"
    assert view._user_fields["last_name"].text() == "Anderson"
    assert view._user_fields["suspended"].text() == "Yes"


def test_launch_remote_assist_opens_the_device_console_url(qtbot, monkeypatch):
    device = Device(id="d1", display_name="alpha", os="windows")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)
    view._devices_table.setCurrentCell(0, 0)

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
    assert "No JumpCloud API key configured" in view._device_status_label.text()
    assert "No JumpCloud API key configured" in view._user_status_label.text()


def test_context_menu_offers_set_key_when_unconfigured(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, api_key=None)

    menu = view.build_context_menu(view)

    assert [a.text() for a in menu.actions()] == ["Set JumpCloud API Key…", "Refresh"]


def test_context_menu_offers_change_key_when_configured(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    menu = view.build_context_menu(view)

    assert [a.text() for a in menu.actions()] == ["Change JumpCloud API Key…", "Refresh"]


def test_populate_device_detail_after_teardown_does_not_raise(qtbot, monkeypatch):
    # Exercises the try/except RuntimeError guard: a get_device() result
    # can arrive after the widget backing it was already torn down —
    # simulated here without an actual Qt-level deletion (which would
    # conflict with qtbot's own widget-close-at-teardown tracking) by
    # having a field widget raise the same RuntimeError Qt itself would.
    device = Device(id="d1", display_name="alpha", os="windows")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)
    view._devices_table.setCurrentCell(0, 0)

    def _raise_deleted(*args, **kwargs):
        raise RuntimeError("Internal C++ object already deleted.")

    monkeypatch.setattr(view._device_fields["os_version"], "setText", _raise_deleted)

    detail = Device(id="d1", display_name="alpha", os="windows", os_version="1.0")
    view._populate_device_detail(detail)  # must not raise

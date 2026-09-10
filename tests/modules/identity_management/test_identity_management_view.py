from PySide6.QtWidgets import QMessageBox

import it_toolbox.modules.identity_management.ui.main_view as main_view_module
from it_toolbox.modules.connection_manager.models import GcpIamBinding, GcpProject
from it_toolbox.modules.identity_management.models import Device, User
from it_toolbox.modules.identity_management.ui.main_view import (
    DEVICE_ROLE,
    GCP_PROJECT_ROLE,
    PAGE_DEVICE_DETAIL,
    PAGE_DEVICES_TABLE,
    PAGE_GCP_PROJECT_DETAIL,
    PAGE_GCP_PROJECTS_TABLE,
    PAGE_PLACEHOLDER,
    PAGE_USER_DETAIL,
    PAGE_USERS_TABLE,
    USER_ROLE,
    IdentityManagementView,
)


class _FakePath:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def is_file(self) -> bool:
        return self._exists


def _make_view(
    qtbot,
    monkeypatch,
    api_key="jca_test",
    devices=(),
    users=(),
    gcp_available=False,
    gcp_account=None,
    gcp_projects=(),
):
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
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_auth.is_available",
        lambda: gcp_available,
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_auth.get_active_account",
        lambda: gcp_account,
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_auth.get_credentials",
        lambda: object(),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.list_projects",
        lambda credentials: list(gcp_projects),
    )
    view = IdentityManagementView()
    qtbot.addWidget(view)
    return view


# -- Populating the tables (not the tree) --------------------------------


def test_devices_populate_the_table_and_not_the_tree(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows", hostname="alpha-host"),
        Device(id="d2", display_name="beta", os="linux", hostname="beta-host"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)

    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)
    assert view._devices_table.item(0, 0).text() == "alpha"
    assert view._devices_table.item(0, 0).data(DEVICE_ROLE) == devices[0]
    assert view._devices_table.item(0, 1).text() == "windows"
    assert view._devices_table.item(1, 0).text() == "beta"
    # The tree is deliberately uncluttered — no permanent children.
    assert view._devices_category.childCount() == 0


def test_devices_table_shows_a_status_message_when_empty(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, devices=[])

    qtbot.waitUntil(
        lambda: view._devices_table_status_label.text() == "No devices found.", timeout=2000
    )


def test_users_populate_the_table_and_not_the_tree(qtbot, monkeypatch):
    users = [User(id="u1", username="alice", email="alice@example.com")]
    view = _make_view(qtbot, monkeypatch, users=users)

    qtbot.waitUntil(lambda: view._users_table.rowCount() == 1, timeout=2000)
    assert view._users_table.item(0, 0).text() == "alice"
    assert view._users_table.item(0, 0).data(USER_ROLE) == users[0]
    assert view._users_table.item(0, 1).text() == "alice@example.com"
    assert view._users_category.childCount() == 0


# -- Clicking a category shows its table ---------------------------------


def test_clicking_devices_category_shows_the_devices_table(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    view._on_tree_item_clicked(view._devices_category, 0)

    assert view._stack.currentIndex() == PAGE_DEVICES_TABLE


def test_clicking_users_category_shows_the_users_table(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    view._on_tree_item_clicked(view._users_category, 0)

    assert view._stack.currentIndex() == PAGE_USERS_TABLE


def test_clicking_the_jumpcloud_root_shows_the_placeholder_page(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._on_tree_item_clicked(view._devices_category, 0)  # move off the default page first

    view._on_tree_item_clicked(view._jumpcloud_root, 0)

    assert view._stack.currentIndex() == PAGE_PLACEHOLDER


# -- Clicking a table row shows its detail --------------------------------


def test_clicking_a_device_table_row_shows_its_detail(qtbot, monkeypatch):
    device = Device(id="d1", display_name="alpha", os="windows", hostname="alpha-host")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)

    view._devices_table.setCurrentCell(0, 0)

    assert view._stack.currentIndex() == PAGE_DEVICE_DETAIL
    assert view._device_fields["hostname"].text() == "alpha-host"


def test_clicking_a_user_table_row_shows_its_detail(qtbot, monkeypatch):
    user = User(id="u1", username="alice", email="alice@example.com", first_name="Alice")
    view = _make_view(qtbot, monkeypatch, users=[user])
    qtbot.waitUntil(lambda: view._users_table.rowCount() == 1, timeout=2000)

    view._users_table.setCurrentCell(0, 0)

    assert view._stack.currentIndex() == PAGE_USER_DETAIL
    assert view._user_fields["first_name"].text() == "Alice"


# -- Search -------------------------------------------------------------


def test_search_creates_matching_tree_leaves(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)
    assert view._devices_category.childCount() == 0  # nothing until searching

    view._search_box.setText("alp")

    assert view._devices_category.childCount() == 1
    assert view._devices_category.child(0).text(0) == "alpha"
    assert view._devices_category.child(0).data(0, DEVICE_ROLE) == devices[0]


def test_search_matches_users_too(qtbot, monkeypatch):
    users = [
        User(id="u1", username="alice", email="alice@example.com"),
        User(id="u2", username="bob", email="bob@example.com"),
    ]
    view = _make_view(qtbot, monkeypatch, users=users)
    qtbot.waitUntil(lambda: view._users_table.rowCount() == 2, timeout=2000)

    view._search_box.setText("ali")

    assert view._users_category.childCount() == 1
    assert view._users_category.child(0).text(0) == "alice"
    assert view._users_category.child(0).data(0, USER_ROLE) == users[0]


def test_search_is_case_insensitive(qtbot, monkeypatch):
    devices = [Device(id="d1", display_name="AlphaHost", os="windows")]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)

    view._search_box.setText("alphahost")

    assert view._devices_category.childCount() == 1


def test_search_hides_a_category_with_no_matches(qtbot, monkeypatch):
    devices = [Device(id="d1", display_name="alpha", os="windows")]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)

    view._search_box.setText("no-such-device")

    assert view._devices_category.childCount() == 0
    assert view._devices_category.isHidden()


def test_clearing_search_removes_the_leaves_again(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)
    view._search_box.setText("alp")
    assert view._devices_category.childCount() == 1

    view._search_box.setText("")

    assert view._devices_category.childCount() == 0
    assert not view._devices_category.isHidden()


def test_selecting_a_device_search_result_shows_its_detail(qtbot, monkeypatch):
    device = Device(id="d1", display_name="alpha", os="windows", hostname="alpha-host")
    view = _make_view(qtbot, monkeypatch, devices=[device])
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)
    view._search_box.setText("alp")
    assert view._devices_category.childCount() == 1

    view._on_tree_item_clicked(view._devices_category.child(0), 0)

    assert view._stack.currentIndex() == PAGE_DEVICE_DETAIL
    assert view._device_fields["hostname"].text() == "alpha-host"


def test_selecting_a_user_search_result_shows_its_detail(qtbot, monkeypatch):
    user = User(id="u1", username="alice", email="alice@example.com", first_name="Alice")
    view = _make_view(qtbot, monkeypatch, users=[user])
    qtbot.waitUntil(lambda: view._users_table.rowCount() == 1, timeout=2000)
    view._search_box.setText("ali")

    view._on_tree_item_clicked(view._users_category.child(0), 0)

    assert view._stack.currentIndex() == PAGE_USER_DETAIL
    assert view._user_fields["first_name"].text() == "Alice"


def test_search_filters_the_devices_table_rows(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)

    view._search_box.setText("alp")

    assert not view._devices_table.isRowHidden(0)  # alpha
    assert view._devices_table.isRowHidden(1)  # beta


def test_search_filters_the_users_table_rows(qtbot, monkeypatch):
    users = [
        User(id="u1", username="alice", email="alice@example.com"),
        User(id="u2", username="bob", email="bob@example.com"),
    ]
    view = _make_view(qtbot, monkeypatch, users=users)
    qtbot.waitUntil(lambda: view._users_table.rowCount() == 2, timeout=2000)

    view._search_box.setText("ali")

    assert not view._users_table.isRowHidden(0)  # alice
    assert view._users_table.isRowHidden(1)  # bob


def test_clearing_search_shows_all_table_rows_again(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)
    view._search_box.setText("alp")
    assert view._devices_table.isRowHidden(1)

    view._search_box.setText("")

    assert not view._devices_table.isRowHidden(0)
    assert not view._devices_table.isRowHidden(1)


def test_search_is_reapplied_after_refresh(qtbot, monkeypatch):
    devices = [
        Device(id="d1", display_name="alpha", os="windows"),
        Device(id="d2", display_name="beta", os="linux"),
    ]
    view = _make_view(qtbot, monkeypatch, devices=devices)
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)
    view._search_box.setText("alp")
    qtbot.waitUntil(lambda: view._devices_category.childCount() == 1)

    view.refresh()
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 2, timeout=2000)

    # Still filtered down to just the matching result, not reset to
    # everything, even though the whole table was reloaded.
    assert view._devices_category.childCount() == 1
    assert view._devices_category.child(0).text(0) == "alpha"


# -- Detail panels --------------------------------------------------------


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

    assert view._stack.currentIndex() == PAGE_DEVICE_DETAIL
    assert view._device_fields["hostname"].text() == "alpha-host"
    qtbot.waitUntil(
        lambda: view._device_fields["serial_number"].text() == "ABC123", timeout=2000
    )
    assert view._device_fields["os_version"].text() == "10.0.19045"
    assert view._device_fields["agent_version"].text() == "1.2.3"


def test_selecting_a_device_shows_general_info_fields(qtbot, monkeypatch):
    device = Device(
        id="d1", display_name="alpha", os="windows", hostname="alpha-host", active=False
    )
    detail = Device(
        id="d1",
        display_name="alpha",
        os="windows",
        hostname="alpha-host",
        active=False,
        created="2025-01-01T00:00:00Z",
        remote_ip="203.0.113.5",
        arch="x86_64",
        description="Finance laptop",
    )
    view = _make_view(qtbot, monkeypatch, devices=[device])
    qtbot.waitUntil(lambda: view._devices_table.rowCount() == 1, timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.get_device",
        lambda key, device_id: detail,
    )

    view._devices_table.setCurrentCell(0, 0)

    assert view._device_fields["status"].text() == "Inactive"
    qtbot.waitUntil(
        lambda: view._device_fields["description"].text() == "Finance laptop", timeout=2000
    )
    assert view._device_fields["created"].text() == "2025-01-01T00:00:00Z"
    assert view._device_fields["remote_ip"].text() == "203.0.113.5"
    assert view._device_fields["arch"].text() == "x86_64"


def test_selecting_a_user_shows_general_info_fields(qtbot, monkeypatch):
    user = User(
        id="u1",
        username="alice",
        email="alice@example.com",
        job_title="Engineer",
        department="R&D",
        activated=False,
        mfa_configured=True,
        created="2024-06-01T00:00:00Z",
    )
    view = _make_view(qtbot, monkeypatch, users=[user])
    qtbot.waitUntil(lambda: view._users_table.rowCount() == 1, timeout=2000)

    view._users_table.setCurrentCell(0, 0)

    assert view._user_fields["email"].text() == "alice@example.com"
    assert view._user_fields["job_title"].text() == "Engineer"
    assert view._user_fields["department"].text() == "R&D"
    assert view._user_fields["activated"].text() == "No"
    assert view._user_fields["mfa_configured"].text() == "Yes"
    assert view._user_fields["created"].text() == "2024-06-01T00:00:00Z"


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

    assert view._stack.currentIndex() == PAGE_USER_DETAIL
    assert view._user_fields["first_name"].text() == "Alice"
    assert view._user_fields["last_name"].text() == "Anderson"
    assert view._user_fields["suspended"].text() == "Yes"


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


# -- API key / refresh / context menu --------------------------------------


def test_refresh_shows_status_message_when_no_api_key_configured(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.list_devices",
        lambda key: calls.append(key) or [],
    )
    view = _make_view(qtbot, monkeypatch, api_key=None)

    assert calls == []  # never called — no key means no API traffic at all
    assert "No JumpCloud API key configured" in view._devices_table_status_label.text()
    assert "No JumpCloud API key configured" in view._users_table_status_label.text()


def test_jumpcloud_root_menu_offers_only_refresh(qtbot, monkeypatch):
    # _build_jumpcloud_root_menu is split out precisely so this can be
    # checked without ever calling QMenu.exec() — see its docstring and
    # app.py's _build_session_tab_menu, which hit the same "monkeypatching
    # exec() hangs the test" problem this split avoids. Setting the API
    # key itself moved to the Settings page — this menu is action-only now.
    view = _make_view(qtbot, monkeypatch)

    menu = view._build_jumpcloud_root_menu()

    assert [a.text() for a in menu.actions()] == ["Refresh"]


# -- Periodic auto-refresh -----------------------------------------------


def test_refresh_timer_is_active_with_the_expected_interval(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    assert view._refresh_timer.isActive()
    assert view._refresh_timer.interval() == main_view_module.REFRESH_INTERVAL_MS


def test_refresh_timer_firing_reloads_devices_and_users(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    # The __init__-time refresh() call's background list_devices task is
    # only *queued* when _make_view() returns, not necessarily finished —
    # wait for it to actually settle before installing a second mock
    # below, or that first (still in-flight) call can pick up the new
    # mock too once it finally runs, double-counting against it.
    qtbot.waitUntil(
        lambda: view._devices_table_status_label.text() == "No devices found.", timeout=2000
    )

    # Applied after _make_view() rather than before — _make_view() sets
    # its own default list_devices mock, which would otherwise overwrite
    # this one instead of the other way around.
    calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.jumpcloud_client.list_devices",
        lambda key: calls.append("devices") or [],
    )

    view._refresh_timer.timeout.emit()

    qtbot.waitUntil(lambda: calls == ["devices"], timeout=2000)


# -- GCP: sign-in state -----------------------------------------------------


def test_gcp_shows_gcloud_not_found_message_when_unavailable(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcp_available=False)

    assert "gcloud CLI not found" in view._gcp_projects_status_label.text()
    assert view._gcp_sign_in_button.isHidden()


def test_gcp_shows_sign_in_prompt_when_signed_out(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcp_available=True, gcp_account=None)

    qtbot.waitUntil(
        lambda: "Sign in with Google" in view._gcp_projects_status_label.text(), timeout=2000
    )
    assert not view._gcp_sign_in_button.isHidden()


def test_gcp_signs_in_automatically_when_already_authenticated(qtbot, monkeypatch):
    projects = [GcpProject(project_id="proj-1", display_name="Project One")]
    view = _make_view(
        qtbot,
        monkeypatch,
        gcp_available=True,
        gcp_account="alice@example.com",
        gcp_projects=projects,
    )

    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)
    assert view._gcp_signed_in is True
    assert view._gcp_sign_in_button.isHidden()


def test_gcp_sign_in_button_click_populates_projects(qtbot, monkeypatch):
    projects = [GcpProject(project_id="proj-1", display_name="Project One")]
    view = _make_view(qtbot, monkeypatch, gcp_available=True, gcp_account=None)
    qtbot.waitUntil(lambda: not view._gcp_sign_in_button.isHidden(), timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_auth.sign_in",
        lambda: "alice@example.com",
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.list_projects",
        lambda credentials: list(projects),
    )

    view._on_gcp_sign_in_clicked()

    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)
    assert view._gcp_signed_in is True


def test_gcp_sign_out_clears_projects(qtbot, monkeypatch):
    projects = [GcpProject(project_id="proj-1", display_name="Project One")]
    view = _make_view(
        qtbot,
        monkeypatch,
        gcp_available=True,
        gcp_account="alice@example.com",
        gcp_projects=projects,
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_auth.sign_out",
        lambda: None,
    )

    view._do_gcp_sign_out()

    qtbot.waitUntil(lambda: view._gcp_signed_in is False, timeout=2000)
    assert view._gcp_projects_table.rowCount() == 0
    assert not view._gcp_sign_in_button.isHidden()


def test_gcp_root_menu_is_none_when_signed_out(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcp_available=True, gcp_account=None)
    qtbot.waitUntil(lambda: view._gcp_signed_in is False, timeout=2000)

    assert view._build_gcp_root_menu() is None


def test_gcp_root_menu_offers_refresh_and_sign_out_when_signed_in(qtbot, monkeypatch):
    projects = [GcpProject(project_id="proj-1", display_name="Project One")]
    view = _make_view(
        qtbot,
        monkeypatch,
        gcp_available=True,
        gcp_account="alice@example.com",
        gcp_projects=projects,
    )
    qtbot.waitUntil(lambda: view._gcp_signed_in is True, timeout=2000)

    menu = view._build_gcp_root_menu()

    assert [a.text() for a in menu.actions()] == ["Refresh", "Sign out"]


# -- GCP: projects table / tree ----------------------------------------------


def test_gcp_projects_populate_the_table_and_not_the_tree(qtbot, monkeypatch):
    projects = [
        GcpProject(project_id="proj-a", display_name="Alpha"),
        GcpProject(project_id="proj-b", display_name="Beta"),
    ]
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=projects
    )

    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 2, timeout=2000)
    assert view._gcp_projects_table.item(0, 0).text() == "Alpha"
    assert view._gcp_projects_table.item(0, 0).data(GCP_PROJECT_ROLE) == projects[0]
    assert view._gcp_projects_table.item(0, 1).text() == "proj-a"
    assert view._gcp_projects_category.childCount() == 0


def test_clicking_gcp_projects_category_shows_the_projects_table(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    view._on_tree_item_clicked(view._gcp_projects_category, 0)

    assert view._stack.currentIndex() == PAGE_GCP_PROJECTS_TABLE


def test_clicking_the_gcp_root_shows_the_placeholder_page(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._on_tree_item_clicked(view._gcp_projects_category, 0)  # move off the default page first

    view._on_tree_item_clicked(view._gcp_root, 0)

    assert view._stack.currentIndex() == PAGE_PLACEHOLDER


def test_gcp_project_search_creates_matching_tree_leaf(qtbot, monkeypatch):
    projects = [
        GcpProject(project_id="proj-a", display_name="Alpha"),
        GcpProject(project_id="proj-b", display_name="Beta"),
    ]
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=projects
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 2, timeout=2000)

    view._search_box.setText("alp")

    assert view._gcp_projects_category.childCount() == 1
    assert view._gcp_projects_category.child(0).text(0) == "Alpha"
    assert view._gcp_projects_category.child(0).data(0, GCP_PROJECT_ROLE) == projects[0]


def test_gcp_project_search_filters_the_projects_table_rows(qtbot, monkeypatch):
    projects = [
        GcpProject(project_id="proj-a", display_name="Alpha"),
        GcpProject(project_id="proj-b", display_name="Beta"),
    ]
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=projects
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 2, timeout=2000)

    view._search_box.setText("alp")

    assert not view._gcp_projects_table.isRowHidden(0)  # Alpha
    assert view._gcp_projects_table.isRowHidden(1)  # Beta


# -- GCP: project IAM detail --------------------------------------------------


def test_selecting_a_gcp_project_row_shows_its_iam_bindings(qtbot, monkeypatch):
    project = GcpProject(project_id="proj-a", display_name="Alpha")
    bindings = [
        GcpIamBinding(project_id="proj-a", role="roles/owner", member="user:alice@example.com"),
        GcpIamBinding(
            project_id="proj-a", role="roles/viewer", member="serviceAccount:svc@proj-a.iam.gserviceaccount.com"
        ),
    ]
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=[project]
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.get_iam_policy",
        lambda credentials, project_id: list(bindings),
    )

    view._gcp_projects_table.setCurrentCell(0, 0)

    assert view._stack.currentIndex() == PAGE_GCP_PROJECT_DETAIL
    qtbot.waitUntil(lambda: view._gcp_bindings_table.rowCount() == 2, timeout=2000)
    assert view._gcp_bindings_table.item(0, 0).text() == "alice@example.com"
    assert view._gcp_bindings_table.item(0, 1).text() == "User"
    assert view._gcp_bindings_table.item(0, 2).text() == "roles/owner"
    assert view._gcp_bindings_table.item(1, 1).text() == "Service Account"


def test_selecting_a_gcp_project_search_result_shows_its_iam_bindings(qtbot, monkeypatch):
    project = GcpProject(project_id="proj-a", display_name="Alpha")
    bindings = [
        GcpIamBinding(project_id="proj-a", role="roles/owner", member="user:alice@example.com")
    ]
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=[project]
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.get_iam_policy",
        lambda credentials, project_id: list(bindings),
    )
    view._search_box.setText("alp")

    view._on_tree_item_clicked(view._gcp_projects_category.child(0), 0)

    assert view._stack.currentIndex() == PAGE_GCP_PROJECT_DETAIL
    qtbot.waitUntil(lambda: view._gcp_bindings_table.rowCount() == 1, timeout=2000)


def test_gcp_project_detail_shows_status_message_when_no_bindings(qtbot, monkeypatch):
    project = GcpProject(project_id="proj-a", display_name="Alpha")
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=[project]
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.get_iam_policy",
        lambda credentials, project_id: [],
    )

    view._gcp_projects_table.setCurrentCell(0, 0)

    qtbot.waitUntil(
        lambda: view._gcp_bindings_status_label.text() == "No IAM bindings found.", timeout=2000
    )


def test_gcp_project_detail_local_filter_matches_principal_or_role(qtbot, monkeypatch):
    project = GcpProject(project_id="proj-a", display_name="Alpha")
    bindings = [
        GcpIamBinding(project_id="proj-a", role="roles/owner", member="user:alice@example.com"),
        GcpIamBinding(project_id="proj-a", role="roles/viewer", member="user:bob@example.com"),
    ]
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=[project]
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.get_iam_policy",
        lambda credentials, project_id: list(bindings),
    )
    view._gcp_projects_table.setCurrentCell(0, 0)
    qtbot.waitUntil(lambda: view._gcp_bindings_table.rowCount() == 2, timeout=2000)

    view._gcp_bindings_filter_box.setText("owner")

    assert view._gcp_bindings_table.rowCount() == 1
    assert view._gcp_bindings_table.item(0, 2).text() == "roles/owner"

    view._gcp_bindings_filter_box.setText("bob")

    assert view._gcp_bindings_table.rowCount() == 1
    assert view._gcp_bindings_table.item(0, 0).text() == "bob@example.com"


def test_gcp_iam_load_error_shows_a_message_box(qtbot, monkeypatch):
    project = GcpProject(project_id="proj-a", display_name="Alpha")
    view = _make_view(
        qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com", gcp_projects=[project]
    )
    qtbot.waitUntil(lambda: view._gcp_projects_table.rowCount() == 1, timeout=2000)

    def _raise(credentials, project_id):
        raise main_view_module.gcp_client.GcpApiError("403 permission denied")

    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.get_iam_policy", _raise
    )
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: calls.append(a)))

    view._gcp_projects_table.setCurrentCell(0, 0)

    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)
    assert "permission denied" in calls[0][2]


def test_gcp_projects_load_error_shows_a_message_box(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcp_available=True, gcp_account="alice@example.com")
    # The __init__-time sign-in's background list_projects task is only
    # *queued* when _make_view() returns — wait for it to settle before
    # installing a second mock, same reasoning as
    # test_refresh_timer_firing_reloads_devices_and_users above.
    qtbot.waitUntil(
        lambda: view._gcp_projects_status_label.text() == "No projects found.", timeout=2000
    )

    def _raise(credentials):
        raise main_view_module.gcp_client.GcpApiError("boom")

    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.gcp_client.list_projects", _raise
    )
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: calls.append(a)))

    view._refresh_gcp_projects()

    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)

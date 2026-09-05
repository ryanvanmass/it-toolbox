import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from it_toolbox.modules.connection_manager.models import (
    GcpProject,
    GcsBucket,
    Instance,
    ManualConnection,
    QemuHost,
    QemuVm,
)
from it_toolbox.modules.connection_manager.ui.main_view import ConnectionManagerView
from it_toolbox.widgets.terminal_widget import TerminalWidget


class _FakeTunnel:
    def __init__(self, port=2222):
        self.port = port
        self.stopped = False

    def start(self):
        return self.port

    def stop(self, timeout=5):
        self.stopped = True


def _make_view(
    qtbot, monkeypatch, qemu_hosts=(), manual_connections=(), instances=(), buckets=()
):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.is_available",
        lambda: False,
    )
    # QEMU hosts and manual connections are loaded unconditionally
    # (independent of GCP sign-in) — stub both out so tests don't depend
    # on this machine's real qemu_hosts.json/manual_connections.json.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.settings.load_qemu_hosts",
        lambda: list(qemu_hosts),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.settings.load_manual_connections",
        lambda: list(manual_connections),
    )
    # _apply_project_selection now pre-loads every project's VMs/buckets
    # in the background immediately (not just on first expand) — stub
    # these out (get_credentials included: list_instances/list_buckets
    # are mocked below, but the lambda that calls them still evaluates a
    # real gcp_auth.get_credentials() first, which fails fast without a
    # real gcloud on PATH) so tests don't fire real, un-mocked API calls.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.get_credentials",
        lambda: None,
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_client.list_instances",
        lambda creds, project_id: list(instances),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_client.list_buckets",
        lambda creds, project_id: list(buckets),
    )
    view = ConnectionManagerView()
    qtbot.addWidget(view)
    return view


def test_projects_are_nested_under_a_gcp_category(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]

    view._apply_project_selection({"p1"})

    # GCP, QEMU, and Manual are independent top-level roots (QEMU/Manual
    # lists are empty here, but the roots themselves are always present).
    assert view._tree.topLevelItemCount() == 3
    gcp_category = view._tree.topLevelItem(0)
    assert gcp_category.text(0) == "GCP"
    assert gcp_category.isExpanded()
    assert gcp_category.childCount() == 1
    project_item = gcp_category.child(0)
    assert project_item.text(0) == "Project One"

    qemu_category = view._tree.topLevelItem(1)
    assert qemu_category.text(0) == "QEMU"

    manual_category = view._tree.topLevelItem(2)
    assert manual_category.text(0) == "Manual"


def test_projects_are_listed_alphabetically_case_insensitive(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [
        GcpProject(project_id="p1", display_name="pvwrk-fme04"),
        GcpProject(project_id="p2", display_name="pvsrv-ftp03"),
        GcpProject(project_id="p3", display_name="PVSRV-GIS03"),
        GcpProject(project_id="p4", display_name="pvsrv-nas01"),
    ]

    view._apply_project_selection({"p1", "p2", "p3", "p4"})

    gcp_category = view._tree.topLevelItem(0)
    names = [gcp_category.child(i).text(0) for i in range(gcp_category.childCount())]
    assert names == ["pvsrv-ftp03", "PVSRV-GIS03", "pvsrv-nas01", "pvwrk-fme04"]


def test_project_has_vms_and_buckets_categories(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import (
        CATEGORY_BUCKETS,
        CATEGORY_ROLE,
        CATEGORY_VMS,
    )

    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    project_item = view._tree.topLevelItem(0).child(0)
    assert project_item.childCount() == 2
    assert project_item.child(0).text(0) == "VMs"
    assert project_item.child(0).data(0, CATEGORY_ROLE) == CATEGORY_VMS
    assert project_item.child(1).text(0) == "Buckets"
    assert project_item.child(1).data(0, CATEGORY_ROLE) == CATEGORY_BUCKETS


def test_expanding_buckets_category_populates_bucket_items(qtbot, monkeypatch):
    # "Expanding" is a misnomer now that categories pre-load in the
    # background regardless of expand state — this exercises that real
    # pre-load pipeline end-to-end (mocked gcp_client, real async
    # round-trip) rather than calling _populate_buckets directly.
    from it_toolbox.modules.connection_manager.ui.main_view import BUCKET_ROLE

    bucket = GcsBucket(name="my-bucket", project_id="p1")
    view = _make_view(qtbot, monkeypatch, buckets=[bucket])
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    buckets_item = view._tree.topLevelItem(0).child(0).child(1)

    # childCount() == 1 is true both before (the "Loading…" placeholder)
    # and after (the real bucket) the async pre-load resolves — wait for
    # the actual text instead of just a count.
    qtbot.waitUntil(lambda: buckets_item.child(0).text(0) != "Loading…", timeout=2000)
    assert buckets_item.childCount() == 1
    assert buckets_item.child(0).text(0) == "my-bucket"
    assert buckets_item.child(0).data(0, BUCKET_ROLE) == bucket
    assert not buckets_item.isHidden()


def test_buckets_category_hides_when_project_has_no_buckets(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)  # default gcp_client stub returns []
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    buckets_item = view._tree.topLevelItem(0).child(0).child(1)

    qtbot.waitUntil(lambda: buckets_item.isHidden(), timeout=2000)


def test_buckets_category_unhides_once_a_bucket_appears_on_refresh(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    view = _make_view(qtbot, monkeypatch)  # starts with no buckets -> hidden
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    buckets_item = view._tree.topLevelItem(0).child(0).child(1)
    qtbot.waitUntil(lambda: buckets_item.isHidden(), timeout=2000)

    bucket = GcsBucket(name="new-bucket", project_id="p1")
    monkeypatch.setattr(main_view_module.gcp_auth, "get_credentials", lambda: None)
    monkeypatch.setattr(
        main_view_module.gcp_client, "list_buckets", lambda creds, project_id: [bucket]
    )
    view._refresh_project(view._tree.topLevelItem(0).child(0))

    qtbot.waitUntil(lambda: not buckets_item.isHidden(), timeout=2000)
    assert buckets_item.childCount() == 1
    assert buckets_item.child(0).text(0) == "new-bucket"


def test_bucket_list_error_unhides_a_previously_empty_category(qtbot, monkeypatch):
    # Regression guard for the edge case this hiding behavior introduces:
    # a category hidden from an earlier empty-but-successful load must
    # not stay hidden if a later refresh actually fails — that would
    # silently swallow a real error from the user.
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    view = _make_view(qtbot, monkeypatch)  # starts with no buckets -> hidden
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    buckets_item = view._tree.topLevelItem(0).child(0).child(1)
    qtbot.waitUntil(lambda: buckets_item.isHidden(), timeout=2000)

    def failing_list_buckets(creds, project_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_view_module.gcp_auth, "get_credentials", lambda: None)
    monkeypatch.setattr(main_view_module.gcp_client, "list_buckets", failing_list_buckets)
    view._refresh_project(view._tree.topLevelItem(0).child(0))

    qtbot.waitUntil(lambda: not buckets_item.isHidden(), timeout=2000)
    assert "Error" in buckets_item.child(0).text(0)


def test_expanding_vms_category_populates_instance_items(qtbot, monkeypatch):
    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch, instances=[instance])
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    vms_item = view._tree.topLevelItem(0).child(0).child(0)

    # childCount() == 1 is true both before (the "Loading…" placeholder)
    # and after (the real instance) the async pre-load resolves — wait
    # for the actual text instead of just a count.
    qtbot.waitUntil(lambda: vms_item.child(0).text(0) != "Loading…", timeout=2000)
    assert vms_item.childCount() == 1
    assert vms_item.child(0).text(0) == "vm-1"


def test_turn_on_instance_calls_start_and_refreshes_project(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="TERMINATED")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    calls = []
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "start_instance",
        lambda creds, project_id, zone, name: calls.append((project_id, zone, name)),
    )
    refreshed = []
    monkeypatch.setattr(view, "_refresh_project", lambda item: refreshed.append(item))

    view._run_instance_power_action(instance, "start")

    qtbot.waitUntil(lambda: calls == [("p1", "us-central1-a", "vm-1")], timeout=2000)
    qtbot.waitUntil(lambda: len(refreshed) == 1, timeout=2000)


def test_turn_off_instance_asks_for_confirmation_first(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    calls = []
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "stop_instance",
        lambda creds, project_id, zone, name: calls.append((project_id, zone, name)),
    )
    monkeypatch.setattr(
        main_view_module.QMessageBox,
        "question",
        lambda *args, **kwargs: main_view_module.QMessageBox.StandardButton.No,
    )

    view._run_instance_power_action(instance, "stop")

    assert calls == []  # declining the confirmation must not call the API


def test_turn_off_instance_calls_stop_once_confirmed(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    calls = []
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "stop_instance",
        lambda creds, project_id, zone, name: calls.append((project_id, zone, name)),
    )
    monkeypatch.setattr(
        main_view_module.QMessageBox,
        "question",
        lambda *args, **kwargs: main_view_module.QMessageBox.StandardButton.Yes,
    )

    view._run_instance_power_action(instance, "stop")

    qtbot.waitUntil(lambda: calls == [("p1", "us-central1-a", "vm-1")], timeout=2000)


def test_force_shutdown_asks_for_confirmation_first(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    calls = []
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "stop_instance",
        lambda creds, project_id, zone, name, force=False: calls.append(
            (project_id, zone, name, force)
        ),
    )
    monkeypatch.setattr(
        main_view_module.QMessageBox,
        "question",
        lambda *args, **kwargs: main_view_module.QMessageBox.StandardButton.No,
    )

    view._run_instance_power_action(instance, "force_stop")

    assert calls == []  # declining the confirmation must not call the API


def test_force_shutdown_calls_stop_with_force_once_confirmed(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    calls = []
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "stop_instance",
        lambda creds, project_id, zone, name, force=False: calls.append(
            (project_id, zone, name, force)
        ),
    )
    monkeypatch.setattr(
        main_view_module.QMessageBox,
        "question",
        lambda *args, **kwargs: main_view_module.QMessageBox.StandardButton.Yes,
    )

    view._run_instance_power_action(instance, "force_stop")

    qtbot.waitUntil(lambda: calls == [("p1", "us-central1-a", "vm-1", True)], timeout=2000)


def test_set_instance_password_prompt_is_prefilled_with_default_username(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    monkeypatch.setattr(
        main_view_module.settings, "load_default_username", lambda: "alice"
    )
    prefill_seen = []

    def fake_get_text(parent, title, label, mode, text):
        prefill_seen.append(text)
        return "", False  # cancel — this test only cares what it was prefilled with

    monkeypatch.setattr(main_view_module.QInputDialog, "getText", fake_get_text)

    view._on_set_instance_password_clicked(instance)

    # Never defaults to "Administrator" behind the user's back — the app's
    # already-configured default username is offered instead, and the user
    # can still change or clear it before confirming.
    assert prefill_seen == ["alice"]


def test_set_instance_password_cancel_does_not_call_the_api(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    calls = []
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "reset_windows_password",
        lambda creds, project_id, zone, name, username: calls.append(username),
    )
    monkeypatch.setattr(
        main_view_module.QInputDialog, "getText", lambda *args, **kwargs: ("someone", False)
    )

    view._on_set_instance_password_clicked(instance)

    assert calls == []


def test_set_instance_password_shows_returned_credentials(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    instance = Instance(name="vm-1", zone="us-central1-a", project_id="p1", status="RUNNING")
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    monkeypatch.setattr(
        main_view_module.QInputDialog, "getText", lambda *args, **kwargs: ("alice", True)
    )
    calls = []
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "reset_windows_password",
        lambda creds, project_id, zone, name, username: calls.append(username)
        or ("alice", "s3cr3t!"),
    )
    shown = []
    monkeypatch.setattr(
        main_view_module.QMessageBox,
        "information",
        lambda parent, title, text: shown.append((title, text)),
    )

    view._on_set_instance_password_clicked(instance)

    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)
    assert calls == ["alice"]
    title, text = shown[0]
    assert "alice" in text
    assert "s3cr3t!" in text


def test_double_clicking_a_bucket_opens_a_browser_tab(qtbot, monkeypatch):
    import it_toolbox.widgets.bucket_browser_widget as browser_module

    monkeypatch.setattr(
        browser_module.gcp_client, "list_objects", lambda creds, bucket, prefix: []
    )
    view = _make_view(qtbot, monkeypatch)
    bucket = GcsBucket(name="my-bucket", project_id="p1")

    view._open_bucket_browser(bucket)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "my-bucket"


def test_closing_a_bucket_browser_tab_just_removes_it(qtbot, monkeypatch):
    import it_toolbox.widgets.bucket_browser_widget as browser_module

    monkeypatch.setattr(
        browser_module.gcp_client, "list_objects", lambda creds, bucket, prefix: []
    )
    view = _make_view(qtbot, monkeypatch)
    bucket = GcsBucket(name="my-bucket", project_id="p1")
    view._open_bucket_browser(bucket)

    view._on_tab_close_requested(0)

    assert view._tabs.count() == 0
    assert view._active_sessions == {}  # not tracked as a session


def test_gcp_root_context_menu_offers_select_projects_and_sign_out(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._account = "me@example.com"

    menu = view._build_gcp_root_menu()

    assert [action.text() for action in menu.actions()] == ["Select Projects…", "Sign out"]


def test_gcp_root_context_menu_is_none_when_not_signed_in(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._account = None

    assert view._build_gcp_root_menu() is None


def test_gcp_root_item_is_marked_with_is_gcp_root_role(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import IS_GCP_ROOT_ROLE

    view = _make_view(qtbot, monkeypatch)
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})

    root = view._tree.topLevelItem(0)
    assert root.data(0, IS_GCP_ROOT_ROLE) is True


def test_selecting_projects_preloads_vms_and_buckets_without_expanding(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    # _make_view's own default gcp_client stubs must be set up first —
    # applying our call-counting mocks before it would just get
    # overwritten by _make_view's own monkeypatch.setattr calls.
    view = _make_view(qtbot, monkeypatch)

    calls = {"instances": 0, "buckets": 0}
    monkeypatch.setattr(main_view_module.gcp_auth, "get_credentials", lambda: None)
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "list_instances",
        lambda creds, project_id: (calls.__setitem__("instances", calls["instances"] + 1), [])[1],
    )
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "list_buckets",
        lambda creds, project_id: (calls.__setitem__("buckets", calls["buckets"] + 1), [])[1],
    )
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]

    view._apply_project_selection({"p1"})

    # No itemExpanded signal ever fired — this is pre-loaded purely from
    # applying the selection.
    qtbot.waitUntil(lambda: calls == {"instances": 1, "buckets": 1}, timeout=2000)


def test_load_category_skips_a_second_call_while_already_loading(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    view = _make_view(qtbot, monkeypatch)

    calls = []
    monkeypatch.setattr(main_view_module.gcp_auth, "get_credentials", lambda: None)
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "list_instances",
        lambda creds, project_id: (calls.append(project_id), [])[1],
    )
    item = QTreeWidgetItem(["VMs"])

    # Fire twice back-to-back, synchronously, before either has a chance
    # to resolve — the second call must be a no-op given the guard.
    view._load_category(item, "p1", main_view_module.CATEGORY_VMS)
    view._load_category(item, "p1", main_view_module.CATEGORY_VMS)

    qtbot.waitUntil(lambda: len(calls) >= 1, timeout=2000)
    qtbot.wait(50)  # give a wrongly-unguarded second call a chance to land too
    assert calls == ["p1"]


def test_refresh_project_reloads_both_categories(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    view = _make_view(qtbot, monkeypatch)

    instance_calls = []
    bucket_calls = []
    monkeypatch.setattr(main_view_module.gcp_auth, "get_credentials", lambda: None)
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "list_instances",
        lambda creds, project_id: (instance_calls.append(project_id), [])[1],
    )
    monkeypatch.setattr(
        main_view_module.gcp_client,
        "list_buckets",
        lambda creds, project_id: (bucket_calls.append(project_id), [])[1],
    )
    view._account = "me@example.com"
    view._all_projects = [GcpProject(project_id="p1", display_name="Project One")]
    view._apply_project_selection({"p1"})
    project_item = view._tree.topLevelItem(0).child(0)

    qtbot.waitUntil(lambda: instance_calls == ["p1"] and bucket_calls == ["p1"], timeout=2000)

    # A manual refresh re-triggers both, even though they're already loaded.
    view._refresh_project(project_item)

    qtbot.waitUntil(lambda: instance_calls == ["p1", "p1"] and bucket_calls == ["p1", "p1"], timeout=2000)


def test_refresh_all_gcp_data_noops_when_signed_out(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    view._account = None

    view._refresh_all_gcp_data()  # must not raise despite no tree/account


def test_ssh_connect_embeds_terminal_and_registers_session(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "test-vm"
    assert len(view._active_sessions) == 1
    assert len(view._session_tab_widgets) == 1


def test_ssh_connect_gives_the_terminal_keyboard_focus(qtbot, monkeypatch):
    # Regression test: keyPressEvent() only ever fires for the widget that
    # actually has Qt focus. A prior version created the terminal tab but
    # never called setFocus() on it, so real keystrokes silently went
    # nowhere — invisible in a test that calls keyPressEvent() directly
    # instead of exercising real focus, which is exactly how this was
    # missed originally.
    view = _make_view(qtbot, monkeypatch)
    view.show()
    qtbot.waitExposed(view)
    tunnel = _FakeTunnel()

    # A real `ssh` against a closed port fails almost instantly, tearing
    # the tab back down while this test is still polling it — a long-lived
    # shell exercises the same focus-wiring path deterministically instead.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.TerminalWidget",
        lambda argv: TerminalWidget(["/bin/sh"]),
    )

    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    terminal = view._tabs.widget(0)
    qtbot.waitUntil(lambda: terminal.hasFocus(), timeout=2000)
    terminal.close_session()


def test_closing_tab_disconnects_and_stops_tunnel(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()
    view._on_tunnel_ready(tunnel, "test-vm", "ssh", None)

    view._on_tab_close_requested(0)

    assert view._tabs.count() == 0
    assert view._active_sessions == {}
    assert view._session_tab_widgets == {}
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)


class _FakeRdpWidget(QWidget):
    """Stands in for the real RdpWidget in main_view tests — the real one
    spawns a background thread that immediately drives actual libfreerdp
    ctypes calls, which needs a real reachable RDP server and isn't
    something a unit test should depend on. Exposes the same contract
    main_view relies on: a `finished` signal and close_session()."""

    finished = Signal()

    def __init__(self, host, port, username, password, domain=""):
        super().__init__()
        self.host, self.port, self.username, self.password = host, port, username, password

    def close_session(self):
        pass


def test_rdp_connect_embeds_widget_and_registers_session(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.RdpWidget", _FakeRdpWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_tunnel_ready(tunnel, "test-vm", "rdp", "alice", "secret")

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "test-vm"
    widget = view._tabs.widget(0)
    assert (widget.host, widget.port, widget.username, widget.password) == (
        "127.0.0.1",
        2222,
        "alice",
        "secret",
    )
    assert len(view._active_sessions) == 1


def test_rdp_widget_finishing_disconnects_and_stops_tunnel(qtbot, monkeypatch):
    # Covers both a connect failure and the remote side dropping the
    # connection — RdpWidget.finished fires in either case, and main_view
    # must tear the tab/session/tunnel down the same way for both.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.RdpWidget", _FakeRdpWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel()

    view._on_tunnel_ready(tunnel, "test-vm", "rdp", None, None)
    widget = view._tabs.widget(0)
    widget.finished.emit()

    assert view._tabs.count() == 0
    assert view._active_sessions == {}
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)


# -- QEMU hosts / VMs --------------------------------------------------------


def test_populate_qemu_hosts_creates_lazy_loading_host_items(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import CHILDREN_LOADED_ROLE, HOST_ROLE

    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    view = _make_view(qtbot, monkeypatch, qemu_hosts=[{"name": host.name, "uri": host.uri}])

    assert view._tree.topLevelItemCount() == 2  # gcloud unavailable, so QEMU + Manual only
    qemu_root = view._tree.topLevelItem(0)
    assert qemu_root.text(0) == "QEMU"
    assert qemu_root.childCount() == 1
    host_item = qemu_root.child(0)
    assert host_item.text(0) == "lab"
    assert host_item.data(0, HOST_ROLE) == host
    assert host_item.data(0, CHILDREN_LOADED_ROLE) is False
    assert host_item.child(0).text(0) == "Loading…"


def test_populate_qemu_vms_creates_items_with_roles(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import HOST_ROLE, VM_ROLE

    view = _make_view(qtbot, monkeypatch)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    host_item = QTreeWidgetItem(["lab"])
    vm = QemuVm(id="1", name="myvm", state="running")

    view._populate_qemu_vms(host_item, host, [vm])

    assert host_item.childCount() == 1
    vm_item = host_item.child(0)
    assert vm_item.text(0) == "myvm"
    assert vm_item.data(0, HOST_ROLE) == host
    assert vm_item.data(0, VM_ROLE) == vm


def test_populate_qemu_vms_shows_placeholder_when_empty(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    host_item = QTreeWidgetItem(["lab"])

    view._populate_qemu_vms(host_item, host, [])

    assert host_item.childCount() == 1
    assert host_item.child(0).text(0) == "(no VMs)"


class _FakeSpiceWidget(QWidget):
    """Stands in for the real SpiceWidget — the real one spawns a
    background thread that immediately drives actual SpiceClientGLib
    calls against a real SPICE server. Exposes the same contract
    main_view relies on: a `finished` signal and close_session()."""

    finished = Signal()

    def __init__(self, host, port, password=""):
        super().__init__()
        self.host, self.port, self.password = host, port, password

    def close_session(self):
        pass


def test_qemu_connect_embeds_widget_and_registers_session(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.SpiceWidget", _FakeSpiceWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel(port=5901)
    vm = QemuVm(id="1", name="myvm", state="running")

    view._on_qemu_tunnel_ready(tunnel, vm)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "myvm"
    widget = view._tabs.widget(0)
    assert (widget.host, widget.port) == ("127.0.0.1", 5901)
    assert len(view._active_sessions) == 1
    assert view._active_sessions[next(iter(view._active_sessions))][0] == "spice"


def test_spice_widget_finishing_disconnects_and_stops_tunnel(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.SpiceWidget", _FakeSpiceWidget
    )
    view = _make_view(qtbot, monkeypatch)
    tunnel = _FakeTunnel(port=5901)
    vm = QemuVm(id="1", name="myvm", state="running")

    view._on_qemu_tunnel_ready(tunnel, vm)
    widget = view._tabs.widget(0)
    widget.finished.emit()

    assert view._tabs.count() == 0
    assert view._active_sessions == {}
    qtbot.waitUntil(lambda: tunnel.stopped, timeout=2000)


def test_start_qemu_tunnel_raises_when_no_spice_port(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    monkeypatch.setattr(main_view_module.qemu_client, "get_vm_spice_port", lambda host, name: None)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    vm = QemuVm(id="1", name="myvm", state="shut off")

    with pytest.raises(main_view_module.QemuApiError, match="no SPICE port"):
        ConnectionManagerView._start_qemu_tunnel(host, vm)


def test_connect_qemu_warns_instead_of_crashing_when_spice_unavailable(qtbot, monkeypatch):
    # Regression test: SpiceWidget is None on platforms without PyGObject/
    # spice-glib (see the try/except import at the top of main_view.py).
    # _connect_qemu must degrade to a clear warning, not an AttributeError
    # from trying to construct a SpiceWidget that doesn't exist.
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    monkeypatch.setattr(main_view_module, "SpiceWidget", None)
    warnings = []
    monkeypatch.setattr(
        main_view_module.QMessageBox, "warning", staticmethod(lambda *a: warnings.append(a))
    )
    view = _make_view(qtbot, monkeypatch)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    vm = QemuVm(id="1", name="myvm", state="running")

    view._connect_qemu(host, vm)

    assert len(warnings) == 1
    assert view._tabs.count() == 0
    assert view._active_sessions == {}


def test_qemu_power_action_calls_client_and_refreshes_vm_list(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    calls = []
    monkeypatch.setattr(
        main_view_module.qemu_client,
        "power_action",
        lambda host, vm_name, action: calls.append((host, vm_name, action)),
    )
    monkeypatch.setattr(main_view_module.qemu_client, "list_vms", lambda host: [])

    view = _make_view(qtbot, monkeypatch)
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")
    view._qemu_root_item = QTreeWidgetItem(["QEMU"])
    host_item = QTreeWidgetItem(["lab"])
    host_item.setData(0, main_view_module.HOST_ROLE, host)
    view._qemu_root_item.addChild(host_item)
    vm = QemuVm(id="1", name="myvm", state="running")

    view._run_qemu_power_action(host, vm, "shutdown")

    qtbot.waitUntil(lambda: calls == [(host, "myvm", "shutdown")], timeout=2000)
    qtbot.waitUntil(lambda: host_item.childCount() == 1, timeout=2000)
    assert host_item.child(0).text(0) == "(no VMs)"


def test_manage_hosts_dialog_roundtrips_through_settings(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    saved = {}
    monkeypatch.setattr(
        main_view_module.settings, "save_qemu_hosts", lambda hosts: saved.setdefault("hosts", hosts)
    )
    host = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")

    view = _make_view(qtbot, monkeypatch)
    view._save_qemu_hosts([host])

    assert saved["hosts"] == [{"name": "lab", "uri": "qemu+ssh://user@lab-host/system"}]


# -- Manually-configured RDP/SSH connections --------------------------------


def test_populate_manual_connections_creates_items(qtbot, monkeypatch):
    from it_toolbox.modules.connection_manager.ui.main_view import MANUAL_CONNECTION_ROLE

    connection = ManualConnection(name="my-box", host="10.0.0.5", port=3389, kind="rdp")
    view = _make_view(
        qtbot,
        monkeypatch,
        manual_connections=[
            {"name": connection.name, "host": connection.host, "port": connection.port, "kind": connection.kind}
        ],
    )

    manual_root = None
    for i in range(view._tree.topLevelItemCount()):
        if view._tree.topLevelItem(i).text(0) == "Manual":
            manual_root = view._tree.topLevelItem(i)
    assert manual_root is not None
    assert manual_root.childCount() == 1
    item = manual_root.child(0)
    assert item.text(0) == "my-box"
    assert item.data(0, MANUAL_CONNECTION_ROLE) == connection


def test_manual_ssh_connect_embeds_terminal_without_tunnel(qtbot, monkeypatch):
    # No tunnel is involved for a manual connection — it dials host:port
    # directly, so _active_sessions must stay empty (nothing to stop on
    # disconnect) while _session_tab_widgets still tracks the tab.
    view = _make_view(qtbot, monkeypatch)
    connection = ManualConnection(name="my-box", host="10.0.0.5", port=2222, kind="ssh", username="alice")

    view._start_session_from_manual_connection(connection)

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "my-box"
    assert view._active_sessions == {}
    assert len(view._session_tab_widgets) == 1


def test_manual_rdp_connect_embeds_widget_without_tunnel(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    monkeypatch.setattr(main_view_module, "RdpWidget", _FakeRdpWidget)
    monkeypatch.setattr(
        main_view_module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("secret", True))
    )
    view = _make_view(qtbot, monkeypatch)
    connection = ManualConnection(name="my-box", host="10.0.0.5", port=3389, kind="rdp", username="alice")

    view._start_session_from_manual_connection(connection)

    assert view._tabs.count() == 1
    widget = view._tabs.widget(0)
    assert (widget.host, widget.port, widget.username, widget.password) == (
        "10.0.0.5",
        3389,
        "alice",
        "secret",
    )
    assert view._active_sessions == {}


def test_manual_connections_roundtrip_through_settings(qtbot, monkeypatch):
    import it_toolbox.modules.connection_manager.ui.main_view as main_view_module

    saved = {}
    monkeypatch.setattr(
        main_view_module.settings,
        "save_manual_connections",
        lambda connections: saved.setdefault("connections", connections),
    )
    connection = ManualConnection(name="my-box", host="10.0.0.5", port=3389, kind="rdp", username="alice")

    view = _make_view(qtbot, monkeypatch)
    view._save_manual_connections([connection])

    assert saved["connections"] == [
        {"name": "my-box", "host": "10.0.0.5", "port": 3389, "kind": "rdp", "username": "alice"}
    ]

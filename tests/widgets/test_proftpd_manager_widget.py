import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog, QMessageBox

from it_toolbox.core import proftpd_manager as pm
from it_toolbox.widgets import proftpd_manager_widget as w

SERVER = pm.ProftpdServer(name="nas", host="nas.lan", username="admin")

USERS = [
    {"username": "alice", "uid": 5000, "gid": 5000, "homedir": "/var/ftp/alice", "protocol": "both",
     "quota_mb": 100, "quota_used_mb": 12.5, "readonly": False, "public_key": None,
     "rate_limit": "unlimited", "locked": False, "expires_at": None},
    {"username": "bob", "uid": 5001, "gid": 5001, "homedir": "/srv/bob", "protocol": "sftp",
     "quota_mb": None, "quota_used_mb": None, "readonly": True, "public_key": "ssh-ed25519 AAAA",
     "rate_limit": "slow", "locked": True, "expires_at": None},
]


class FakeConnection:
    """Stands in for ProftpdConnection; `connect_errors` are raised by
    successive connect() calls before one succeeds."""

    instances = []
    connect_errors = []
    status_result = {"installed": True, "configured": True, "active": True}
    helper_path = pm.COCKPIT_HELPER_PATH
    live_enabled = False

    def __init__(self, server, **credentials):
        self.server = server
        self.credentials = credentials
        self.calls = []
        self.helper_path = type(self).helper_path
        FakeConnection.instances.append(self)

    def connect(self):
        if FakeConnection.connect_errors:
            raise FakeConnection.connect_errors.pop(0)

    def close(self):
        self.calls.append(("close",))

    def status(self):
        return dict(self.status_result)

    def setup(self, require_tls):
        self.calls.append(("setup", require_tls))
        return {"installed": True, "configured": True, "active": True}

    def install_bundled_helper(self):
        self.calls.append(("install",))
        self.helper_path = pm.BUNDLED_HELPER_PATH
        return self.helper_path

    def list_users(self):
        return [dict(u) for u in USERS]

    def list_groups(self):
        return [{"groupname": "eng", "gid": 3000, "members": ["alice"]}]

    def list_virtual_mounts(self, username=None):
        return [
            {"username": "alice", "virtual_name": "team", "real_path": "/srv/team",
             "readonly": False, "group_name": "eng"},
        ]

    def list_transfers(self):
        return [{"username": "alice", "command": "STOR", "path": "/a.txt", "bytes": 2048,
                 "timestamp": 1791419672}]

    def live_log_enabled(self):
        return self.live_enabled

    def enable_live_log(self):
        self.calls.append(("enable_live_log",))
        self.live_enabled = True

    def follow_live_log(self, on_lines, should_stop):
        on_lines(["\t".join(["1791419672", "35", "10.0.0.5", "ftp", "-", "-", "-", "-", ""])])

    def list_sessions(self):
        return [pm.LiveSession(pid=35, address="10.0.0.5", user="alice", protocol="ftp",
                               location="/", connected_since=1791419672.0, idle=True)]

    def kick_session(self, pid):
        self.calls.append(("kick", pid))

    def delete_user(self, username):
        self.calls.append(("delete_user", username))

    def update_user(self, username, password, options):
        self.calls.append(("update_user", username, password, options))

    def create_user(self, username, password, options):
        self.calls.append(("create_user", username, password, options))


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeConnection.instances = []
    FakeConnection.connect_errors = []
    FakeConnection.status_result = {"installed": True, "configured": True, "active": True}
    FakeConnection.helper_path = pm.COCKPIT_HELPER_PATH
    FakeConnection.live_enabled = False


def _make(qtbot):
    widget = w.ProftpdManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)
    return widget


def test_connects_and_shows_users_groups_and_activity(qtbot):
    widget = _make(qtbot)

    qtbot.waitUntil(lambda: widget.users_table.rowCount() == 2)
    assert widget.stack.currentWidget() is widget.tabs
    assert widget.users_table.item(0, 0).text() == "alice"
    assert widget.users_table.item(0, 5).text() == "12.5 / 100 MB"
    assert widget.users_table.item(1, 3).text() == "SFTP only"
    assert widget.users_table.item(1, 8).text() == "Locked"
    qtbot.waitUntil(lambda: widget.groups_list.count() == 1)
    assert widget.members_list.item(0).text() == "alice"
    assert widget.group_mounts.item(0, 1).text() == "/srv/team"
    assert [widget.add_member_combo.itemText(i) for i in range(widget.add_member_combo.count())] == ["bob"]
    qtbot.waitUntil(lambda: widget.transfers_table.rowCount() == 1)
    assert widget.transfers_table.item(0, 4).text() == "2.0 KB"
    qtbot.waitUntil(lambda: widget.live.enabled is False)
    assert widget.live.stack.currentWidget() is widget.live.off_panel


def test_search_filters_users(qtbot):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.users_table.rowCount() == 2)

    widget.user_search.setText("/srv")

    assert widget.users_table.isRowHidden(0)
    assert not widget.users_table.isRowHidden(1)


def test_unconfigured_server_shows_setup_and_runs_it(qtbot):
    FakeConnection.status_result = {"installed": False, "configured": False, "active": False}
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.setup_page)

    widget.require_tls.setChecked(False)
    widget.setup_button.click()

    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.tabs)
    assert ("setup", False) in widget.connection.calls


def test_missing_helper_offers_the_bundled_one(qtbot):
    FakeConnection.helper_path = None
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.helper_page)

    widget.install_helper_button.click()

    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.tabs)
    assert ("install",) in widget.connection.calls


def test_prompts_for_sudo_password_and_reconnects(qtbot, monkeypatch):
    FakeConnection.connect_errors = [pm.SudoPasswordRequired()]
    monkeypatch.setattr(w.QInputDialog, "getText", lambda *a, **k: ("pw", True))
    widget = _make(qtbot)

    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.tabs)
    assert FakeConnection.instances[-1].credentials == {"sudo_password": "pw"}


def test_login_password_is_reused_for_sudo(qtbot, monkeypatch):
    FakeConnection.connect_errors = [pm.LoginPasswordRequired("denied")]
    monkeypatch.setattr(w.QInputDialog, "getText", lambda *a, **k: ("pw", True))
    widget = _make(qtbot)

    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.tabs)
    assert FakeConnection.instances[-1].credentials == {"password": "pw", "sudo_password": "pw"}


def test_cancelled_prompt_leaves_an_error_page(qtbot, monkeypatch):
    FakeConnection.connect_errors = [pm.SudoPasswordRequired()]
    monkeypatch.setattr(w.QInputDialog, "getText", lambda *a, **k: ("", False))
    widget = _make(qtbot)

    qtbot.waitUntil(lambda: widget.reconnect_button.isEnabled())
    assert widget.stack.currentWidget() is widget.message_page
    assert "sudo needs a password" in widget.message_page.text()


def test_turning_on_live_logging_starts_following(qtbot):
    widget = _make(qtbot)
    widget.show()
    qtbot.waitUntil(lambda: widget.live.enabled is False)
    widget.tabs.setCurrentWidget(widget.live)

    widget.live.enable_button.click()

    qtbot.waitUntil(lambda: widget.live.log.rowCount() == 1)
    assert widget.live.stack.currentWidget() is widget.live.on_panel
    assert widget.live.log.item(0, 5).text() == "Connected"
    qtbot.waitUntil(lambda: widget.live.sessions.rowCount() == 1)
    assert widget.live.sessions.item(0, 1).text() == "alice"
    widget.close_session()


def _event(command="", user=None, code=None, response=None, pid=7, num_bytes=None):
    return pm.LiveEvent(timestamp=1791419672, pid=pid, address="10.0.0.5", protocol="ftp",
                        user=user, code=code, bytes=num_bytes, response=response, command=command)


def test_live_view_labels_session_start_and_end(qtbot):
    widget = _make(qtbot)
    live = widget.live

    live.add_event(_event())
    live.add_event(_event("USER alice", code="331", response="Password required"))
    live.add_event(_event("RETR a.iso", user="alice", code="226", response="Transfer complete",
                          num_bytes=2 * 1024 * 1024))
    live.add_event(_event("PASS (hidden)", code="530", response="Login incorrect."))
    live.add_event(_event(user="alice"))
    # A session that ended before the shown history began.
    live.add_event(_event(user="carol", pid=8))

    assert [live.log.item(r, 5).text() for r in range(live.log.rowCount())] == [
        "Connected", "USER alice", "RETR a.iso", "PASS (hidden)", "Disconnected", "Disconnected",
    ]
    assert live.log.item(2, 6).text() == "226 Transfer complete (2.0 MB)"
    assert live.log.item(3, 6).foreground().color().name() == "#c62828"


def test_live_view_filter_and_pause(qtbot):
    widget = _make(qtbot)
    live = widget.live
    line = "\t".join(["1", "7", "10.0.0.5", "ftp", "alice", "226", "1", "ok", "STOR x"])
    other = "\t".join(["1", "8", "10.0.0.6", "sftp", "bob", "226", "1", "ok", "RETR y"])
    live._on_lines([line, other, "not a log line"])

    live.filter.setText("bob")
    assert live.log.isRowHidden(0) and not live.log.isRowHidden(1)

    live.pause_button.setChecked(True)
    live._on_lines([line])
    assert live.log.rowCount() == 2


def test_kicking_a_session_asks_first(qtbot, monkeypatch):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.connection is not None)
    widget.live.show_sessions(widget.connection.list_sessions())
    widget.live.sessions.selectRow(0)
    monkeypatch.setattr(w.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    widget.live._kick_selected()

    qtbot.waitUntil(lambda: ("kick", 35) in widget.connection.calls)


def test_bulk_delete_deletes_each_selected_user(qtbot, monkeypatch):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.users_table.rowCount() == 2)
    widget.users_table.selectAll()
    assert widget.delete_selected_button.text() == "Delete Selected (2)"
    monkeypatch.setattr(w.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    widget.delete_selected_button.click()

    qtbot.waitUntil(lambda: ("delete_user", "bob") in widget.connection.calls)
    assert ("delete_user", "alice") in widget.connection.calls


def test_toggle_lock(qtbot):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.users_table.rowCount() == 2)

    widget.toggle_lock(widget.users[1])

    qtbot.waitUntil(lambda: any(c[0] == "update_user" for c in widget.connection.calls))
    assert ("update_user", "bob", None, {"locked": False}) in widget.connection.calls


def test_user_dialog_create_options(qtbot):
    dialog = w.UserDialog()
    qtbot.addWidget(dialog)
    dialog.username.setText("carol")
    dialog.quota.setValue(50)
    dialog.protocol.setCurrentIndex(dialog.protocol.findData("ftp"))
    dialog.expires.setChecked(True)
    dialog.expires_date.setDate(QDate(2030, 1, 2))

    assert dialog.options() == {
        "protocol": "ftp", "quota_mb": 50, "readonly": False, "public_key": "",
        "rate_limit": "unlimited", "locked": False, "expires_at": "2030-01-02",
    }


def test_user_dialog_edit_prefills_and_renames(qtbot):
    dialog = w.UserDialog(dict(USERS[1], expires_at="2031-05-06"))
    qtbot.addWidget(dialog)
    assert dialog.readonly.isChecked() and dialog.locked.isChecked()
    assert dialog.expires.isChecked()

    dialog.username.setText("robert")
    dialog.expires.setChecked(False)
    options = dialog.options()

    assert options["new_username"] == "robert"
    assert options["expires_at"] == ""
    assert options["public_key"] == "ssh-ed25519 AAAA"
    assert options["homedir"] == "/srv/bob"


def test_user_dialog_requires_a_password_or_key(qtbot, monkeypatch):
    warnings = []
    monkeypatch.setattr(w.QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    dialog = w.UserDialog()
    qtbot.addWidget(dialog)
    dialog.username.setText("carol")

    dialog._accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert warnings == ["A password or a public key is required."]


def test_server_dialog_builds_a_server(qtbot):
    dialog = w.ServerDialog()
    qtbot.addWidget(dialog)
    dialog._host.setText("nas.lan")
    dialog._container.setText("proftpd")

    server = dialog.server()

    assert server == pm.ProftpdServer(name="nas.lan", host="nas.lan", username="root",
                                      docker_container="proftpd")

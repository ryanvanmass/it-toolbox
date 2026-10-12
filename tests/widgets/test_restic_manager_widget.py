import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from it_toolbox.core import async_utils
from it_toolbox.core import remote_helper as rh
from it_toolbox.core import restic_manager as rm
from it_toolbox.widgets import remote_helper_widget as rw
from it_toolbox.widgets import restic_dialogs as dialogs
from it_toolbox.widgets import restic_manager_widget as w

SERVER = rm.ResticServer(name="lab", host="lab.lan", username="admin")
LOCKED_CHECK = {"status": "failure", "started_at": "2026-10-12T03:00:00+00:00", "finished_at": None,
                "blocked_by_lock": True}
REPOS = [
    {"id": "r1", "name": "NAS", "backend": "sftp", "initialized": True, "check_schedule": "weekly",
     "check_read_data": 5, "healthcheck_url": "", "host": "nas.lan", "port": 22, "remote_path": "/srv/r",
     "user": "bk", "last_check": LOCKED_CHECK, "next_check": "Mon 2026-10-19 00:00:00 EDT"},
    {"id": "r2", "name": "Offsite", "backend": "sftp", "initialized": False, "check_schedule": "",
     "check_read_data": 0, "healthcheck_url": "", "host": "off", "port": 22, "remote_path": "/b", "user": "u",
     "last_check": None, "next_check": None},
]
JOBS = [
    {"id": "j1", "name": "home", "repo_id": "r1", "source_paths": ["/home"], "exclude_patterns": [],
     "schedule": "daily", "keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6, "keep_yearly": 0,
     "enabled": True, "pre_command": "", "post_command": "", "healthcheck_url": "",
     "last_run": {"status": "failure", "started_at": "2026-10-12T02:00:00+00:00", "finished_at": None,
                  "blocked_by_lock": True},
     "next_run": "Tue 2026-10-13 00:00:00 EDT"},
    {"id": "j2", "name": "etc", "repo_id": "r1", "source_paths": ["/etc"], "exclude_patterns": ["*.tmp"],
     "schedule": "*-*-* 03:00:00", "keep_daily": 1, "keep_weekly": 0, "keep_monthly": 0, "keep_yearly": 0,
     "enabled": False, "pre_command": "", "post_command": "", "healthcheck_url": "", "last_run": None,
     "next_run": None},
]
SNAPSHOTS = [{"id": "a" * 64, "short_id": "aaaaaaaa", "time": "2026-10-11T02:00:00+00:00", "paths": ["/home"],
              "hostname": "lab", "summary": {"total_files_processed": 12, "total_bytes_processed": 1}}]
FILES = {
    "/": [{"path": "/home", "name": "home", "type": "dir", "size": 0}],
    "/home": [{"path": "/home/alice", "name": "alice", "type": "dir", "size": 0},
              {"path": "/home/notes.txt", "name": "notes.txt", "type": "file", "size": 2048}],
}


class FakeConnection:
    instances = []
    connect_errors = []
    helper_path = rm.HELPER_PATH
    configured = True

    def __init__(self, server, **credentials):
        self.server = server
        self.credentials = credentials
        self.calls = []
        self.helper_path = type(self).helper_path
        self.configured = type(self).configured
        FakeConnection.instances.append(self)

    def connect(self):
        if FakeConnection.connect_errors:
            raise FakeConnection.connect_errors.pop(0)

    def close(self):
        pass

    def status(self):
        return {"installed": True, "version": "restic 0.18.0", "configured": self.configured}

    def setup(self):
        self.calls.append(("setup",))
        self.configured = True
        return self.status()

    def list_repos(self):
        return [dict(r) for r in REPOS]

    def list_jobs(self):
        return [dict(j) for j in JOBS]

    def __getattr__(self, name):
        # Every other helper call is just recorded.
        def record(*args, **kwargs):
            self.calls.append((name, *args, *([kwargs] if kwargs else [])))
            return {"create_repo": {"repo": {}, "generated_password": "pw", "public_key": "ssh-ed25519 AAA"},
                    "unlock_repo": {"unlocked": True, "output": "removed 1 lock"},
                    "list_snapshots": SNAPSHOTS,
                    "repo_stats": {"size": 4096, "uncompressed_size": None, "snapshot_count": 1},
                    "list_job_runs": [{"id": "x", "status": "failure", "started_at": "2026-10-12T02:00:00+00:00",
                                       "finished_at": None, "output_tail": "Fatal: locked"}],
                    "list_snapshot_files": FILES.get(args[2] if len(args) > 2 else "/", []),
                    "find_snapshot_files": {"matches": FILES["/home"][1:], "truncated": False},
                    }.get(name, {})

        return record


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch):
    FakeConnection.instances = []
    FakeConnection.connect_errors = []
    FakeConnection.helper_path = rm.HELPER_PATH
    FakeConnection.configured = True

    def run(fn, on_result=None, on_error=None):
        try:
            result = fn()
        except Exception as error:  # noqa: BLE001 -- mirrors run_in_background
            if on_error is not None:
                on_error(error)
            return
        if on_result is not None:
            on_result(result)

    monkeypatch.setattr(async_utils, "run_in_background", run)


@pytest.fixture
def yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)


def _make(qtbot):
    widget = w.ResticManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)
    return widget


def _calls(name):
    return [c for c in FakeConnection.instances[-1].calls if c[0] == name]


def test_connects_and_lists_repos_and_jobs(qtbot):
    widget = _make(qtbot)

    assert widget.stack.currentWidget() is widget.main_page
    assert widget.server_label.text().startswith("restic 0.18.0")
    row = [widget.repo_table.item(0, c).text() for c in range(6)]
    assert row[:3] == ["NAS", "SFTP", "bk@nas.lan:/srv/r"]
    assert row[3].startswith("Failure, ") and row[4:] == ["Mon 2026-10-19 00:00:00 EDT", "Ready"]
    assert widget.repo_table.item(1, 5).text() == "Needs key authorized on remote"
    job = [widget.job_table.item(0, c).text() for c in range(7)]
    assert job[:3] == ["home", "NAS", "Daily"] and job[5:] == ["7 daily, 4 weekly, 6 monthly, 0 yearly", "Enabled"]
    # a disabled job has no next run; a custom schedule shows as written
    assert widget.job_table.item(1, 4).text() == "-"
    assert widget.job_table.item(1, 2).text() == "*-*-* 03:00:00"
    assert widget.create_job_button.isEnabled()


def test_failure_banners_offer_to_remove_stale_locks(qtbot):
    widget = _make(qtbot)

    assert not widget.repo_banner.isHidden() and "1 repository failed its last check" in widget.repo_banner.text()
    assert 'href="unlock:r1"' in widget.repo_banner.text()
    assert "home could not finish because repository NAS is locked" in widget.job_banner.text()

    widget.job_banner.linkActivated.emit("unlock:r1")

    assert _calls("unlock_repo") == [("unlock_repo", "r1")]


def test_missing_module_shows_the_install_page(qtbot):
    FakeConnection.helper_path = None
    widget = _make(qtbot)

    assert widget.stack.currentWidget() is widget.missing_page
    assert "cockpit-restic" in widget.missing_page.text()


def test_unconfigured_server_offers_setup(qtbot):
    FakeConnection.configured = False
    widget = _make(qtbot)
    assert widget.stack.currentWidget() is widget.setup_page

    widget.setup_button.click()

    assert _calls("setup") == [("setup",)]
    assert widget.stack.currentWidget() is widget.main_page


def test_prompts_for_sudo_password_and_reconnects(qtbot, monkeypatch):
    FakeConnection.connect_errors = [rh.SudoPasswordRequired()]
    monkeypatch.setattr(rw.QInputDialog, "getText", lambda *a, **k: ("pw", True))
    _make(qtbot)

    assert FakeConnection.instances[-1].credentials == {"sudo_password": "pw"}


def test_repo_buttons_follow_the_selection(qtbot):
    widget = _make(qtbot)
    assert not any(b.isEnabled() for b in widget.repo_buttons)

    widget.repo_table.selectRow(1)
    assert widget.init_button.isVisibleTo(widget) and not any(b.isEnabled() for b in widget.repo_buttons)
    widget.init_button.click()
    assert _calls("init_repo") == [("init_repo", "r2")]

    widget.repo_table.selectRow(0)
    assert not widget.init_button.isVisibleTo(widget) and all(b.isEnabled() for b in widget.repo_buttons)
    widget.repo_buttons[1].click()  # Check Now
    assert _calls("trigger_check") == [("trigger_check", "r1")]


def test_create_sftp_repo_shows_its_secrets(qtbot, monkeypatch):
    widget = _make(qtbot)
    shown = []

    def fill(dialog):
        dialog.name.setText("Cloud")
        dialog.backend.setCurrentIndex(1)
        dialog.host.setText("cloud.lan")
        dialog.user.setText("bk")
        dialog.remote_path.setText("/srv/cloud")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.RepoDialog, "exec", fill)
    monkeypatch.setattr(dialogs.SecretsDialog, "exec", lambda d: shown.append(d) or 0)

    widget.create_repo()

    assert _calls("create_repo") == [("create_repo", {"name": "Cloud", "backend": "sftp", "host": "cloud.lan",
                                                      "port": 22, "user": "bk", "remote_path": "/srv/cloud"})]
    secrets = shown[0]
    assert secrets.fields["password"].text() == "pw" and secrets.fields["public_key"].text() == "ssh-ed25519 AAA"
    assert not secrets.done_button.isEnabled()
    secrets.saved.setChecked(True)
    assert secrets.done_button.isEnabled()


def test_repo_dialog_validates_paths(qtbot, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warnings.append(text))
    dialog = dialogs.RepoDialog()
    qtbot.addWidget(dialog)
    dialog.name.setText("x")
    dialog.path.setText("relative")
    dialog._accept()
    assert warnings == ["The repository path must be an absolute path."]
    assert dialog.form.isRowVisible(dialog.path) and not dialog.form.isRowVisible(dialog.host)


def test_health_check_settings_save(qtbot, monkeypatch):
    widget = _make(qtbot)

    def edit(dialog):
        assert dialog.schedule.schedule() == "weekly" and dialog.read_data.value() == 5
        dialog.schedule.choice.setCurrentIndex(dialog.schedule.choice.findData("never"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.HealthCheckDialog, "exec", edit)
    widget.edit_health_checks(REPOS[0])

    assert _calls("update_repo") == [("update_repo", "r1", {"check_schedule": "", "check_read_data": 5,
                                                            "healthcheck_url": ""})]


def test_job_dialog_round_trips_a_job(qtbot):
    dialog = dialogs.JobDialog(JOBS[1], REPOS[:1])
    qtbot.addWidget(dialog)

    values = dialog.values()

    assert values["schedule"] == "*-*-* 03:00:00" and dialog.schedule.custom.text() == "*-*-* 03:00:00"
    assert values == {"name": "etc", "repo_id": "r1", "source_paths": ["/etc"], "exclude_patterns": ["*.tmp"],
                      "schedule": "*-*-* 03:00:00", "keep_daily": 1, "keep_weekly": 0, "keep_monthly": 0,
                      "keep_yearly": 0, "enabled": False, "pre_command": "", "post_command": "",
                      "healthcheck_url": ""}
    new = dialogs.JobDialog(None, REPOS[:1])
    qtbot.addWidget(new)
    assert new.values()["schedule"] == "daily" and new.values()["keep_daily"] == 7


def test_run_edit_and_delete_jobs(qtbot, monkeypatch, yes):
    widget = _make(qtbot)
    widget.job_table.selectRow(0)

    widget.job_buttons[0].click()
    monkeypatch.setattr(dialogs.JobDialog, "exec", lambda d: QDialog.DialogCode.Accepted)
    widget.job_buttons[1].click()
    widget.job_buttons[3].click()

    assert _calls("trigger_job") == [("trigger_job", "j1")]
    assert _calls("update_job")[0][1] == "j1" and _calls("update_job")[0][2]["name"] == "home"
    assert _calls("delete_job") == [("delete_job", "j1")]


def test_run_history_shows_the_output(qtbot, monkeypatch):
    widget = _make(qtbot)
    shown = []
    monkeypatch.setattr(dialogs.RunsDialog, "exec", lambda d: shown.append(d) or 0)

    widget.show_runs(JOBS[0])

    assert shown[0].table.rowCount() == 1 and shown[0].output.toPlainText() == "Fatal: locked"


def test_snapshots_restore_chosen_files(qtbot, monkeypatch, yes):
    widget = _make(qtbot)
    snapshots = []
    monkeypatch.setattr(dialogs.SnapshotsDialog, "exec", lambda d: snapshots.append(d) or 0)
    widget.browse_snapshots(REPOS[0])
    dialog = snapshots[0]
    assert dialog.table.rowCount() == 1 and "4.0 KB" in dialog.stats.text()

    def choose(restore):
        restore.restore_some.setChecked(True)
        restore._browse()
        tree = restore.browser.tree
        home = tree.topLevelItem(0)
        home.setExpanded(True)
        alice, notes = home.child(0), home.child(1)
        notes.setCheckState(0, Qt.CheckState.Checked)
        assert restore.paths.toPlainText() == "/home/notes.txt"
        home.setCheckState(0, Qt.CheckState.Checked)
        # the folder covers what was inside it
        assert restore.paths.toPlainText() == "/home"
        assert alice.checkState(0) == Qt.CheckState.Checked
        assert not alice.flags() & Qt.ItemFlag.ItemIsUserCheckable
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.RestoreDialog, "exec", choose)
    dialog.table.selectRow(0)
    dialog.restore(dialog.selected())

    assert _calls("restore_snapshot") == [("restore_snapshot", "r1", "a" * 64, "/var/restore", ["/home"])]

    dialog.delete(dialog.selected())
    assert _calls("forget_snapshots") == [("forget_snapshots", "r1", ["a" * 64])]


def test_snapshot_search_lists_matches(qtbot):
    connection = FakeConnection(SERVER)
    toggled = []
    browser = dialogs.SnapshotBrowser(connection, "r1", "abcd1234", lambda p, c: toggled.append((p, c)))
    qtbot.addWidget(browser)
    browser.query.setText("notes")

    browser.search()

    assert browser.pages.currentIndex() == 1 and browser.results.topLevelItem(0).text(0) == "/home/notes.txt"
    browser.results.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert toggled == [("/home/notes.txt", True)]

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from it_toolbox.core import settings
from it_toolbox.core.ftp_client import FtpClientError
from it_toolbox.core.sftp_stress_test import StressStats
from it_toolbox.widgets import sftp_server_test_widget
from it_toolbox.widgets.sftp_server_test_widget import (
    IDLE,
    RUNNING,
    SftpServerTestWidget,
)


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)
    return tmp_path


class StubTest:
    """Stands in for StressTest: records calls, no network."""

    instances: list["StubTest"] = []
    prepare_error: Exception | None = None

    def __init__(self, config):
        self.config = config
        self.stats = StressStats()
        self.root = None
        self.calls = []
        StubTest.instances.append(self)

    def prepare(self):
        self.calls.append("prepare")
        if StubTest.prepare_error is not None:
            raise StubTest.prepare_error
        self.root = "/home/tester/it-toolbox-sftp-test-x"
        return self.root

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def join(self, timeout=None):
        self.calls.append("join")
        self.stats.mark_stopped()

    def cleanup(self):
        self.calls.append("cleanup")
        return 7


@pytest.fixture(autouse=True)
def stub_test(monkeypatch):
    StubTest.instances = []
    StubTest.prepare_error = None
    monkeypatch.setattr(sftp_server_test_widget, "StressTest", StubTest)
    return StubTest


def _make(qtbot):
    widget = SftpServerTestWidget()
    qtbot.addWidget(widget)
    widget._host_edit.setText("sftp.example.com")
    widget._port_spin.setValue(2222)
    widget._username_edit.setText("tester")
    widget._password_edit.setText("hunter2")
    widget._workers_spin.setValue(8)
    return widget


def test_config_reflects_the_form(qtbot):
    widget = _make(qtbot)
    widget._min_size.set_size(4, "KB")
    widget._max_size.set_size(64, "KB")

    config = widget.config()

    assert (config.host, config.port, config.username, config.password) == (
        "sftp.example.com",
        2222,
        "tester",
        "hunter2",
    )
    assert config.workers == 8
    assert (config.min_file_size, config.max_file_size) == (4096, 65536)
    assert config.cleanup is True


def test_file_sizes_use_the_chosen_units(qtbot):
    widget = _make(qtbot)
    widget._max_size.set_size(2, "GB")
    widget._min_size.set_size(500, "MB")

    config = widget.config()

    assert (config.min_file_size, config.max_file_size) == (500 * 1024**2, 2 * 1024**3)


def test_file_size_range_stays_consistent(qtbot):
    widget = _make(qtbot)
    widget._max_size.set_size(10, "KB")
    widget._min_size.set_size(50, "KB")
    assert widget._max_size.size() == (50, "KB")

    widget._max_size.set_size(3, "MB")
    widget._min_size.unit_combo.setCurrentText("GB")  # 50 GB > 3 MB
    assert widget._max_size.size() == (50, "GB")

    widget._max_size.unit_combo.setCurrentText("KB")  # 50 KB < 50 GB
    assert widget._min_size.size() == (50, "KB")


def test_start_requires_host_and_username(qtbot, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a))
    widget = SftpServerTestWidget()
    qtbot.addWidget(widget)

    widget.start()

    assert warnings
    assert StubTest.instances == []


def test_start_runs_then_stop_cleans_up(qtbot):
    widget = _make(qtbot)
    titles = []
    widget.title_changed.connect(titles.append)

    widget.start()
    qtbot.waitUntil(lambda: widget.state == RUNNING, timeout=3000)
    test = StubTest.instances[0]
    assert test.calls == ["prepare", "start"]
    assert titles == ["SFTP Test: sftp.example.com"]
    assert not widget._server_box.isEnabled()
    assert widget._stop_button.isEnabled()

    test.stats.record("upload", 0.05)
    test.stats.record("list", 0.01, error="Permission denied", worker=3)
    widget._refresh_stats()
    assert widget._stat_rows["upload"].text(1) == "1"
    assert widget._stat_rows["list"].text(2) == "1"
    assert widget._summary_labels["errors"].text() == "1"
    assert widget._errors_tree.topLevelItemCount() == 1
    assert widget._errors_tree.topLevelItem(0).text(3) == "Permission denied"
    widget._refresh_stats()
    assert widget._errors_tree.topLevelItemCount() == 1  # not re-added

    widget.stop()
    qtbot.waitUntil(lambda: widget.state == IDLE, timeout=3000)
    assert test.calls == ["prepare", "start", "stop", "join", "cleanup"]
    assert "Removed /home/tester/it-toolbox-sftp-test-x" in widget._status_label.text()
    assert widget._start_button.isEnabled()


def test_keeping_the_test_folder_skips_cleanup(qtbot):
    widget = _make(qtbot)
    widget._cleanup_check.setChecked(False)

    widget.start()
    qtbot.waitUntil(lambda: widget.state == RUNNING, timeout=3000)
    widget.stop()
    qtbot.waitUntil(lambda: widget.state == IDLE, timeout=3000)

    assert "cleanup" not in StubTest.instances[0].calls
    assert "left in" in widget._status_label.text()


def test_connection_failure_returns_to_the_form(qtbot):
    StubTest.prepare_error = FtpClientError("Authentication failed for tester@sftp.example.com.")
    widget = _make(qtbot)

    widget.start()
    qtbot.waitUntil(lambda: widget.state == IDLE, timeout=3000)

    assert "Authentication failed" in widget._status_label.text()
    assert widget._server_box.isEnabled()


def test_last_settings_are_remembered_without_the_password(qtbot):
    widget = _make(qtbot)
    widget.start()
    qtbot.waitUntil(lambda: widget.state == RUNNING, timeout=3000)
    widget.close_session()

    saved = settings.load_sftp_server_test_defaults()
    assert saved["host"] == "sftp.example.com"
    assert saved["workers"] == 8
    assert "hunter2" not in str(saved)

    again = SftpServerTestWidget()
    qtbot.addWidget(again)
    assert again._host_edit.text() == "sftp.example.com"
    assert again._port_spin.value() == 2222
    assert again._password_edit.text() == ""


def test_settings_saved_before_units_existed_load_as_kb(qtbot):
    settings.save_sftp_server_test_defaults({"host": "old.example.com", "min_kb": 8, "max_kb": 2048})

    widget = SftpServerTestWidget()
    qtbot.addWidget(widget)

    assert widget._min_size.size() == (8, "KB")
    assert widget._max_size.size() == (2048, "KB")


def test_save_and_load_a_test_configuration(qtbot, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Big files", True))
    widget = _make(qtbot)
    widget._max_size.set_size(4, "GB")
    widget._min_size.set_size(1, "GB")
    widget._cleanup_check.setChecked(False)
    changed = []
    widget.saved_tests_changed.connect(lambda: changed.append(True))

    widget.save_test_config()

    saved = settings.load_sftp_server_test_configs()
    assert list(saved) == ["Big files"]
    assert saved["Big files"]["host"] == "sftp.example.com"
    assert (saved["Big files"]["max_size"], saved["Big files"]["max_unit"]) == (4, "GB")
    assert "hunter2" not in str(saved)
    assert widget.saved_name == "Big files"
    assert changed == [True]

    other = SftpServerTestWidget()
    qtbot.addWidget(other)
    titles = []
    other.title_changed.connect(titles.append)
    other._host_edit.setText("elsewhere")
    other._password_edit.setText("secret")

    assert other.load_saved_test("Big files") is True
    assert other._host_edit.text() == "sftp.example.com"
    assert other._port_spin.value() == 2222
    assert other._workers_spin.value() == 8
    assert other._min_size.size() == (1, "GB")
    assert other._max_size.size() == (4, "GB")
    assert not other._cleanup_check.isChecked()
    assert other._password_edit.text() == ""
    assert titles == ["SFTP Test: Big files"]
    assert other.load_saved_test("missing") is False


def test_saving_over_another_saved_test_asks_first(qtbot, monkeypatch):
    settings.save_sftp_server_test_configs({"Prod": {"host": "prod.example.com"}})
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Prod", True))
    questions = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: questions.append(a) or QMessageBox.StandardButton.No
    )
    widget = _make(qtbot)

    widget.save_test_config()

    assert questions
    assert settings.load_sftp_server_test_configs()["Prod"]["host"] == "prod.example.com"


def test_saving_is_locked_while_a_test_runs(qtbot):
    widget = _make(qtbot)
    widget.start()
    qtbot.waitUntil(lambda: widget.state == RUNNING, timeout=3000)

    assert not widget._save_config_button.isEnabled()
    widget.close_session()


def test_closing_a_running_tab_stops_and_cleans_up(qtbot):
    widget = _make(qtbot)
    widget.start()
    qtbot.waitUntil(lambda: widget.state == RUNNING, timeout=3000)
    test = StubTest.instances[0]

    widget.close_session()

    qtbot.waitUntil(lambda: "cleanup" in test.calls, timeout=3000)
    assert test.calls[2:] == ["stop", "join", "cleanup"]

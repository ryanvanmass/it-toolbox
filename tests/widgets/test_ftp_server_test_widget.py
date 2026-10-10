import pytest
from PySide6.QtWidgets import QInputDialog

from it_toolbox.core import settings
from it_toolbox.core.sftp_stress_test import StressStats
from it_toolbox.widgets import ftp_server_test_widget
from it_toolbox.widgets.ftp_server_test_widget import FtpServerTestWidget
from it_toolbox.widgets.sftp_server_test_widget import IDLE, RUNNING


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)
    return tmp_path


class StubTest:
    """Stands in for FtpStressTest: records calls, no network."""

    instances: list["StubTest"] = []

    def __init__(self, config):
        self.config = config
        self.stats = StressStats()
        self.root = None
        self.calls = []
        StubTest.instances.append(self)

    def prepare(self):
        self.calls.append("prepare")
        self.root = "/it-toolbox-ftp-test-x"
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
        return 3


@pytest.fixture(autouse=True)
def stub_test(monkeypatch):
    StubTest.instances = []
    monkeypatch.setattr(ftp_server_test_widget, "FtpStressTest", StubTest)
    return StubTest


def _make(qtbot):
    widget = FtpServerTestWidget()
    qtbot.addWidget(widget)
    widget._host_edit.setText("ftp.example.com")
    widget._username_edit.setText("tester")
    widget._password_edit.setText("hunter2")
    return widget


def test_defaults_to_plain_ftp_on_port_21(qtbot):
    widget = _make(qtbot)

    config = widget.config()

    assert (config.host, config.port, config.username, config.password) == ("ftp.example.com", 21, "tester", "hunter2")
    assert config.use_tls is False
    assert not hasattr(config, "key_path")


def test_explicit_ftps_and_sizes(qtbot):
    widget = _make(qtbot)
    widget._security_combo.setCurrentIndex(widget._security_combo.findData("explicit_tls"))
    widget._max_size.set_size(2, "GB")
    widget._min_size.set_size(10, "MB")

    config = widget.config()

    assert config.use_tls is True
    assert (config.min_file_size, config.max_file_size) == (10 * 1024**2, 2 * 1024**3)


def test_start_runs_an_ftp_test_then_stop_cleans_up(qtbot):
    widget = _make(qtbot)
    titles = []
    widget.title_changed.connect(titles.append)

    widget.start()
    qtbot.waitUntil(lambda: widget.state == RUNNING, timeout=3000)
    test = StubTest.instances[0]
    assert test.calls == ["prepare", "start"]
    assert titles == ["FTP Test: ftp.example.com"]

    widget.stop()
    qtbot.waitUntil(lambda: widget.state == IDLE, timeout=3000)
    assert test.calls == ["prepare", "start", "stop", "join", "cleanup"]


def test_form_is_remembered_separately_from_sftp_without_the_password(qtbot):
    widget = _make(qtbot)
    widget._security_combo.setCurrentIndex(1)
    widget.start()
    qtbot.waitUntil(lambda: widget.state == RUNNING, timeout=3000)

    saved = settings.load_ftp_server_test_defaults()
    assert saved["host"] == "ftp.example.com"
    assert saved["security"] == "explicit_tls"
    assert "password" not in saved and "hunter2" not in str(saved)
    assert settings.load_sftp_server_test_defaults() == {}

    again = FtpServerTestWidget()
    qtbot.addWidget(again)
    assert again._host_edit.text() == "ftp.example.com"
    assert again._security_combo.currentData() == "explicit_tls"
    assert again._password_edit.text() == ""
    widget.close_session()


def test_saved_tests_go_to_the_ftp_list(qtbot, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("NAS", True))
    widget = _make(qtbot)

    widget.save_test_config()

    assert list(settings.load_ftp_server_test_configs()) == ["NAS"]
    assert settings.load_sftp_server_test_configs() == {}
    other = FtpServerTestWidget()
    qtbot.addWidget(other)
    assert other.load_saved_test("NAS")
    assert other._host_edit.text() == "ftp.example.com"

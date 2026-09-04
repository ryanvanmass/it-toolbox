from it_toolbox.core import update_checker
from it_toolbox.modules.settings.ui.main_view import SettingsView


def _make_view(qtbot, monkeypatch, installed_version="1.0.0"):
    monkeypatch.setattr(update_checker, "get_installed_version", lambda: installed_version)
    view = SettingsView()
    qtbot.addWidget(view)
    return view


def test_shows_installed_version_on_load(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.2.3")

    assert "1.2.3" in view._update_status_label.text()
    assert view._update_link_button.isHidden()


def test_check_updates_reports_no_releases_yet(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    monkeypatch.setattr(update_checker, "get_latest_release", lambda: None)

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "no releases published yet" in view._update_status_label.text())
    assert view._update_link_button.isHidden()
    assert view._check_updates_button.isEnabled()


def test_check_updates_reports_up_to_date(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0")
    monkeypatch.setattr(
        update_checker,
        "get_latest_release",
        lambda: update_checker.ReleaseInfo(version="1.0.0", html_url="https://example.com"),
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Up to date" in view._update_status_label.text())
    assert view._update_link_button.isHidden()


def test_check_updates_reports_available_update_and_shows_link(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0")
    monkeypatch.setattr(
        update_checker,
        "get_latest_release",
        lambda: update_checker.ReleaseInfo(version="2.0.0", html_url="https://example.com/v2"),
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Update available" in view._update_status_label.text())
    assert "2.0.0" in view._update_status_label.text()
    assert not view._update_link_button.isHidden()
    assert view._latest_release_url == "https://example.com/v2"


def test_check_updates_handles_network_error(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    def _raise():
        raise RuntimeError("network down")

    monkeypatch.setattr(update_checker, "get_latest_release", _raise)

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Couldn't check for updates" in view._update_status_label.text())
    assert view._check_updates_button.isEnabled()

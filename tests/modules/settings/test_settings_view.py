from it_toolbox.core import rclone_client, settings, update_checker
from it_toolbox.modules.settings.ui.main_view import SettingsView


def _make_view(
    qtbot,
    monkeypatch,
    installed_version="1.0.0",
    rclone_available=False,
    rclone_override=None,
):
    monkeypatch.setattr(update_checker, "get_installed_version", lambda: installed_version)
    monkeypatch.setattr(rclone_client, "is_available", lambda: rclone_available)
    monkeypatch.setattr(rclone_client, "rclone_executable", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(settings, "load_rclone_path", lambda: rclone_override)
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


def test_rclone_section_shows_found_path_when_available(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, rclone_available=True)

    assert "/usr/bin/rclone" in view._rclone_status_label.text()
    assert view._rclone_location_button.text() == "Set rclone Location…"
    assert view._rclone_use_path_button.isHidden()


def test_rclone_section_shows_not_found_message(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, rclone_available=False)

    assert "not found" in view._rclone_status_label.text()


def test_rclone_section_shows_change_and_use_path_buttons_when_override_set(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, rclone_override="/opt/rclone/rclone")

    assert view._rclone_location_button.text() == "Change rclone Location…"
    assert not view._rclone_use_path_button.isHidden()


def test_set_rclone_location_saves_and_refreshes(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    monkeypatch.setattr(
        "it_toolbox.widgets.rclone_location_picker.QFileDialog.getOpenFileName",
        lambda *a, **k: ("/opt/rclone/rclone", ""),
    )
    saved = []
    monkeypatch.setattr(settings, "save_rclone_path", lambda path: saved.append(path))

    view._on_rclone_location_clicked()

    assert saved == ["/opt/rclone/rclone"]


def test_use_rclone_from_path_clears_override(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, rclone_override="/opt/rclone/rclone")
    saved = []
    monkeypatch.setattr(settings, "save_rclone_path", lambda path: saved.append(path))

    view._on_use_rclone_from_path_clicked()

    assert saved == [None]


def test_download_rclone_updates_status_on_success(qtbot, monkeypatch, tmp_path):
    view = _make_view(qtbot, monkeypatch)
    downloaded_path = tmp_path / "rclone"
    monkeypatch.setattr(rclone_client, "download_latest", lambda dest_dir: downloaded_path)

    view._on_download_rclone_clicked()

    qtbot.waitUntil(lambda: view._rclone_download_button.isEnabled())


def test_download_rclone_shows_error_on_failure(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    def _raise(dest_dir):
        raise rclone_client.UnsupportedPlatformError("no build for this platform")

    monkeypatch.setattr(rclone_client, "download_latest", _raise)

    view._on_download_rclone_clicked()

    qtbot.waitUntil(lambda: "Couldn't download rclone" in view._rclone_status_label.text())
    assert view._rclone_download_button.isEnabled()

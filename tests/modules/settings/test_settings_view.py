import subprocess

from it_toolbox.core import rclone_client, settings, update_checker
from it_toolbox.core.auth import gcp_auth
from it_toolbox.modules.connection_manager import qemu_client
from it_toolbox.modules.settings.ui import main_view as settings_main_view
from it_toolbox.modules.settings.ui.main_view import SettingsView


def _make_view(
    qtbot,
    monkeypatch,
    installed_version="1.0.0",
    rclone_available=False,
    rclone_override=None,
    gcloud_available=False,
    platform_system="Linux",
    qemu_available=False,
):
    # Keep tests hermetic — exercising Settings-page wiring, not real
    # gcloud/rclone discovery, so they shouldn't depend on (or spawn a
    # background subprocess check against) whatever's actually installed
    # on the machine running the test. A real gcp_auth.is_available()
    # here would fire a genuine background `gcloud` subprocess call via
    # run_in_background, which has been observed to interfere with other
    # tests' forkpty-based terminal tests when run in the same session.
    monkeypatch.setattr(update_checker, "get_installed_version", lambda: installed_version)
    monkeypatch.setattr(rclone_client, "is_available", lambda: rclone_available)
    monkeypatch.setattr(rclone_client, "rclone_executable", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(settings, "load_rclone_path", lambda: rclone_override)
    monkeypatch.setattr(gcp_auth, "is_available", lambda: gcloud_available)
    monkeypatch.setattr(qemu_client, "is_available", lambda: qemu_available)
    monkeypatch.setattr(settings_main_view.platform, "system", lambda: platform_system)
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


def test_gcloud_section_shows_not_found_when_gcloud_missing(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcloud_available=False)

    assert "not found" in view._gcloud_status_label.text()
    assert not view._gcloud_sign_in_button.isEnabled()
    assert not view._gcloud_sign_out_button.isEnabled()


def test_gcloud_section_shows_signed_in_account(qtbot, monkeypatch):
    monkeypatch.setattr(gcp_auth, "get_active_account", lambda: "someone@example.com")
    view = _make_view(qtbot, monkeypatch, gcloud_available=True)

    qtbot.waitUntil(lambda: "someone@example.com" in view._gcloud_status_label.text())
    assert view._gcloud_sign_out_button.isEnabled()


def test_gcloud_section_shows_not_signed_in(qtbot, monkeypatch):
    monkeypatch.setattr(gcp_auth, "get_active_account", lambda: None)
    view = _make_view(qtbot, monkeypatch, gcloud_available=True)

    qtbot.waitUntil(lambda: "Not signed in" in view._gcloud_status_label.text())
    assert not view._gcloud_sign_out_button.isEnabled()


def test_gcloud_sign_in_updates_status_on_success(qtbot, monkeypatch):
    monkeypatch.setattr(gcp_auth, "get_active_account", lambda: None)
    view = _make_view(qtbot, monkeypatch, gcloud_available=True)
    qtbot.waitUntil(lambda: "Not signed in" in view._gcloud_status_label.text())

    monkeypatch.setattr(gcp_auth, "sign_in", lambda: "someone@example.com")
    view._on_gcloud_sign_in_clicked()

    qtbot.waitUntil(lambda: "someone@example.com" in view._gcloud_status_label.text())
    assert view._gcloud_sign_out_button.isEnabled()


def test_gcloud_sign_in_error_shows_message(qtbot, monkeypatch):
    monkeypatch.setattr(gcp_auth, "get_active_account", lambda: None)
    view = _make_view(qtbot, monkeypatch, gcloud_available=True)
    qtbot.waitUntil(lambda: "Not signed in" in view._gcloud_status_label.text())

    def _raise():
        raise RuntimeError("login failed")

    monkeypatch.setattr(gcp_auth, "sign_in", _raise)
    view._on_gcloud_sign_in_clicked()

    qtbot.waitUntil(lambda: "gcloud error" in view._gcloud_status_label.text())
    assert view._gcloud_sign_in_button.isEnabled()


def test_gcloud_sign_out_updates_status(qtbot, monkeypatch):
    monkeypatch.setattr(gcp_auth, "get_active_account", lambda: "someone@example.com")
    view = _make_view(qtbot, monkeypatch, gcloud_available=True)
    qtbot.waitUntil(lambda: "someone@example.com" in view._gcloud_status_label.text())

    monkeypatch.setattr(gcp_auth, "sign_out", lambda: None)
    view._on_gcloud_sign_out_clicked()

    qtbot.waitUntil(lambda: "Not signed in" in view._gcloud_status_label.text())


def test_qemu_section_not_applicable_off_linux(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, platform_system="Windows")

    assert "Not applicable" in view._qemu_status_label.text()


def test_qemu_section_shows_found_when_virsh_available(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, platform_system="Linux", qemu_available=True)

    assert "virsh found" in view._qemu_status_label.text()


def test_qemu_section_shows_install_instructions_when_missing(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, platform_system="Linux", qemu_available=False)

    assert "virsh not found" in view._qemu_status_label.text()
    assert "apt install libvirt-clients" in view._qemu_status_label.text()


def test_freerdp_section_not_applicable_off_windows(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, platform_system="Linux")

    assert "Not applicable" in view._freerdp_status_label.text()
    assert not hasattr(view, "_freerdp_fetch_button")


def test_freerdp_section_shows_loaded_status_on_windows(qtbot, monkeypatch):
    monkeypatch.setattr(settings_main_view, "freerdp_client", object())

    view = _make_view(qtbot, monkeypatch, platform_system="Windows")

    assert "loaded" in view._freerdp_status_label.text()


def test_freerdp_section_shows_not_found_status_on_windows(qtbot, monkeypatch):
    monkeypatch.setattr(settings_main_view, "freerdp_client", None)

    view = _make_view(qtbot, monkeypatch, platform_system="Windows")

    assert "not found" in view._freerdp_status_label.text()


def test_fetch_freerdp_shows_error_when_script_missing(qtbot, monkeypatch):
    monkeypatch.setattr(settings_main_view, "freerdp_client", None)
    monkeypatch.setattr(
        settings_main_view, "_FREERDP_FETCH_SCRIPT", settings_main_view.Path("/no/such/script.ps1")
    )
    view = _make_view(qtbot, monkeypatch, platform_system="Windows")

    view._on_fetch_freerdp_clicked()

    assert "Fetch script not found" in view._freerdp_status_label.text()


def test_fetch_freerdp_runs_script_and_re_checks_status_on_success(qtbot, monkeypatch, tmp_path):
    # freerdp_client is genuinely importable on this dev machine (real
    # libfreerdp3 was installed for the embedded-RDP work) — so a real
    # re-import after a successful fetch naturally succeeds here without
    # needing to fake the module itself, only the script run + env var.
    monkeypatch.setattr(settings_main_view, "freerdp_client", None)
    script = tmp_path / "fetch.ps1"
    script.write_text("")
    monkeypatch.setattr(settings_main_view, "_FREERDP_FETCH_SCRIPT", script)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        settings_main_view.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], returncode=0, stdout="", stderr=""),
    )
    view = _make_view(qtbot, monkeypatch, platform_system="Windows")

    view._on_fetch_freerdp_clicked()

    qtbot.waitUntil(lambda: view._freerdp_fetch_button.isEnabled())
    assert "loaded" in view._freerdp_status_label.text()
    assert settings_main_view.freerdp_client is not None


def test_fetch_freerdp_shows_error_on_script_failure(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(settings_main_view, "freerdp_client", None)
    script = tmp_path / "fetch.ps1"
    script.write_text("")
    monkeypatch.setattr(settings_main_view, "_FREERDP_FETCH_SCRIPT", script)
    monkeypatch.setattr(
        settings_main_view.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], returncode=1, stdout="", stderr="boom"),
    )
    view = _make_view(qtbot, monkeypatch, platform_system="Windows")

    view._on_fetch_freerdp_clicked()

    qtbot.waitUntil(lambda: "Couldn't fetch FreeRDP DLLs" in view._freerdp_status_label.text())
    assert view._freerdp_fetch_button.isEnabled()

import subprocess

from it_toolbox.core import rclone_client, settings, update_checker
from it_toolbox.core.auth import gcp_auth
from it_toolbox.modules.connection_manager import qemu_client
from it_toolbox.modules.settings.ui import main_view as settings_main_view
from it_toolbox.modules.settings.ui.main_view import SettingsView


class _FakePath:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def is_file(self) -> bool:
        return self._exists


def _make_view(
    qtbot,
    monkeypatch,
    installed_version="1.0.0",
    rclone_available=False,
    rclone_override=None,
    gcloud_available=False,
    platform_system="Linux",
    qemu_available=False,
    default_rdp_resolution=None,
    rdp_keyboard_layout=0x0409,
    terminal_font_size=None,
    default_double_click_action="ask",
    jumpcloud_key_configured=False,
    gcp_ssh_key_override=None,
    gcp_ssh_public_key=None,
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
    monkeypatch.setattr(settings, "load_default_rdp_resolution", lambda: default_rdp_resolution)
    monkeypatch.setattr(settings, "load_rdp_keyboard_layout", lambda: rdp_keyboard_layout)
    monkeypatch.setattr(settings, "load_terminal_font_size", lambda: terminal_font_size)
    monkeypatch.setattr(
        settings, "load_default_double_click_action", lambda: default_double_click_action
    )
    monkeypatch.setattr(
        settings, "jumpcloud_api_key_path", lambda: _FakePath(jumpcloud_key_configured)
    )
    # Same hermeticity reasoning as above — real load_gcp_ssh_key_path()/
    # resolve_gcp_ssh_public_key() would otherwise read this machine's
    # actual ~/.ssh contents.
    monkeypatch.setattr(settings, "load_gcp_ssh_key_path", lambda: gcp_ssh_key_override)
    monkeypatch.setattr(settings, "resolve_gcp_ssh_public_key", lambda: gcp_ssh_public_key)
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
    monkeypatch.setattr(
        update_checker, "get_latest_release", lambda include_prerelease=False: None
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "no releases published yet" in view._update_status_label.text())
    assert view._update_link_button.isHidden()
    assert view._check_updates_button.isEnabled()


def test_check_updates_reports_up_to_date(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0")
    monkeypatch.setattr(
        update_checker,
        "get_latest_release",
        lambda include_prerelease=False: update_checker.ReleaseInfo(
            version="1.0.0", html_url="https://example.com"
        ),
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Up to date" in view._update_status_label.text())
    assert view._update_link_button.isHidden()


def test_check_updates_reports_available_update_and_shows_link(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0")
    monkeypatch.setattr(
        update_checker,
        "get_latest_release",
        lambda include_prerelease=False: update_checker.ReleaseInfo(
            version="2.0.0", html_url="https://example.com/v2"
        ),
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Update available" in view._update_status_label.text())
    assert "2.0.0" in view._update_status_label.text()
    assert not view._update_link_button.isHidden()
    assert view._latest_release_url == "https://example.com/v2"


def test_check_updates_handles_network_error(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    def _raise(include_prerelease=False):
        raise RuntimeError("network down")

    monkeypatch.setattr(update_checker, "get_latest_release", _raise)

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Couldn't check for updates" in view._update_status_label.text())
    assert view._check_updates_button.isEnabled()


def test_include_prerelease_checkbox_defaults_to_unchecked(qtbot, monkeypatch):
    monkeypatch.setattr(settings, "load_include_prerelease_updates", lambda: False)
    view = _make_view(qtbot, monkeypatch)

    assert not view._include_prerelease_checkbox.isChecked()


def test_include_prerelease_checkbox_preselects_saved_value(qtbot, monkeypatch):
    monkeypatch.setattr(settings, "load_include_prerelease_updates", lambda: True)
    view = _make_view(qtbot, monkeypatch)

    assert view._include_prerelease_checkbox.isChecked()


def test_toggling_include_prerelease_checkbox_saves_it(qtbot, monkeypatch):
    monkeypatch.setattr(settings, "load_include_prerelease_updates", lambda: False)
    saved = []
    monkeypatch.setattr(settings, "save_include_prerelease_updates", lambda v: saved.append(v))
    view = _make_view(qtbot, monkeypatch)

    view._include_prerelease_checkbox.setChecked(True)

    assert saved == [True]


def test_check_updates_passes_include_prerelease_flag(qtbot, monkeypatch):
    monkeypatch.setattr(settings, "load_include_prerelease_updates", lambda: True)
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0")
    calls = []

    def _fake_get_latest_release(include_prerelease=False):
        calls.append(include_prerelease)
        return update_checker.ReleaseInfo(version="1.0.0", html_url="https://example.com")

    monkeypatch.setattr(update_checker, "get_latest_release", _fake_get_latest_release)

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: calls == [True])


def test_install_update_button_hidden_on_non_windows(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Linux")
    monkeypatch.setattr(
        update_checker,
        "get_latest_release",
        lambda include_prerelease=False: update_checker.ReleaseInfo(
            version="2.0.0",
            html_url="https://example.com/v2",
            windows_installer_url="https://example.com/setup.exe",
        ),
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Update available" in view._update_status_label.text())
    assert view._install_update_button.isHidden()


def test_install_update_button_hidden_without_a_windows_asset(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Windows")
    monkeypatch.setattr(
        update_checker,
        "get_latest_release",
        lambda include_prerelease=False: update_checker.ReleaseInfo(
            version="2.0.0", html_url="https://example.com/v2"
        ),
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Update available" in view._update_status_label.text())
    assert view._install_update_button.isHidden()


def test_install_update_button_shown_on_windows_with_installer_asset(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Windows")
    monkeypatch.setattr(
        update_checker,
        "get_latest_release",
        lambda include_prerelease=False: update_checker.ReleaseInfo(
            version="2.0.0",
            html_url="https://example.com/v2",
            windows_installer_url="https://example.com/setup.exe",
        ),
    )

    view._check_updates_button.click()

    qtbot.waitUntil(lambda: "Update available" in view._update_status_label.text())
    assert not view._install_update_button.isHidden()
    assert view._pending_installer_url == "https://example.com/setup.exe"


def test_install_update_declined_does_not_download(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Windows")
    view._pending_installer_url = "https://example.com/setup.exe"
    view._install_update_button.show()
    monkeypatch.setattr(
        settings_main_view.QMessageBox,
        "question",
        lambda *a, **k: settings_main_view.QMessageBox.StandardButton.No,
    )
    calls = []
    monkeypatch.setattr(
        update_checker,
        "download_and_install_windows_update",
        lambda url, on_progress=None: calls.append(url),
    )

    view._install_update_button.click()

    assert calls == []


def test_install_update_accepted_downloads_installs_and_quits(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Windows")
    view._pending_installer_url = "https://example.com/setup.exe"
    view._install_update_button.show()
    monkeypatch.setattr(
        settings_main_view.QMessageBox,
        "question",
        lambda *a, **k: settings_main_view.QMessageBox.StandardButton.Yes,
    )
    calls = []
    monkeypatch.setattr(
        update_checker,
        "download_and_install_windows_update",
        lambda url, on_progress=None: calls.append(url),
    )
    quit_calls = []
    # Patching this instance's own _quit_application (rather than the
    # real, test-session-wide QApplication singleton's .quit()/.instance())
    # keeps this test from disturbing anything pytest-qt's own internals
    # depend on for every other test in this process.
    monkeypatch.setattr(view, "_quit_application", lambda: quit_calls.append(True))

    view._install_update_button.click()

    qtbot.waitUntil(lambda: quit_calls == [True])
    assert calls == ["https://example.com/setup.exe"]


def test_install_update_shows_progress_bar_during_download(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Windows")
    view._pending_installer_url = "https://example.com/setup.exe"
    view._install_update_button.show()
    monkeypatch.setattr(
        settings_main_view.QMessageBox,
        "question",
        lambda *a, **k: settings_main_view.QMessageBox.StandardButton.Yes,
    )

    def _fake_download(url, on_progress=None):
        assert on_progress is not None
        on_progress(50, 100)

    monkeypatch.setattr(update_checker, "download_and_install_windows_update", _fake_download)
    monkeypatch.setattr(view, "_quit_application", lambda: None)

    assert view._update_download_progress_bar.isHidden()
    view._install_update_button.click()

    qtbot.waitUntil(lambda: not view._update_download_progress_bar.isHidden())
    qtbot.waitUntil(lambda: view._update_download_progress_bar.value() == 50)
    assert view._update_download_progress_bar.maximum() == 100
    assert "50%" in view._update_status_label.text()


def test_install_update_failure_hides_progress_bar(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Windows")
    view._pending_installer_url = "https://example.com/setup.exe"
    view._install_update_button.show()
    monkeypatch.setattr(
        settings_main_view.QMessageBox,
        "question",
        lambda *a, **k: settings_main_view.QMessageBox.StandardButton.Yes,
    )

    def _raise(url, on_progress=None):
        raise update_checker.UpdateInstallError("installer exploded")

    monkeypatch.setattr(update_checker, "download_and_install_windows_update", _raise)

    view._install_update_button.click()

    qtbot.waitUntil(lambda: "Update install failed" in view._update_status_label.text())
    assert view._update_download_progress_bar.isHidden()


def test_install_update_failure_shows_error_and_reenables_buttons(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, installed_version="1.0.0", platform_system="Windows")
    view._pending_installer_url = "https://example.com/setup.exe"
    view._install_update_button.show()
    monkeypatch.setattr(
        settings_main_view.QMessageBox,
        "question",
        lambda *a, **k: settings_main_view.QMessageBox.StandardButton.Yes,
    )

    def _raise(url, on_progress=None):
        raise update_checker.UpdateInstallError("installer exploded")

    monkeypatch.setattr(update_checker, "download_and_install_windows_update", _raise)

    view._install_update_button.click()

    qtbot.waitUntil(lambda: "Update install failed" in view._update_status_label.text())
    assert "installer exploded" in view._update_status_label.text()
    assert view._install_update_button.isEnabled()
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


def test_gcp_ssh_key_section_shows_resolved_public_key(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcp_ssh_public_key="ssh-ed25519 AAAA alice@laptop")

    assert "ssh-ed25519 AAAA alice@laptop" in view._gcp_ssh_key_status_label.text()
    assert "default (~/.ssh)" in view._gcp_ssh_key_status_label.text()
    assert view._gcp_ssh_key_button.text() == "Set Key…"
    assert view._gcp_ssh_key_clear_button.isHidden()


def test_gcp_ssh_key_section_shows_configured_override(qtbot, monkeypatch):
    view = _make_view(
        qtbot,
        monkeypatch,
        gcp_ssh_key_override="/home/alice/.ssh/custom_key",
        gcp_ssh_public_key="ssh-ed25519 BBBB alice@laptop",
    )

    assert "/home/alice/.ssh/custom_key" in view._gcp_ssh_key_status_label.text()
    assert view._gcp_ssh_key_button.text() == "Change Key…"
    assert not view._gcp_ssh_key_clear_button.isHidden()


def test_gcp_ssh_key_section_shows_not_found_message(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcp_ssh_public_key=None)

    assert "No SSH public key found" in view._gcp_ssh_key_status_label.text()


def test_set_gcp_ssh_key_saves_and_refreshes(qtbot, monkeypatch):
    import it_toolbox.modules.settings.ui.main_view as settings_main_view

    view = _make_view(qtbot, monkeypatch)
    monkeypatch.setattr(
        settings_main_view.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: ("/home/alice/.ssh/custom_key.pub", ""),
    )
    saved = []
    monkeypatch.setattr(settings, "save_gcp_ssh_key_path", lambda path: saved.append(path))

    view._on_set_gcp_ssh_key_clicked()

    assert saved == ["/home/alice/.ssh/custom_key.pub"]


def test_set_gcp_ssh_key_cancelled_does_not_save(qtbot, monkeypatch):
    import it_toolbox.modules.settings.ui.main_view as settings_main_view

    view = _make_view(qtbot, monkeypatch)
    monkeypatch.setattr(
        settings_main_view.QFileDialog, "getOpenFileName", lambda *a, **k: ("", "")
    )
    saved = []
    monkeypatch.setattr(settings, "save_gcp_ssh_key_path", lambda path: saved.append(path))

    view._on_set_gcp_ssh_key_clicked()

    assert saved == []


def test_clear_gcp_ssh_key_resets_override(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, gcp_ssh_key_override="/home/alice/.ssh/custom_key")
    saved = []
    monkeypatch.setattr(settings, "save_gcp_ssh_key_path", lambda path: saved.append(path))

    view._on_clear_gcp_ssh_key_clicked()

    assert saved == [None]


def test_jumpcloud_section_shows_unconfigured_state(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, jumpcloud_key_configured=False)

    assert "No API key configured" in view._jumpcloud_status_label.text()
    assert view._jumpcloud_key_button.text() == "Set JumpCloud API Key…"


def test_jumpcloud_section_shows_configured_state(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, jumpcloud_key_configured=True)

    assert "API key configured" in view._jumpcloud_status_label.text()
    assert view._jumpcloud_key_button.text() == "Change JumpCloud API Key…"


def test_setting_jumpcloud_key_refreshes_status_on_accept(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, jumpcloud_key_configured=False)

    class _FakeDialog:
        DialogCode = settings_main_view.ApiKeyDialog.DialogCode

        def __init__(self, parent=None):
            pass

        def exec(self):
            # Simulate the key having been saved by the time the dialog
            # closes — a real save updates the file the monkeypatched
            # jumpcloud_api_key_path() below now reports as existing.
            return self.DialogCode.Accepted

    monkeypatch.setattr(settings_main_view, "ApiKeyDialog", _FakeDialog)
    monkeypatch.setattr(settings, "jumpcloud_api_key_path", lambda: _FakePath(True))

    view._on_set_jumpcloud_key_clicked()

    assert "API key configured" in view._jumpcloud_status_label.text()
    assert view._jumpcloud_key_button.text() == "Change JumpCloud API Key…"


def test_dismissing_jumpcloud_key_dialog_leaves_status_unchanged(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, jumpcloud_key_configured=False)

    class _FakeDialog:
        DialogCode = settings_main_view.ApiKeyDialog.DialogCode

        def __init__(self, parent=None):
            pass

        def exec(self):
            return self.DialogCode.Rejected

    monkeypatch.setattr(settings_main_view, "ApiKeyDialog", _FakeDialog)

    view._on_set_jumpcloud_key_clicked()

    assert "No API key configured" in view._jumpcloud_status_label.text()


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


def test_rdp_display_section_defaults_to_match_window_size(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, default_rdp_resolution=None)

    assert view._rdp_resolution_combo.currentText() == "Match window size"


def test_rdp_display_section_preselects_the_saved_resolution(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, default_rdp_resolution=(1920, 1080))

    assert view._rdp_resolution_combo.currentText() == "1920 × 1080"


def test_changing_rdp_resolution_saves_it(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(settings, "save_default_rdp_resolution", lambda value: saved.append(value))

    view._rdp_resolution_combo.setCurrentText("2560 × 1440")

    assert saved == [(2560, 1440)]


def test_changing_rdp_resolution_back_to_match_window_size_clears_it(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, default_rdp_resolution=(1920, 1080))
    saved = []
    monkeypatch.setattr(settings, "save_default_rdp_resolution", lambda value: saved.append(value))

    view._rdp_resolution_combo.setCurrentText("Match window size")

    assert saved == [None]


def test_rdp_keyboard_layout_section_defaults_to_english_us(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, rdp_keyboard_layout=0x0409)

    assert view._rdp_keyboard_layout_combo.currentText() == "English (US)"


def test_rdp_keyboard_layout_section_preselects_the_saved_layout(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, rdp_keyboard_layout=0x040C)

    assert view._rdp_keyboard_layout_combo.currentText() == "French"


def test_changing_rdp_keyboard_layout_saves_it(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(settings, "save_rdp_keyboard_layout", lambda value: saved.append(value))

    view._rdp_keyboard_layout_combo.setCurrentText("German")

    assert saved == [0x0407]


def test_terminal_font_size_section_defaults_to_default(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, terminal_font_size=None)

    assert view._terminal_font_size_combo.currentText() == "Default"


def test_terminal_font_size_section_preselects_the_saved_size(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, terminal_font_size=14)

    assert view._terminal_font_size_combo.currentText() == "14"


def test_changing_terminal_font_size_saves_it(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(settings, "save_terminal_font_size", lambda value: saved.append(value))

    view._terminal_font_size_combo.setCurrentText("18")

    assert saved == [18]


def test_changing_terminal_font_size_back_to_default_clears_it(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, terminal_font_size=18)
    saved = []
    monkeypatch.setattr(settings, "save_terminal_font_size", lambda value: saved.append(value))

    view._terminal_font_size_combo.setCurrentText("Default")

    assert saved == [None]


def test_double_click_action_section_defaults_to_ask_each_time(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, default_double_click_action="ask")

    assert view._double_click_action_combo.currentText() == "Ask each time"


def test_double_click_action_section_preselects_the_saved_action(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch, default_double_click_action="rdp")

    assert view._double_click_action_combo.currentText() == "RDP"


def test_changing_double_click_action_saves_it(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(
        settings, "save_default_double_click_action", lambda value: saved.append(value)
    )

    view._double_click_action_combo.setCurrentText("SSH")

    assert saved == ["ssh"]


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

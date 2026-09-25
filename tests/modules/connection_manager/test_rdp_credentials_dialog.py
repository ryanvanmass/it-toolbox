from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton

from it_toolbox.modules.connection_manager.ui.rdp_credentials_dialog import RdpCredentialsDialog


def _make_dialog(qtbot, **kwargs):
    dialog = RdpCredentialsDialog("vm-1", **kwargs)
    qtbot.addWidget(dialog)
    return dialog


def _ok_button(dialog):
    return dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)


def _clear_buttons(dialog):
    return [b for b in dialog.findChildren(QPushButton) if b.text() == "Clear Saved Credentials"]


def test_dialog_is_titled_with_the_vm_and_prefilled_with_the_username(qtbot):
    dialog = _make_dialog(qtbot, username="alice")

    assert "vm-1" in dialog.windowTitle()
    assert dialog.username() == "alice"
    assert dialog.password() == ""
    assert dialog.cleared() is False


def test_username_is_trimmed_but_the_password_is_left_exactly_as_typed(qtbot):
    dialog = _make_dialog(qtbot)

    dialog._username_edit.setText("  alice  ")
    dialog._password_edit.setText(" pa ss ")

    assert dialog.username() == "alice"
    assert dialog.password() == " pa ss "


def test_ok_needs_a_username(qtbot):
    dialog = _make_dialog(qtbot)
    assert not _ok_button(dialog).isEnabled()

    dialog._username_edit.setText("   ")
    assert not _ok_button(dialog).isEnabled()

    dialog._username_edit.setText("alice")
    assert _ok_button(dialog).isEnabled()


def test_password_placeholder_says_what_a_blank_password_means(qtbot):
    fresh = _make_dialog(qtbot, username="alice")
    saved = _make_dialog(qtbot, username="alice", has_saved=True, has_saved_password=True)

    assert "prompted" in fresh._password_edit.placeholderText()
    assert "keep the saved password" in saved._password_edit.placeholderText()


def test_password_is_masked(qtbot):
    dialog = _make_dialog(qtbot)

    assert dialog._password_edit.echoMode() == dialog._password_edit.EchoMode.Password


def test_there_is_no_clear_button_when_nothing_is_saved(qtbot):
    assert _clear_buttons(_make_dialog(qtbot, username="alice")) == []


def test_clear_button_accepts_the_dialog_and_reports_cleared(qtbot):
    dialog = _make_dialog(qtbot, username="alice", has_saved=True)
    (clear,) = _clear_buttons(dialog)

    clear.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.cleared() is True


def test_clear_works_even_with_the_username_blanked(qtbot):
    # Clearing doesn't need a valid username; only saving does.
    dialog = _make_dialog(qtbot, username="alice", has_saved=True)
    dialog._username_edit.setText("")
    (clear,) = _clear_buttons(dialog)

    clear.click()

    assert dialog.cleared() is True


def test_cancel_rejects_without_clearing(qtbot):
    dialog = _make_dialog(qtbot, username="alice", has_saved=True)

    dialog._buttons.button(QDialogButtonBox.StandardButton.Cancel).click()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.cleared() is False

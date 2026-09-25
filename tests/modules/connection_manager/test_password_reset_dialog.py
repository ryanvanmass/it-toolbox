from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QPushButton

from it_toolbox.modules.connection_manager.ui.password_reset_dialog import PasswordResetDialog

PASSWORD = "Sup3r-s3cret!"


def _make_dialog(qtbot, password=PASSWORD, note="", username="alice"):
    dialog = PasswordResetDialog("vm-1", username, password, note)
    qtbot.addWidget(dialog)
    return dialog


def _all_visible_text(dialog):
    """Every string the dialog could put in front of a user: window title,
    label text, button text and tooltips."""
    texts = [dialog.windowTitle()]
    for label in dialog.findChildren(QLabel):
        texts.append(label.text())
        texts.append(label.toolTip())
    for button in dialog.findChildren(QPushButton):
        texts.append(button.text())
        texts.append(button.toolTip())
    return texts


def _copy_button(dialog):
    (button,) = [b for b in dialog.findChildren(QPushButton) if b.text().startswith("Cop")]
    return button


def test_the_password_is_not_displayed_anywhere(qtbot):
    dialog = _make_dialog(qtbot)

    assert not any(PASSWORD in text for text in _all_visible_text(dialog))
    # ...nor any fragment of it long enough to be a giveaway.
    assert not any("s3cr3t" in text for text in _all_visible_text(dialog))


def test_the_mask_does_not_reveal_the_password_length(qtbot):
    short = _make_dialog(qtbot, password="ab")
    long = _make_dialog(qtbot, password="a-very-long-generated-password-1234567890")

    masks = lambda d: [t for t in _all_visible_text(d) if t and set(t) == {"•"}]  # noqa: E731
    assert masks(short) and masks(short) == masks(long)


def test_the_username_and_instance_are_shown(qtbot):
    dialog = _make_dialog(qtbot, username="alice")

    texts = _all_visible_text(dialog)
    assert "alice" in texts
    assert any("vm-1" in text for text in texts)


def test_copy_button_puts_the_exact_password_on_the_clipboard(qtbot):
    QApplication.clipboard().setText("something else")
    dialog = _make_dialog(qtbot)

    _copy_button(dialog).click()

    assert QApplication.clipboard().text() == PASSWORD


def test_copy_button_copies_a_password_with_spaces_and_symbols_unchanged(qtbot):
    tricky = '  p@ss w0rd "quoted" \\ é  '
    dialog = _make_dialog(qtbot, password=tricky)

    _copy_button(dialog).click()

    assert QApplication.clipboard().text() == tricky


def test_copy_button_confirms_then_reverts(qtbot, monkeypatch):
    monkeypatch.setattr(PasswordResetDialog, "COPIED_FEEDBACK_MS", 50)
    dialog = _make_dialog(qtbot)
    button = _copy_button(dialog)
    assert button.text() == "Copy Password"

    button.click()

    assert "Copied" in button.text()
    qtbot.waitUntil(lambda: button.text() == "Copy Password", timeout=2000)


def test_the_note_is_shown_when_given_and_absent_otherwise(qtbot):
    with_note = _make_dialog(qtbot, note="Saved as this VM's RDP login.")
    without_note = _make_dialog(qtbot, note="")

    assert "Saved as this VM's RDP login." in _all_visible_text(with_note)
    assert len([t for t in _all_visible_text(with_note) if t]) == (
        len([t for t in _all_visible_text(without_note) if t]) + 1
    )


def test_ok_closes_the_dialog(qtbot):
    dialog = _make_dialog(qtbot)

    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()

    assert dialog.result() == QDialog.DialogCode.Accepted

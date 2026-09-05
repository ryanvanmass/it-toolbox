from PySide6.QtWidgets import QDialog

from it_toolbox.modules.identity_management.ui.api_key_dialog import ApiKeyDialog


class _FakePath:
    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def is_file(self) -> bool:
        return self._exists


def _make_dialog(qtbot, monkeypatch, configured=False):
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.settings.jumpcloud_api_key_path",
        lambda: _FakePath(exists=configured),
    )
    dialog = ApiKeyDialog()
    qtbot.addWidget(dialog)
    return dialog


def test_test_connection_success_updates_status(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.jumpcloud_client.test_connection",
        lambda key: None,
    )
    dialog._key_edit.setText("jca_testkey")

    dialog._on_test_clicked()

    qtbot.waitUntil(lambda: dialog._test_status.text() == "Connection OK.", timeout=2000)


def test_test_connection_failure_shows_error(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    def fake_test(key):
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.jumpcloud_client.test_connection",
        fake_test,
    )
    dialog._key_edit.setText("jca_badkey")

    dialog._on_test_clicked()

    qtbot.waitUntil(lambda: "Failed" in dialog._test_status.text(), timeout=2000)


def test_test_connection_with_empty_key_does_not_call_the_api(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.jumpcloud_client.test_connection",
        lambda key: calls.append(key),
    )

    dialog._on_test_clicked()

    assert calls == []


def test_save_calls_settings_save_and_accepts(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    saved = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.settings.save_jumpcloud_api_key",
        lambda key: saved.append(key),
    )
    dialog._key_edit.setText("jca_testkey")

    dialog._on_save_clicked()

    assert saved == ["jca_testkey"]
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_save_blank_clears_the_key(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch, configured=True)
    saved = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.settings.save_jumpcloud_api_key",
        lambda key: saved.append(key),
    )

    dialog._on_save_clicked()

    assert saved == [None]


def test_save_shows_warning_on_decryption_error(qtbot, monkeypatch):
    from it_toolbox.core import settings

    dialog = _make_dialog(qtbot, monkeypatch)

    def fake_save(key):
        raise settings.SecretDecryptionError("no SSH key found")

    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.settings.save_jumpcloud_api_key",
        fake_save,
    )
    warned = []
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.api_key_dialog.QMessageBox.warning",
        lambda *args, **kwargs: warned.append(args),
    )
    dialog._key_edit.setText("jca_testkey")

    dialog._on_save_clicked()

    assert len(warned) == 1
    assert dialog.result() != QDialog.DialogCode.Accepted

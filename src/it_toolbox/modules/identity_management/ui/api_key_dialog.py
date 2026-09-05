from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, settings
from it_toolbox.modules.identity_management import jumpcloud_client


class ApiKeyDialog(QDialog):
    """Lets the user paste in (or replace) the JumpCloud API key.

    Saving only needs the resolved SSH *public* key (settings.
    save_jumpcloud_api_key encrypts to it) — no passphrase prompt happens
    here even if the matching private key is passphrase-protected, since
    that's only needed later, when actually decrypting the key to use it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set JumpCloud API Key")
        self.resize(420, 180)

        configured = settings.jumpcloud_api_key_path().is_file()
        status = QLabel(
            "A JumpCloud API key is already configured — paste a new one to replace it, "
            "or leave this blank and save to clear it."
            if configured
            else "Paste your JumpCloud API key (Admin Portal → your account initials → "
            "My API Key)."
        )
        status.setWordWrap(True)

        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("jca_…")

        self._test_button = QPushButton("Test Connection")
        self._test_button.clicked.connect(self._on_test_clicked)
        self._test_status = QLabel("")
        self._test_status.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self._save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._on_save_clicked)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(status)
        layout.addWidget(self._key_edit)
        layout.addWidget(self._test_button)
        layout.addWidget(self._test_status)
        layout.addStretch()
        layout.addWidget(buttons)

    def _on_test_clicked(self) -> None:
        api_key = self._key_edit.text().strip()
        if not api_key:
            self._test_status.setText("Enter a key first.")
            return
        self._test_button.setEnabled(False)
        self._test_status.setText("Testing…")
        async_utils.run_in_background(
            lambda: jumpcloud_client.test_connection(api_key),
            on_result=lambda _: self._on_test_done(True),
            on_error=lambda error: self._on_test_done(False, error),
        )

    def _on_test_done(self, ok: bool, error: Exception | None = None) -> None:
        try:
            self._test_button.setEnabled(True)
            self._test_status.setText("Connection OK." if ok else f"Failed: {error}")
        except RuntimeError:
            pass  # dialog closed while the test call was in flight

    def _on_save_clicked(self) -> None:
        try:
            settings.save_jumpcloud_api_key(self._key_edit.text().strip() or None)
        except settings.SecretDecryptionError as exc:
            QMessageBox.warning(self, "Couldn't save API key", str(exc))
            return
        self.accept()

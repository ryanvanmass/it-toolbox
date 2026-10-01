"""Prompts for FTP/SFTP connect-time credentials not already known —
mirrors the shape of main_view.py's RDP password prompt, but with the
extra fields SFTP's real-world auth methods need (password, private
key, or neither — paramiko then falls back to the SSH agent/default
key). Plain FTP only ever shows a password field.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FtpCredentialsDialog(QDialog):
    def __init__(
        self,
        kind: str,
        display_name: str,
        default_username: str = "",
        show_remember: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Connect to {display_name}")
        self._kind = kind

        self._username_edit = QLineEdit(default_username)
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("Username:", self._username_edit)
        form.addRow("Password:", self._password_edit)

        self._key_path_edit: QLineEdit | None = None
        self._key_passphrase_edit: QLineEdit | None = None
        if kind == "sftp":
            self._key_path_edit = QLineEdit()
            browse_button = QPushButton("Browse…")
            browse_button.clicked.connect(self._on_browse_key)
            key_row = QWidget()
            key_row_layout = QHBoxLayout(key_row)
            key_row_layout.setContentsMargins(0, 0, 0, 0)
            key_row_layout.addWidget(self._key_path_edit)
            key_row_layout.addWidget(browse_button)
            form.addRow("Private key:", key_row)

            self._key_passphrase_edit = QLineEdit()
            self._key_passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Key passphrase:", self._key_passphrase_edit)

            hint = QLabel(
                "Leave password and private key blank to authenticate via your SSH "
                "agent or default key (~/.ssh/id_ed25519, ~/.ssh/id_rsa)."
            )
            hint.setWordWrap(True)
            form.addRow("", hint)

        self._remember_checkbox = QCheckBox("Remember password for this connection")
        if show_remember:
            form.addRow("", self._remember_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Private Key")
        if path:
            self._key_path_edit.setText(path)

    def username(self) -> str:
        return self._username_edit.text().strip()

    def password(self) -> str:
        return self._password_edit.text()

    def key_path(self) -> str | None:
        if self._key_path_edit is None:
            return None
        return self._key_path_edit.text().strip() or None

    def key_passphrase(self) -> str | None:
        if self._key_passphrase_edit is None:
            return None
        return self._key_passphrase_edit.text() or None

    def remember_password(self) -> bool:
        return self._remember_checkbox.isChecked()

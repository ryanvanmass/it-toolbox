"""Set (or clear) the RDP login remembered for one GCP VM — what "Connect
via RDP" signs in with instead of prompting. "Set Password…" fills the same
store automatically after a successful reset; this dialog is for entering a
login by hand or removing it.
"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class RdpCredentialsDialog(QDialog):
    def __init__(
        self,
        instance_name: str,
        username: str = "",
        has_saved: bool = False,
        has_saved_password: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"RDP Credentials — {instance_name}")
        self._cleared = False

        self._username_edit = QLineEdit(username)
        self._username_edit.setPlaceholderText("e.g. Administrator or DOMAIN\\user")
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText(
            "Leave blank to keep the saved password"
            if has_saved_password
            else "Leave blank to be prompted each time"
        )

        form = QFormLayout()
        form.addRow("Username:", self._username_edit)
        form.addRow("Password:", self._password_edit)

        hint = QLabel(
            "Used by Connect via RDP for this VM only. The password is stored encrypted "
            "with your SSH key, never as plain text. "
            + (
                "Changing the username without entering a password discards the saved "
                "password, since it belonged to the old username."
                if has_saved_password
                else ""
            )
        )
        hint.setWordWrap(True)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        if has_saved:
            clear_button = QPushButton("Clear Saved Credentials")
            clear_button.clicked.connect(self._on_clear_clicked)
            self._buttons.addButton(clear_button, QDialogButtonBox.ButtonRole.DestructiveRole)

        # A login needs a username; without one there is nothing to save.
        self._username_edit.textChanged.connect(self._update_ok_enabled)
        self._update_ok_enabled()

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self._buttons)

    def _update_ok_enabled(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self._username_edit.text().strip()))

    def _on_clear_clicked(self) -> None:
        self._cleared = True
        self.accept()

    def username(self) -> str:
        return self._username_edit.text().strip()

    def password(self) -> str:
        return self._password_edit.text()

    def cleared(self) -> bool:
        """True when the user chose Clear Saved Credentials instead of OK."""
        return self._cleared

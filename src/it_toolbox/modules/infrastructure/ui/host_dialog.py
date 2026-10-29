"""Add / edit an Infrastructure host, shared by every product.

Certificate handling: with "Verify TLS certificate" off (the default --
all three appliances ship self-signed certificates), the dialog fetches
the certificate's SHA-256 fingerprint on save and asks the user to trust
it, unless it is the one already pinned. A host can never be saved with
verification off and nothing pinned.

The secret field is blank when editing; blank means "keep the stored one".
The caller encrypts and saves -- this dialog never touches settings.
"""

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, pinned_tls
from it_toolbox.core.infrastructure_hosts import InfrastructureHost, normalize_url
from it_toolbox.modules.infrastructure.product import InfrastructureProduct


class HostDialog(QDialog):
    def __init__(
        self,
        product: InfrastructureProduct,
        host: InfrastructureHost | None = None,
        stored_secret=None,
        parent: QWidget | None = None,
    ) -> None:
        """`stored_secret` is a zero-argument callable returning the saved
        secret (decrypting it), used only when Test connection runs with
        the secret field left blank."""
        super().__init__(parent)
        self._product = product
        self._original = host
        self._stored_secret = stored_secret
        self._fingerprint = host.fingerprint if host else None
        self.setWindowTitle(f"{'Edit' if host else 'Add'} {product.display_name} Host")
        self.setMinimumWidth(460)

        self._name = QLineEdit(host.name if host else "")
        self._url = QLineEdit(host.url if host else "")
        self._url.setPlaceholderText(product.url_placeholder)
        self._token_id = QLineEdit(host.token_id if host else "")
        self._token_id.setPlaceholderText(product.token_id_placeholder)
        self._secret = QLineEdit()
        self._secret.setEchoMode(QLineEdit.EchoMode.Password)
        if host is not None and host.secret_encrypted is not None:
            self._secret.setPlaceholderText("Leave blank to keep the stored secret")
        self._ssh_username = QLineEdit(host.ssh_username if host else "root")
        self._verify = QCheckBox("Verify TLS certificate (only for a CA-signed certificate)")
        self._verify.setChecked(host.verify_ssl if host else False)

        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("URL:", self._url)
        if product.token_id_label is not None:
            form.addRow(product.token_id_label, self._token_id)
        form.addRow(product.secret_label, self._secret)
        form.addRow("SSH user:", self._ssh_username)
        form.addRow("", self._verify)

        help_label = QLabel(product.token_help)
        help_label.setWordWrap(True)
        help_label.setVisible(bool(product.token_help))

        self._test_button = QPushButton("Test Connection")
        self._test_button.clicked.connect(self._on_test_clicked)
        self._result = QLabel()
        self._result.setWordWrap(True)
        self._result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.addButton(self._test_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(help_label)
        layout.addWidget(self._result)
        layout.addWidget(buttons)

    # -- Values ----------------------------------------------------------------

    def secret(self) -> str | None:
        """The newly typed secret, or None to keep the stored one."""
        return self._secret.text().strip() or None

    def host(self) -> InfrastructureHost:
        """The edited host. secret_encrypted is carried over unchanged;
        the caller replaces it when secret() is set."""
        url = normalize_url(self._url.text(), self._product.default_port)
        return InfrastructureHost(
            name=self._name.text().strip() or pinned_tls.host_port(url)[0],
            url=url,
            token_id=self._token_id.text().strip(),
            secret_encrypted=self._original.secret_encrypted if self._original else None,
            verify_ssl=self._verify.isChecked(),
            fingerprint=None if self._verify.isChecked() else self._fingerprint,
            ssh_username=self._ssh_username.text().strip() or "root",
        )

    # -- Certificate -------------------------------------------------------------

    def _ensure_trusted(self, url: str) -> bool:
        """Fetches the certificate and asks the user to trust it, unless
        it matches the pinned one. False if fetching failed or the user
        declined."""
        if self._verify.isChecked():
            return True
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fingerprint = pinned_tls.fetch_fingerprint(url, timeout=8)
        except OSError as error:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.warning(self, self.windowTitle(), f"Couldn't reach {url}:\n{error}")
            return False
        QGuiApplication.restoreOverrideCursor()
        if self._fingerprint and pinned_tls.normalize_fingerprint(
            self._fingerprint
        ) == pinned_tls.normalize_fingerprint(fingerprint):
            return True
        changed = bool(self._fingerprint)
        text = (
            f"The certificate for {url} has changed.\n\nPinned:\n{self._fingerprint}\n\nNow:\n{fingerprint}"
            if changed
            else f"{url} presents a certificate that isn't signed by a trusted CA.\n\nSHA-256 fingerprint:\n{fingerprint}"
        )
        answer = QMessageBox.question(
            self,
            "Trust Certificate",
            text + "\n\nCompare it with the fingerprint shown in the host's own web UI. Trust it?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self._fingerprint = fingerprint
        return True

    # -- Buttons ---------------------------------------------------------------

    def _validate(self) -> str | None:
        if not normalize_url(self._url.text(), self._product.default_port):
            return "Enter the host's URL."
        if self._product.token_id_label is not None and not self._token_id.text().strip():
            return f"Enter the {self._product.token_id_label.rstrip(':').lower()}."
        if self._original is None and self.secret() is None:
            return f"Enter the {self._product.secret_label.rstrip(':').lower()}."
        return None

    def _on_save(self) -> None:
        problem = self._validate()
        if problem:
            QMessageBox.warning(self, self.windowTitle(), problem)
            return
        if not self._ensure_trusted(self.host().url):
            return
        self.accept()

    def _on_test_clicked(self) -> None:
        problem = self._validate()
        if problem:
            self._result.setText(problem)
            return
        host = self.host()
        if not self._ensure_trusted(host.url):
            return
        host = self.host()  # now carries the trusted fingerprint
        secret = self.secret()
        if secret is None and self._stored_secret is not None:
            secret = self._stored_secret()
        if not secret:
            self._result.setText("No secret to test with.")
            return
        self._test_button.setEnabled(False)
        self._result.setText("Testing…")

        def done(summary: str) -> None:
            if not shiboken6.isValid(self):
                return
            self._test_button.setEnabled(True)
            self._result.setText(f"Connected: {summary}")

        def failed(error: Exception) -> None:
            if not shiboken6.isValid(self):
                return
            self._test_button.setEnabled(True)
            self._result.setText(f"Failed: {error}")

        async_utils.run_in_background(
            lambda: self._product.test_connection(host, secret), on_result=done, on_error=failed
        )

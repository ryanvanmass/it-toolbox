"""One FTP Server Test tab (General Tools): the SFTP Server Test tab
(widgets/sftp_server_test_widget.py) with an FTP form -- no private key,
a choice of plain FTP or explicit FTPS instead -- running
core/ftp_stress_test.py's FtpStressTest.
"""

from PySide6.QtWidgets import QComboBox, QFormLayout

from it_toolbox.core import settings
from it_toolbox.core.ftp_stress_test import FtpStressTest, FtpStressTestConfig
from it_toolbox.widgets.sftp_server_test_widget import SftpServerTestWidget

#: Saved as the "security" value; the labels are what the combo shows.
SECURITY_OPTIONS = {
    "none": "None (plain FTP)",
    "explicit_tls": "Explicit FTPS (AUTH TLS)",
}


class FtpServerTestWidget(SftpServerTestWidget):
    tool_name = "FTP Server Test"
    protocol = "FTP"
    default_port = 21
    host_placeholder = "ftp.example.com"
    folder_prefix = FtpStressTest.folder_prefix

    def _add_credential_rows(self, form: QFormLayout) -> None:
        self._password_edit.setPlaceholderText("Not saved with the test")
        self._security_combo = QComboBox()
        for key, label in SECURITY_OPTIONS.items():
            self._security_combo.addItem(label, key)
        self._security_combo.setToolTip(
            "Explicit FTPS upgrades the connection with AUTH TLS and encrypts the file transfers too. "
            "The server's certificate isn't verified, the same as the FTP file browser."
        )
        form.addRow("Encryption:", self._security_combo)

    def _credential_values(self) -> dict:
        return {"security": self._security_combo.currentData()}

    def _apply_credential_values(self, values: dict) -> None:
        index = self._security_combo.findData(values.get("security"))
        if index != -1:
            self._security_combo.setCurrentIndex(index)

    def _load_defaults(self) -> None:
        self.apply_values(settings.load_ftp_server_test_defaults())

    def _save_defaults(self) -> None:
        settings.save_ftp_server_test_defaults(self.form_values())

    def _load_configs(self) -> dict[str, dict]:
        return settings.load_ftp_server_test_configs()

    def _save_configs(self, configs: dict[str, dict]) -> None:
        settings.save_ftp_server_test_configs(configs)

    def config(self) -> FtpStressTestConfig:
        return FtpStressTestConfig(
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            username=self._username_edit.text().strip(),
            password=self._password_edit.text() or None,
            use_tls=self._security_combo.currentData() == "explicit_tls",
            workers=self._workers_spin.value(),
            min_file_size=self._min_size.bytes(),
            max_file_size=self._max_size.bytes(),
            remote_dir=self._remote_dir_edit.text().strip(),
            cleanup=self._cleanup_check.isChecked(),
        )

    def _make_test(self, config: FtpStressTestConfig) -> FtpStressTest:
        return FtpStressTest(config)

from it_toolbox.core import settings
from it_toolbox.modules.general_tools.ui.sftp_test_tool import SftpTestTool
from it_toolbox.widgets.ftp_server_test_widget import FtpServerTestWidget


class FtpTestTool(SftpTestTool):
    """The FTP Server Test entry under General Tools: SftpTestTool's
    New Test… / saved tests sidebar, opening FTP test tabs."""

    name = "FTP Server Test"
    widget_class = FtpServerTestWidget

    @staticmethod
    def _load_configs() -> dict[str, dict]:
        return settings.load_ftp_server_test_configs()

    @staticmethod
    def _save_configs(configs: dict[str, dict]) -> None:
        settings.save_ftp_server_test_configs(configs)

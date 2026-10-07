from it_toolbox.core import settings
from it_toolbox.modules.general_tools.ui.recent_files_tool import (  # noqa: F401 - re-exported
    IS_OPEN_ITEM_ROLE,
    PATH_ROLE,
    RecentFilesTool,
)
from it_toolbox.widgets.mbox_browser_widget import MboxBrowserWidget


class MboxTool(RecentFilesTool):
    """The Mbox Browser: each opened mbox archive gets a browse tab."""

    name = "Mbox Browser"
    file_kind = "Mbox"
    file_filter = "Mbox files (*.mbox *.mbx *.mbs);;All files (*)"

    @staticmethod
    def load_recent() -> list[str]:
        return settings.load_recent_mbox_files()

    @staticmethod
    def save_recent(files: list[str]) -> None:
        settings.save_recent_mbox_files(files)

    def create_widget(self, path: str) -> MboxBrowserWidget:
        return MboxBrowserWidget(path)

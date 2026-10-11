from it_toolbox.core import settings
from it_toolbox.modules.general_tools.ui.recent_files_tool import RecentFilesTool
from it_toolbox.widgets.eml_viewer_widget import EmlViewerWidget


class EmlTool(RecentFilesTool):
    """The EML Viewer: each opened .eml message gets a tab showing its
    headers, body and attachments."""

    name = "EML Viewer"
    file_kind = "EML"
    file_filter = "Email messages (*.eml);;All files (*)"

    @staticmethod
    def load_recent() -> list[str]:
        return settings.load_recent_eml_files()

    @staticmethod
    def save_recent(files: list[str]) -> None:
        settings.save_recent_eml_files(files)

    def create_widget(self, path: str) -> EmlViewerWidget:
        return EmlViewerWidget(path)

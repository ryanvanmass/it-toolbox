from PySide6.QtWidgets import QTabWidget

from it_toolbox.modules import ToolModule
from it_toolbox.modules.cloud_storage.module import CloudStorageModule
from it_toolbox.modules.connection_manager.module import ConnectionManagerModule
from it_toolbox.modules.identity_management.module import IdentityManagementModule
from it_toolbox.modules.settings.module import SettingsModule
from it_toolbox.modules.shell_launcher.module import ShellLauncherModule


def load_modules(tabs: QTabWidget) -> list[ToolModule]:
    """Static list of enabled tool modules, in sidebar order.

    Deliberately not a dynamic plugin/entry-points system — module count
    and provenance don't justify one yet.

    `tabs` is the single session-tab pane shared by every module (see
    MainWindow) — passed through so each module's view can add its own
    tabs (terminals, RDP/SPICE sessions, etc.) into that one shared pane
    instead of each keeping a private tab widget.
    """
    return [
        ConnectionManagerModule(tabs),
        ShellLauncherModule(tabs),
        CloudStorageModule(tabs),
        IdentityManagementModule(),
        SettingsModule(),
    ]

from collections.abc import Callable

from PySide6.QtWidgets import QTabWidget

from it_toolbox.core import settings
from it_toolbox.modules import ToolModule
from it_toolbox.modules.cloud_storage.module import CloudStorageModule
from it_toolbox.modules.connection_manager.module import ConnectionManagerModule
from it_toolbox.modules.identity_management.module import IdentityManagementModule
from it_toolbox.modules.settings.module import SettingsModule
from it_toolbox.modules.shell_launcher.module import ShellLauncherModule

#: Modules the user can switch off in Settings > Modules, in sidebar order.
#: Settings itself is deliberately absent -- it's always loaded (last),
#: since it's the only way to switch anything back on.
OPTIONAL_MODULES: list[type[ToolModule]] = [
    ConnectionManagerModule,
    ShellLauncherModule,
    CloudStorageModule,
    IdentityManagementModule,
]


def load_modules(tabs: QTabWidget) -> list[ToolModule]:
    """Static list of enabled tool modules, in sidebar order.

    Deliberately not a dynamic plugin/entry-points system — module count
    and provenance don't justify one yet.

    `tabs` is the single session-tab pane shared by every module (see
    MainWindow) — passed through so each module's view can add its own
    tabs (terminals, RDP/SPICE sessions, etc.) into that one shared pane
    instead of each keeping a private tab widget.

    Modules switched off in Settings > Modules are skipped outright (never
    constructed), so they cost nothing at startup -- toggling one takes
    effect on the next launch.
    """
    disabled = settings.load_disabled_modules()
    candidates: list[tuple[type[ToolModule], Callable[[], ToolModule]]] = [
        (ConnectionManagerModule, lambda: ConnectionManagerModule(tabs)),
        (ShellLauncherModule, lambda: ShellLauncherModule(tabs)),
        (CloudStorageModule, lambda: CloudStorageModule(tabs)),
        (IdentityManagementModule, IdentityManagementModule),
    ]
    modules = [create() for module_class, create in candidates if module_class.id not in disabled]
    modules.append(SettingsModule())
    return modules

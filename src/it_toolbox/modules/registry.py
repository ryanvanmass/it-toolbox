from it_toolbox.modules import ToolModule
from it_toolbox.modules.connection_manager.module import ConnectionManagerModule
from it_toolbox.modules.shell_launcher.module import ShellLauncherModule


def load_modules() -> list[ToolModule]:
    """Static list of enabled tool modules, in sidebar order.

    Deliberately not a dynamic plugin/entry-points system — module count
    and provenance don't justify one yet.
    """
    return [
        ConnectionManagerModule(),
        ShellLauncherModule(),
    ]

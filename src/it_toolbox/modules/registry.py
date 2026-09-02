from it_toolbox.modules import ToolModule
from it_toolbox.modules.connection_manager.module import ConnectionManagerModule


def load_modules() -> list[ToolModule]:
    """Static list of enabled tool modules, in sidebar order.

    Deliberately not a dynamic plugin/entry-points system — there's one
    module today. Revisit if/when module count and provenance justify it.
    """
    return [
        ConnectionManagerModule(),
    ]

import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from it_toolbox.app import MainWindow


def main() -> int:
    # Off by default -- set IT_TOOLBOX_LOG_LEVEL=DEBUG (or INFO/WARNING/etc.)
    # before launching to see logging.debug()/info() calls scattered through
    # the app (e.g. widgets/rdp_widget.py's per-keystroke input logging) on
    # stderr. Only takes effect when launched from a terminal -- a
    # double-clicked Start Menu/desktop entry has nowhere for stderr to go.
    log_level = os.environ.get("IT_TOOLBOX_LOG_LEVEL")
    if log_level:
        # force=True: basicConfig() is a silent no-op if the root logger
        # already has a handler -- which it can, e.g. if some already-
        # imported dependency installed one of its own before this runs.
        # Without this, "nothing at all logs, not even a startup line"
        # would be indistinguishable from the env var itself never being
        # read (a launcher/shell issue) -- the print right after this
        # settles which one it is.
        logging.basicConfig(
            level=log_level.upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            force=True,
        )
        logging.getLogger(__name__).info("Logging configured at level %s", log_level.upper())

    app = QApplication(sys.argv)
    app.setApplicationName("IT Toolbox")
    app.setOrganizationName("IT Toolbox")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

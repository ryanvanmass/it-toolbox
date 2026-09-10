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
        logging.basicConfig(
            level=log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )

    app = QApplication(sys.argv)
    app.setApplicationName("IT Toolbox")
    app.setOrganizationName("IT Toolbox")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

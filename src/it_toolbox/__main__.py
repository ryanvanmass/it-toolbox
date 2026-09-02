import sys

from PySide6.QtWidgets import QApplication

from it_toolbox.app import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("IT Toolbox")
    app.setOrganizationName("IT Toolbox")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

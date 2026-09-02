from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMainWindow, QSplitter, QStackedWidget

from it_toolbox.modules.registry import load_modules


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("IT Toolbox")
        self.resize(1000, 650)

        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(200)
        self._stack = QStackedWidget()

        for module in load_modules():
            item = QListWidgetItem(module.icon, module.display_name)
            self._sidebar.addItem(item)
            self._stack.addWidget(module.create_widget())

        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        if self._sidebar.count():
            self._sidebar.setCurrentRow(0)

        splitter = QSplitter()
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules.registry import load_modules


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("IT Toolbox")
        self.resize(1000, 650)

        self._module_list = QListWidget()
        # Each module's own navigation content (e.g. a resource browser
        # tree) is nested directly beneath its entry, switching in sync
        # with which module is selected above.
        self._sidebar_extras = QStackedWidget()
        self._stack = QStackedWidget()

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(self._module_list)
        sidebar_layout.addWidget(self._sidebar_extras, 1)

        for module in load_modules():
            item = QListWidgetItem(module.icon, module.display_name)
            self._module_list.addItem(item)
            self._stack.addWidget(module.create_widget())
            self._sidebar_extras.addWidget(module.create_sidebar_widget() or QWidget())

        self._module_list.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._module_list.currentRowChanged.connect(self._sidebar_extras.setCurrentIndex)
        if self._module_list.count():
            self._module_list.setCurrentRow(0)

        splitter = QSplitter()
        splitter.addWidget(sidebar)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 750])

        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules import ToolModule
from it_toolbox.modules.registry import load_modules


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("IT Toolbox")
        self.resize(1000, 650)

        self._modules: list[ToolModule] = load_modules()

        self._module_list = QListWidget()
        self._module_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._module_list.customContextMenuRequested.connect(self._on_module_context_menu)
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

        for module in self._modules:
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

    def _on_module_context_menu(self, pos) -> None:
        item = self._module_list.itemAt(pos)
        if item is None:
            return
        module = self._modules[self._module_list.row(item)]
        menu = module.build_context_menu(self)
        if menu is not None:
            menu.exec(self._module_list.viewport().mapToGlobal(pos))

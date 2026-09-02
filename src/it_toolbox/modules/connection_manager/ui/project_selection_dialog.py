from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.modules.connection_manager.models import GcpProject

PROJECT_ID_ROLE = Qt.ItemDataRole.UserRole


class ProjectSelectionDialog(QDialog):
    """Lets the user pick a subset of their GCP projects to show in the tree.

    Meant for accounts with a large number of projects (org accounts can
    easily have hundreds) — browsing/expanding all of them is both
    impractical and, if any one project is slow to respond, means every
    expansion click risks eating a request timeout.
    """

    def __init__(
        self, projects: list[GcpProject], selected_ids: set[str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Projects")
        self.resize(420, 520)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter projects…")
        self._filter_edit.textChanged.connect(self._apply_filter)

        self._list = QListWidget()
        for project in sorted(projects, key=lambda p: (p.display_name or p.project_id).lower()):
            label = f"{project.display_name or project.project_id} ({project.project_id})"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if project.project_id in selected_ids
                else Qt.CheckState.Unchecked
            )
            item.setData(PROJECT_ID_ROLE, project.project_id)
            self._list.addItem(item)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{len(projects)} project(s) available — check the ones to show:"))
        layout.addWidget(self._filter_edit)
        layout.addWidget(self._list)
        layout.addWidget(buttons)

    def _apply_filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(text not in item.text().lower())

    def selected_project_ids(self) -> set[str]:
        ids = set()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                ids.add(item.data(PROJECT_ID_ROLE))
        return ids

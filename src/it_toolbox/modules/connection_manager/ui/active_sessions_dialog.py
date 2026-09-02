from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SESSION_ID_ROLE = Qt.ItemDataRole.UserRole


class ActiveSessionsDialog(QDialog):
    """A standalone, non-modal window listing active tunnel/RDP/SSH sessions.

    Owns only the presentation — ConnectionManagerView still owns session
    state and lifecycle (including tearing everything down on app quit);
    this just displays it and reports back what the user asked to disconnect.
    """

    disconnect_requested = Signal(int)  # session_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Active Sessions")
        self.resize(420, 300)

        self._list = QListWidget()
        self._disconnect_button = QPushButton("Disconnect")
        self._disconnect_button.setEnabled(False)
        self._disconnect_button.clicked.connect(self._on_disconnect_clicked)
        self._list.itemSelectionChanged.connect(
            lambda: self._disconnect_button.setEnabled(bool(self._list.selectedItems()))
        )

        buttons_bar = QHBoxLayout()
        buttons_bar.addStretch()
        buttons_bar.addWidget(self._disconnect_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons_bar)

    def add_session(self, session_id: int, label: str) -> None:
        item = QListWidgetItem(label)
        item.setData(SESSION_ID_ROLE, session_id)
        self._list.addItem(item)

    def remove_session(self, session_id: int) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(SESSION_ID_ROLE) == session_id:
                self._list.takeItem(i)
                return

    def _on_disconnect_clicked(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        self.disconnect_requested.emit(items[0].data(SESSION_ID_ROLE))

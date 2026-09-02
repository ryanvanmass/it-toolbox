from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ConnectionManagerView(QWidget):
    """Placeholder view for the Connection Manager module.

    Replaced with the real project/instance tree + toolbar in M2/M4.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        label = QLabel(
            "Connection Manager\n\n"
            "GCP project/instance browsing and IAP-tunneled RDP/SSH "
            "connections will appear here."
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

"""The one-time "here is the new login" dialog shown after Set Password….

The password is deliberately not displayed: it is held only so the Copy
Password button can put it on the clipboard, and the field shows a fixed-length
mask (so not even its length leaks) -- no reading it off a shared screen, over
someone's shoulder, or out of a screenshot. It is also never placed in any
widget's text, tooltip or title.
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_MASK = "•" * 12


class PasswordResetDialog(QDialog):
    #: How long the Copy button says "Copied" before reverting.
    COPIED_FEEDBACK_MS = 2000

    def __init__(
        self,
        instance_name: str,
        username: str,
        password: str,
        note: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Password Reset")
        self._password = password

        heading = QLabel(f"New login for {instance_name} — shown once:")
        heading.setWordWrap(True)

        username_label = QLabel(username)
        username_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # A plain label of bullets (not a QLineEdit holding the password):
        # nothing in the widget tree contains the real value.
        password_label = QLabel(_MASK)
        self._copy_button = QPushButton("Copy Password")
        self._copy_button.setToolTip("Copy the new password to the clipboard")
        self._copy_button.clicked.connect(self._on_copy_clicked)
        password_row = QWidget()
        password_row_layout = QHBoxLayout(password_row)
        password_row_layout.setContentsMargins(0, 0, 0, 0)
        password_row_layout.addWidget(password_label)
        password_row_layout.addWidget(self._copy_button)
        password_row_layout.addStretch(1)

        form = QFormLayout()
        form.addRow("Username:", username_label)
        form.addRow("Password:", password_row)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addLayout(form)
        if note:
            note_label = QLabel(note)
            note_label.setWordWrap(True)
            layout.addWidget(note_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        # A child timer (not QTimer.singleShot) so it dies with the dialog
        # rather than firing at a deleted button.
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_copy_label)

    def _on_copy_clicked(self) -> None:
        QGuiApplication.clipboard().setText(self._password)
        self._copy_button.setText("Copied ✓")
        self._feedback_timer.start(self.COPIED_FEEDBACK_MS)

    def _restore_copy_label(self) -> None:
        self._copy_button.setText("Copy Password")

"""CRUD dialog for the session automation library -- named scripts that
the session tab right-click "Run Automation" menu types into an RDP or
SSH tab as keystrokes/stdin (see app.MainWindow._build_session_tab_menu).

Deliberately just name + text + a declared shell: no remote execution,
no result feedback. The shell is a label, not something this app runs --
the script is typed into whatever already has focus in the session -- but
the tab menu uses it to list the automations that fit that tab first
(Bash for SSH/terminal tabs, PowerShell/cmd for RDP). Any automation can
still be run against any RDP or SSH tab.
Mirrors connection_manager/ui/manage_hosts_dialog.py.
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

AUTOMATION_ROLE = Qt.ItemDataRole.UserRole

SHELL_ANY = "Any"
SHELLS = (SHELL_ANY, "Bash", "PowerShell", "cmd")


def display_name(name: str, shell: str) -> str:
    """How an automation is labelled in the library list and the tab
    menu -- the shell in parentheses, unless it's the catch-all "Any"."""
    return name if shell == SHELL_ANY else f"{name} ({shell})"


@dataclass(frozen=True)
class Automation:
    name: str
    content: str
    shell: str = SHELL_ANY

    @classmethod
    def from_dict(cls, data: dict) -> "Automation":
        # Automations saved before the shell field existed have no
        # "shell" key -- they load as "Any".
        shell = data.get("shell", SHELL_ANY)
        return cls(
            name=data.get("name", ""),
            content=data.get("content", ""),
            shell=shell if shell in SHELLS else SHELL_ANY,
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "content": self.content, "shell": self.shell}


class _AutomationEditDialog(QDialog):
    """Add or edit a single automation's name and script content."""

    def __init__(self, automation: Automation | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Automation" if automation else "Add Automation")
        self.resize(560, 420)

        self._name_edit = QLineEdit(automation.name if automation else "")
        self._shell_combo = QComboBox()
        self._shell_combo.addItems(SHELLS)
        self._shell_combo.setCurrentText(automation.shell if automation else SHELL_ANY)
        self._content_edit = QPlainTextEdit(automation.content if automation else "")
        self._content_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._content_edit.setPlaceholderText(
            "Typed into the session exactly as written, one line at a time, "
            "with Enter after each line."
        )

        form = QFormLayout()
        form.addRow("Name:", self._name_edit)
        form.addRow("Shell:", self._shell_combo)
        form.addRow("Script:", self._content_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def automation(self) -> Automation:
        return Automation(
            name=self._name_edit.text().strip(),
            content=self._content_edit.toPlainText(),
            shell=self._shell_combo.currentText(),
        )


class ManageAutomationsDialog(QDialog):
    """Lets the user add, edit, and remove saved automations.

    Edits apply to the in-dialog list immediately; the caller reads back
    the final list via automations() once this closes and is responsible
    for persisting it (settings.save_automations) -- same as
    ManageHostsDialog.
    """

    def __init__(self, automations: list[Automation], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Automations")
        self.resize(420, 320)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._on_edit_clicked())
        for automation in automations:
            self._add_list_item(automation)

        add_button = QPushButton("Add…")
        add_button.clicked.connect(self._on_add_clicked)
        edit_button = QPushButton("Edit…")
        edit_button.clicked.connect(self._on_edit_clicked)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._on_remove_clicked)

        buttons_bar = QHBoxLayout()
        buttons_bar.addWidget(add_button)
        buttons_bar.addWidget(edit_button)
        buttons_bar.addWidget(remove_button)
        buttons_bar.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_bar = QHBoxLayout()
        close_bar.addStretch()
        close_bar.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons_bar)
        layout.addLayout(close_bar)

    # Split out from the button handlers so tests can drive add/edit
    # without ever calling _AutomationEditDialog.exec() (a real, blocking
    # modal headless).
    def _make_edit_dialog(self, automation: Automation | None = None) -> _AutomationEditDialog:
        return _AutomationEditDialog(automation, parent=self)

    def _add_list_item(self, automation: Automation) -> None:
        item = QListWidgetItem(display_name(automation.name, automation.shell))
        item.setData(AUTOMATION_ROLE, automation)
        self._list.addItem(item)

    def _on_add_clicked(self) -> None:
        dialog = self._make_edit_dialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        automation = dialog.automation()
        if automation.name and automation.content:
            self._add_list_item(automation)

    def _on_edit_clicked(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        dialog = self._make_edit_dialog(item.data(AUTOMATION_ROLE))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        automation = dialog.automation()
        if automation.name and automation.content:
            item.setText(display_name(automation.name, automation.shell))
            item.setData(AUTOMATION_ROLE, automation)

    def _on_remove_clicked(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._list.takeItem(self._list.row(item))

    def automations(self) -> list[Automation]:
        return [self._list.item(i).data(AUTOMATION_ROLE) for i in range(self._list.count())]

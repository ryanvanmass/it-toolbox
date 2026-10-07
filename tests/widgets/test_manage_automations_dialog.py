from PySide6.QtWidgets import QDialog

from it_toolbox.widgets.manage_automations_dialog import (
    Automation,
    ManageAutomationsDialog,
    _AutomationEditDialog,
)


class _FakeEditDialog:
    """Stands in for _AutomationEditDialog -- its exec() is a real,
    blocking modal headless."""

    def __init__(self, result, automation):
        self._result = result
        self._automation = automation

    def exec(self):
        return self._result

    def automation(self):
        return self._automation


def _make_dialog(qtbot, automations=()):
    dialog = ManageAutomationsDialog(list(automations))
    qtbot.addWidget(dialog)
    return dialog


def test_lists_initial_automations(qtbot):
    dialog = _make_dialog(qtbot, [Automation("one", "ls"), Automation("two", "pwd")])

    assert [dialog._list.item(i).text() for i in range(dialog._list.count())] == ["one", "two"]
    assert dialog.automations() == [Automation("one", "ls"), Automation("two", "pwd")]


def test_add_appends_the_new_automation(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, [Automation("one", "ls")])
    monkeypatch.setattr(
        dialog,
        "_make_edit_dialog",
        lambda automation=None: _FakeEditDialog(QDialog.DialogCode.Accepted, Automation("new", "whoami")),
    )

    dialog._on_add_clicked()

    assert dialog.automations() == [Automation("one", "ls"), Automation("new", "whoami")]


def test_cancelled_or_blank_add_changes_nothing(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot)
    results = iter(
        [
            _FakeEditDialog(QDialog.DialogCode.Rejected, Automation("x", "y")),
            _FakeEditDialog(QDialog.DialogCode.Accepted, Automation("", "y")),
            _FakeEditDialog(QDialog.DialogCode.Accepted, Automation("x", "")),
        ]
    )
    monkeypatch.setattr(dialog, "_make_edit_dialog", lambda automation=None: next(results))

    for _ in range(3):
        dialog._on_add_clicked()

    assert dialog.automations() == []


def test_edit_replaces_the_selected_automation(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, [Automation("one", "ls"), Automation("two", "pwd")])
    dialog._list.setCurrentRow(1)
    seen = []

    def _fake(automation=None):
        seen.append(automation)
        return _FakeEditDialog(QDialog.DialogCode.Accepted, Automation("renamed", "pwd -P"))

    monkeypatch.setattr(dialog, "_make_edit_dialog", _fake)

    dialog._on_edit_clicked()

    assert seen == [Automation("two", "pwd")]
    assert dialog.automations() == [Automation("one", "ls"), Automation("renamed", "pwd -P")]
    assert dialog._list.item(1).text() == "renamed"


def test_remove_drops_the_selected_automation(qtbot):
    dialog = _make_dialog(qtbot, [Automation("one", "ls"), Automation("two", "pwd")])
    dialog._list.setCurrentRow(0)

    dialog._on_remove_clicked()

    assert dialog.automations() == [Automation("two", "pwd")]


def test_edit_dialog_round_trips_name_and_multiline_content(qtbot):
    edit = _AutomationEditDialog(Automation("  Update  ", "apt update\napt upgrade -y\n"))
    qtbot.addWidget(edit)

    assert edit.automation() == Automation("Update", "apt update\napt upgrade -y\n")


def test_automation_dict_round_trip():
    automation = Automation("n", "c")

    assert Automation.from_dict(automation.to_dict()) == automation


def test_shell_defaults_to_any_for_automations_saved_without_one():
    assert Automation.from_dict({"name": "n", "content": "c"}).shell == "Any"
    assert Automation.from_dict({"name": "n", "content": "c", "shell": "bogus"}).shell == "Any"


def test_automation_dict_round_trip_keeps_shell():
    automation = Automation("n", "c", "PowerShell")

    assert automation.to_dict() == {"name": "n", "content": "c", "shell": "PowerShell"}
    assert Automation.from_dict(automation.to_dict()) == automation


def test_edit_dialog_round_trips_shell(qtbot):
    edit = _AutomationEditDialog(Automation("Svc", "Get-Service", "PowerShell"))
    qtbot.addWidget(edit)

    assert edit.automation().shell == "PowerShell"
    edit._shell_combo.setCurrentText("cmd")
    assert edit.automation().shell == "cmd"


def test_list_labels_show_the_declared_shell(qtbot):
    dialog = _make_dialog(qtbot, [Automation("Svc", "x", "PowerShell"), Automation("Any one", "y")])

    assert [dialog._list.item(i).text() for i in range(2)] == ["Svc (PowerShell)", "Any one"]

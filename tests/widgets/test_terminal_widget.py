import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from it_toolbox.widgets.terminal_widget import TerminalWidget

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="ptyprocess is POSIX-only")


def _type(widget: TerminalWidget, text: str) -> None:
    for ch in text:
        widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, ch))


def test_terminal_renders_shell_prompt(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)

    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)
    term.close_session()


def test_terminal_echoes_typed_command_output(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    _type(term, "echo hello_from_pty\n")

    qtbot.waitUntil(lambda: "hello_from_pty" in term.toPlainText(), timeout=3000)
    term.close_session()


def test_terminal_is_read_only_for_direct_text_edits(qtbot):
    # All content must come from re-rendering pty output, never direct
    # editing of the widget's own text buffer.
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    assert term.isReadOnly()
    term.close_session()


def test_cursor_block_is_painted_at_a_single_character(qtbot):
    # Regression test: Qt's native blinking text cursor turned out
    # unreliable here (setPlainText() on every update resets its blink
    # phase, and a read-only widget gets no help from normal editing to
    # keep it visible) — an explicit ExtraSelection block is painted
    # instead, the same technique real terminal emulators use.
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    selections = term.extraSelections()
    assert len(selections) == 1
    assert len(selections[0].cursor.selectedText()) == 1
    fmt = selections[0].format
    assert fmt.background().color() != fmt.foreground().color()
    term.close_session()


def test_close_session_terminates_child_process(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    assert term._pty.is_alive()
    term.close_session()
    qtbot.waitUntil(lambda: not term._pty.is_alive(), timeout=3000)

import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from it_toolbox.widgets.terminal_widget import TerminalWidget

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="ptyprocess is POSIX-only")


def _type(widget: TerminalWidget, text: str) -> None:
    for ch in text:
        widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, ch))


def _press_paste_shortcut(widget: TerminalWidget) -> None:
    # Builds the actual platform paste binding (Ctrl+V on Windows/Linux,
    # Cmd+V on macOS) rather than hardcoding one, so this exercises the
    # same event.matches(QKeySequence.StandardKey.Paste) check the widget
    # itself uses.
    combo = QKeySequence(QKeySequence.StandardKey.Paste)[0]
    widget.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, combo.key(), combo.keyboardModifiers())
    )


def test_terminal_renders_shell_prompt(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)

    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)
    term.close_session()


def test_terminal_uses_default_font_size_when_not_specified(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)

    default_size = term.font().pointSize()

    term.close_session()
    assert default_size > 0  # whatever Qt's own default monospace size is, just not "unset"


def test_terminal_applies_a_configured_font_point_size(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24, font_point_size=18)
    qtbot.addWidget(term)

    assert term.font().pointSize() == 18
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


def test_paste_shortcut_writes_clipboard_text_to_the_shell(qtbot):
    QApplication.clipboard().setText("echo pasted_from_clipboard\n")
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    _press_paste_shortcut(term)

    qtbot.waitUntil(lambda: "pasted_from_clipboard" in term.toPlainText(), timeout=3000)
    term.close_session()


def test_ctrl_shift_v_pastes_instead_of_sending_a_control_byte(qtbot):
    # Regression test: Ctrl+Shift+V never matches
    # QKeySequence.StandardKey.Paste, so without an explicit check it fell
    # through to the Ctrl+letter branch and sent a literal ^V control byte
    # to the shell instead of pasting -- many real terminal emulators
    # (GNOME Terminal, Konsole, ...) bind paste there specifically because
    # plain Ctrl+V is already meaningful to a shell/readline.
    QApplication.clipboard().setText("echo pasted_via_ctrl_shift_v\n")
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    term.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
    )

    qtbot.waitUntil(lambda: "pasted_via_ctrl_shift_v" in term.toPlainText(), timeout=3000)
    term.close_session()


def test_paste_with_empty_clipboard_writes_nothing(qtbot, monkeypatch):
    QApplication.clipboard().setText("")
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    writes = []
    monkeypatch.setattr(term._pty, "write", lambda data: writes.append(data))

    _press_paste_shortcut(term)

    assert writes == []
    term.close_session()


def test_close_session_terminates_child_process(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    assert term._pty.is_alive()
    term.close_session()
    qtbot.waitUntil(lambda: not term._pty.is_alive(), timeout=3000)


# -- Tab: forwarded to the pty, not stolen by Qt's own focus-traversal ------
#
# QWidget's default Tab-key focus-traversal only has somewhere to go (and so
# only actually misbehaves) when there's another focusable widget in the
# same window to steal focus to -- an isolated TerminalWidget with no
# siblings wouldn't reproduce the bug this guards against (real usage always
# has sibling tabs/sidebar widgets in the same window). See RdpWidget's
# identical fixture/tests for the same reasoning.


@pytest.fixture
def terminal_with_sibling(qtbot):
    container = QWidget()
    layout = QVBoxLayout(container)
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24, parent=container)
    sibling = QLineEdit(container)
    layout.addWidget(term)
    layout.addWidget(sibling)
    qtbot.addWidget(container)
    container.show()
    qtbot.waitExposed(container)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)
    term.setFocus()
    yield term
    term.close_session()


def test_tab_does_not_steal_focus(qtbot, terminal_with_sibling):
    term = terminal_with_sibling
    assert term.hasFocus()

    qtbot.keyClick(term, Qt.Key.Key_Tab)

    assert term.hasFocus()


def test_tab_is_forwarded_to_the_pty(qtbot, monkeypatch, terminal_with_sibling):
    term = terminal_with_sibling
    writes = []
    monkeypatch.setattr(term._pty, "write", lambda data: writes.append(data))

    qtbot.keyClick(term, Qt.Key.Key_Tab)

    assert writes == [b"\t"]


def test_shift_tab_does_not_steal_focus(qtbot, terminal_with_sibling):
    term = terminal_with_sibling
    assert term.hasFocus()

    qtbot.keyClick(term, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)

    assert term.hasFocus()


# -- Resizing the widget resizes the pty/pyte grid to match -----------------
#
# Regression: the pty/pyte screen was a fixed cols x rows grid, entirely
# disconnected from the widget's actual pixel size -- a full-screen program
# like nano/vim only ever redraws to fill whatever size the pty *reports*
# (via TIOCSWINCH), so growing the widget left everything past its size at
# construction time as dead space instead of the display actually scaling
# up to fill it.


def test_growing_the_widget_grows_the_terminal_grid(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    term.show()
    qtbot.waitExposed(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    term.resize(term.width() * 3, term.height() * 3)
    qtbot.wait(50)

    assert term._cols > 80
    assert term._rows > 24
    term.close_session()


def test_shrinking_the_widget_shrinks_the_terminal_grid(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    term.resize(1600, 1200)
    term.show()
    qtbot.waitExposed(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)
    grown_cols, grown_rows = term._cols, term._rows

    term.resize(term.width() // 4, term.height() // 4)
    qtbot.wait(50)

    assert term._cols < grown_cols
    assert term._rows < grown_rows
    term.close_session()


def test_resizing_the_widget_sends_the_new_size_to_the_pty(qtbot, monkeypatch):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    term.show()
    qtbot.waitExposed(term)
    qtbot.waitUntil(lambda: bool(term.toPlainText().strip()), timeout=3000)

    resize_calls = []
    monkeypatch.setattr(term._pty, "resize", lambda cols, rows: resize_calls.append((cols, rows)))

    term.resize(term.width() * 2, term.height() * 2)
    qtbot.wait(50)

    assert resize_calls
    assert resize_calls[-1] == (term._cols, term._rows)
    term.close_session()

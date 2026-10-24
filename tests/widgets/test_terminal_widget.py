import shutil
import subprocess
import sys

import pyte
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from it_toolbox.widgets.terminal_widget import (
    TerminalWidget,
    _TerminalScreen,
    encode_key,
)

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


def test_send_text_writes_lines_with_enter_bytes(qtbot, monkeypatch):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)
    writes = []
    monkeypatch.setattr(term._pty, "write", lambda data: writes.append(data))

    term.send_text("echo one\r\necho two\n")

    assert writes == [b"echo one\recho two\r"]
    term.close_session()


def test_send_text_runs_the_script_in_the_shell(qtbot):
    term = TerminalWidget(["/bin/sh"], cols=80, rows=24)
    qtbot.addWidget(term)

    term.send_text("echo from_automation_$((40+2))\n")

    qtbot.waitUntil(lambda: "from_automation_42" in term.toPlainText(), timeout=3000)
    term.close_session()


# -- Full-screen programs (tmux, nano, vim) ---------------------------------



_NO_MOD = Qt.KeyboardModifier.NoModifier
_CTRL = Qt.KeyboardModifier.ControlModifier


def test_cursor_keys_follow_application_cursor_mode():
    assert encode_key(Qt.Key.Key_Up, _NO_MOD, "") == b"\x1b[A"
    assert encode_key(Qt.Key.Key_Up, _NO_MOD, "", app_cursor=True) == b"\x1bOA"
    assert encode_key(Qt.Key.Key_Home, _NO_MOD, "", app_cursor=True) == b"\x1bOH"


def test_modified_cursor_and_function_keys_use_xterm_encoding():
    assert encode_key(Qt.Key.Key_Left, _CTRL, "") == b"\x1b[1;5D"
    assert encode_key(Qt.Key.Key_F1, _NO_MOD, "") == b"\x1bOP"
    assert encode_key(Qt.Key.Key_F5, _NO_MOD, "") == b"\x1b[15~"
    assert encode_key(Qt.Key.Key_PageUp, Qt.KeyboardModifier.ShiftModifier, "") == b"\x1b[5;2~"
    assert encode_key(Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier, "") == b"\x1b[Z"


def test_ctrl_symbol_keys_send_control_bytes():
    # nano's "^\ Replace" and "^/ Go To Line", plus Ctrl+Space.
    assert encode_key(Qt.Key.Key_Backslash, _CTRL, "") == b"\x1c"
    assert encode_key(Qt.Key.Key_Slash, _CTRL, "") == b"\x1f"
    assert encode_key(Qt.Key.Key_Space, _CTRL, "") == b"\x00"
    assert encode_key(Qt.Key.Key_B, _CTRL, "") == b"\x02"  # tmux prefix


@pytest.mark.skipif(sys.platform == "darwin", reason="Option composes characters on macOS")
def test_alt_prefixes_escape():
    assert encode_key(Qt.Key.Key_U, Qt.KeyboardModifier.AltModifier, "u") == b"\x1bu"


def test_alternate_screen_restores_the_shell_output():
    screen = _TerminalScreen(20, 5)
    stream = pyte.ByteStream(screen)
    stream.feed(b"$ before")
    stream.feed(b"\x1b[?1049h\x1b[2J\x1b[Hfull screen app")
    assert "full screen app" in screen.display[0]
    stream.feed(b"\x1b[?1049l")
    assert screen.display[0].rstrip() == "$ before"
    assert (screen.cursor.x, screen.cursor.y) == (8, 0)


def test_unsupported_private_sequences_do_not_drop_output():
    # vim sends "CSI > 4;2 m"; pyte raised on it and lost the rest of the read.
    screen = _TerminalScreen(20, 5)
    pyte.ByteStream(screen).feed(b"\x1b[>4;2m\x1b[?6nafter")
    assert screen.display[0].rstrip() == "after"


def test_utf8_split_across_reads_is_decoded(qtbot):
    term = TerminalWidget(["/bin/sh", "-c", "sleep 5"], cols=20, rows=5)
    qtbot.addWidget(term)
    box = "┌─┐".encode()
    term._on_output(box[:4])
    term._on_output(box[4:])
    assert term._screen.display[0].startswith("┌─┐")
    term.close_session()


def test_device_attribute_queries_are_answered(qtbot, monkeypatch):
    term = TerminalWidget(["/bin/sh", "-c", "sleep 5"], cols=20, rows=5)
    qtbot.addWidget(term)
    writes = []
    monkeypatch.setattr(term._pty, "write", lambda data: writes.append(data))
    term._on_output(b"\x1b[c")
    assert writes == [b"\x1b[?6c"]
    term.close_session()


def test_bracketed_paste_wraps_clipboard_text(qtbot, monkeypatch):
    QApplication.clipboard().setText("pasted")
    term = TerminalWidget(["/bin/sh", "-c", "sleep 5"], cols=20, rows=5)
    qtbot.addWidget(term)
    writes = []
    monkeypatch.setattr(term._pty, "write", lambda data: writes.append(data))
    term._on_output(b"\x1b[?2004h")
    _press_paste_shortcut(term)
    assert writes == [b"\x1b[200~pasted\x1b[201~"]
    term.close_session()


def test_colored_output_is_rendered_with_its_color(qtbot):
    term = TerminalWidget(["/bin/sh", "-c", "sleep 5"], cols=20, rows=5)
    qtbot.addWidget(term)
    term._on_output(b"\x1b[31mred\x1b[0m")
    term._render()
    block = term.document().firstBlock()
    fmt = block.begin().fragment().charFormat()
    assert block.begin().fragment().text() == "red"
    assert fmt.foreground().color().name() == "#cd3131"
    term.close_session()


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_tmux_starts_inside_the_terminal(qtbot, monkeypatch, tmp_path):
    # The bug from issue #123: launched from a desktop entry TERM is unset,
    # and tmux refused to start ("terminal does not support clear").
    monkeypatch.delenv("TERM", raising=False)
    socket = str(tmp_path / "tmux.sock")
    term = TerminalWidget(["tmux", "-S", socket, "-f", "/dev/null", "new"], cols=80, rows=24)
    qtbot.addWidget(term)
    try:
        qtbot.waitUntil(lambda: "[0]" in term.toPlainText(), timeout=5000)
        assert "open terminal failed" not in term.toPlainText()
    finally:
        term.close_session()
        subprocess.run(["tmux", "-S", socket, "kill-server"], check=False, capture_output=True)

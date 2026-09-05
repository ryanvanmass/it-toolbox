"""A minimal embedded terminal widget.

pyte parses the child process's output into a character-grid screen model;
that grid is re-rendered here as plain text on every update. There's no
per-cell color/attribute rendering yet (a real terminal emulator's screen
is colored text, this one is monochrome) — a known, deliberate simplification
to get a working embedded shell first rather than a fully-faithful one.
"""

import sys
import threading

import pyte
from PySide6.QtCore import QSocketNotifier, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QMenu, QPlainTextEdit, QTextEdit, QWidget

from it_toolbox.widgets.pty_backend import PtyHandle

_IS_WINDOWS = sys.platform == "win32"

# Keys without a meaningful event.text() get translated to the escape
# sequence a real terminal would send for them.
_SPECIAL_KEYS: dict[Qt.Key, bytes] = {
    Qt.Key.Key_Return: b"\r",
    Qt.Key.Key_Enter: b"\r",
    Qt.Key.Key_Backspace: b"\x7f",
    Qt.Key.Key_Tab: b"\t",
    Qt.Key.Key_Escape: b"\x1b",
    Qt.Key.Key_Up: b"\x1b[A",
    Qt.Key.Key_Down: b"\x1b[B",
    Qt.Key.Key_Right: b"\x1b[C",
    Qt.Key.Key_Left: b"\x1b[D",
    Qt.Key.Key_Home: b"\x1b[H",
    Qt.Key.Key_End: b"\x1b[F",
    Qt.Key.Key_Delete: b"\x1b[3~",
    Qt.Key.Key_PageUp: b"\x1b[5~",
    Qt.Key.Key_PageDown: b"\x1b[6~",
}


class TerminalWidget(QPlainTextEdit):
    """Spawns `argv` in a pty and renders its output; keystrokes are sent
    straight to the child process rather than edited locally.
    """

    finished = Signal()
    _output_ready = Signal(bytes)  # background-thread -> main-thread bridge (Windows only)

    def __init__(self, argv: list[str], cols: int = 100, rows: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(font)

        self._cols = cols
        self._rows = rows
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)
        self._pty = PtyHandle(argv, cols=cols, rows=rows)

        self._notifier: QSocketNotifier | None = None
        self._reader_thread: threading.Thread | None = None
        self._output_ready.connect(self._on_output)

        if _IS_WINDOWS or self._pty.fd is None:
            self._start_reader_thread()
        else:
            self._start_socket_notifier(self._pty.fd)

    # -- reading pty output ---------------------------------------------

    def _start_socket_notifier(self, fd: int) -> None:
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(lambda: self._on_output(self._pty.read()))

    def _start_reader_thread(self) -> None:
        def run() -> None:
            while True:
                data = self._pty.read()
                # The widget can be deleted (tab closed) while this blocking
                # read() was still in flight — same cross-thread QObject
                # lifetime hazard as core/async_utils.py, guarded the same way.
                try:
                    self._output_ready.emit(data)
                except RuntimeError:
                    return
                if not data:
                    return

        self._reader_thread = threading.Thread(target=run, daemon=True)
        self._reader_thread.start()

    def _on_output(self, data: bytes) -> None:
        if not data:
            if self._notifier is not None:
                self._notifier.setEnabled(False)
            self.finished.emit()
            return
        self._stream.feed(data.decode(errors="replace"))
        self._render()

    def _render(self) -> None:
        # pyte's rows are already padded to exactly `cols` characters wide —
        # rstrip()-ing them here would shorten lines and misalign the
        # cursor's column index against the (now-shorter) rendered text.
        self.setPlainText("\n".join(self._screen.display))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, n=self._screen.cursor.y)
        cursor.movePosition(QTextCursor.MoveOperation.Right, n=self._screen.cursor.x)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self._paint_cursor_block(cursor)

    def _paint_cursor_block(self, cursor: QTextCursor) -> None:
        # Qt's native blinking text cursor turned out unreliable to see here
        # — replacing the whole document on every update (setPlainText,
        # above) resets its blink phase each time, and a read-only widget
        # gets no help from normal editing to keep it visible. Paint an
        # explicit solid block instead, the same way real terminal emulators
        # render their cursor, using an ExtraSelection rather than Qt's
        # built-in cursor rendering.
        if self._screen.cursor.hidden:
            self.setExtraSelections([])
            return

        block_cursor = QTextCursor(cursor)
        block_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)

        fmt = QTextCharFormat()
        fmt.setBackground(self.palette().text())
        fmt.setForeground(self.palette().base())

        selection = QTextEdit.ExtraSelection()
        selection.cursor = block_cursor
        selection.format = fmt
        self.setExtraSelections([selection])

    # -- writing keystrokes ------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()

        # Checked ahead of the Ctrl+letter branch below: on the platforms
        # this resolves to Ctrl+V (Windows/Linux) it would otherwise be
        # swallowed as the literal ^V control byte, which is where "can't
        # paste into the terminal" came from — Ctrl+V never reached
        # anything but that byte.
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_clipboard()
            return

        if modifiers & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            self._pty.write(bytes([key - Qt.Key.Key_A + 1]))
            return

        if key in _SPECIAL_KEYS:
            self._pty.write(_SPECIAL_KEYS[key])
            return

        text = event.text()
        if text:
            self._pty.write(text.encode())

    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self._pty.write(text.encode())

    def contextMenuEvent(self, event) -> None:
        # A read-only QPlainTextEdit's standard context menu offers Copy
        # but never Paste (Qt gates it on the widget being editable) — this
        # widget's "editing" is relaying keystrokes to the pty rather than
        # the document, so Paste is wired up manually here instead.
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(self.textCursor().hasSelection())
        paste_action = menu.addAction("Paste")
        paste_action.setEnabled(bool(QApplication.clipboard().text()))
        menu.addSeparator()
        select_all_action = menu.addAction("Select All")
        chosen = menu.exec(event.globalPos())
        if chosen is copy_action:
            self.copy()
        elif chosen is paste_action:
            self._paste_clipboard()
        elif chosen is select_all_action:
            self.selectAll()

    def resizeTerminal(self, cols: int, rows: int) -> None:
        self._cols, self._rows = cols, rows
        self._screen.resize(rows, cols)
        self._pty.resize(cols, rows)

    def close_session(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
        self._pty.close()

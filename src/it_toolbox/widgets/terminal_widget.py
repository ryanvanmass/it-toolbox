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
from PySide6.QtGui import QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

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
                self._output_ready.emit(data)
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

    # -- writing keystrokes ------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            self._pty.write(bytes([key - Qt.Key.Key_A + 1]))
            return

        if key in _SPECIAL_KEYS:
            self._pty.write(_SPECIAL_KEYS[key])
            return

        text = event.text()
        if text:
            self._pty.write(text.encode())

    def resizeTerminal(self, cols: int, rows: int) -> None:
        self._cols, self._rows = cols, rows
        self._screen.resize(rows, cols)
        self._pty.resize(cols, rows)

    def close_session(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
        self._pty.close()

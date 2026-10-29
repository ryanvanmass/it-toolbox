"""A minimal embedded terminal widget.

pyte parses the child process's output into a character-grid screen model;
that grid is re-rendered here as colored text runs (foreground, background,
bold, italics, underline, strikethrough, reverse video) on every update.
Full-screen programs (tmux, nano, vim, htop, ...) additionally need the
alternate screen, cursor-key application mode, replies to terminal queries
and xterm's key encodings, all of which are handled below.
"""

import inspect
import logging
import sys
import threading

import pyte
from PySide6.QtCore import QEvent, QSocketNotifier, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QKeyEvent,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QApplication, QMenu, QPlainTextEdit, QTextEdit, QWidget
from wcwidth import wcwidth

from it_toolbox.widgets.pty_backend import PtyHandle

_IS_WINDOWS = sys.platform == "win32"

logger = logging.getLogger(__name__)

# Keys without a meaningful event.text() get translated to the escape
# sequence xterm sends for them (pyte emulates an xterm, and TERM is set to
# xterm-256color for the child, so its terminfo describes these).
_SPECIAL_KEYS: dict[Qt.Key, bytes] = {
    Qt.Key.Key_Return: b"\r",
    Qt.Key.Key_Enter: b"\r",
    Qt.Key.Key_Backspace: b"\x7f",
    Qt.Key.Key_Tab: b"\t",
    Qt.Key.Key_Backtab: b"\x1b[Z",
    Qt.Key.Key_Escape: b"\x1b",
}

# Cursor keys: final byte of "CSI <x>" (normal mode) / "SS3 <x>" (cursor-key
# application mode, DECCKM -- what vim/nano/tmux switch on, and what
# terminfo's kcuu1/khome/... say these keys send).
_CURSOR_KEYS: dict[Qt.Key, str] = {
    Qt.Key.Key_Up: "A",
    Qt.Key.Key_Down: "B",
    Qt.Key.Key_Right: "C",
    Qt.Key.Key_Left: "D",
    Qt.Key.Key_Home: "H",
    Qt.Key.Key_End: "F",
}

# F1-F4 are SS3 P..S; everything else here is "CSI <n> ~".
_SS3_FUNCTION_KEYS: dict[Qt.Key, str] = {
    Qt.Key.Key_F1: "P",
    Qt.Key.Key_F2: "Q",
    Qt.Key.Key_F3: "R",
    Qt.Key.Key_F4: "S",
}
_TILDE_KEYS: dict[Qt.Key, int] = {
    Qt.Key.Key_Insert: 2,
    Qt.Key.Key_Delete: 3,
    Qt.Key.Key_PageUp: 5,
    Qt.Key.Key_PageDown: 6,
    Qt.Key.Key_F5: 15,
    Qt.Key.Key_F6: 17,
    Qt.Key.Key_F7: 18,
    Qt.Key.Key_F8: 19,
    Qt.Key.Key_F9: 20,
    Qt.Key.Key_F10: 21,
    Qt.Key.Key_F11: 23,
    Qt.Key.Key_F12: 24,
}

# Ctrl+<symbol> control bytes beyond Ctrl+A..Z -- e.g. nano's "^\\ Replace"
# and "^/ Go To Line", Ctrl+Space for emacs' mark, Ctrl+] for telnet.
_CTRL_SYMBOL_KEYS: dict[Qt.Key, bytes] = {
    Qt.Key.Key_Space: b"\x00",
    Qt.Key.Key_At: b"\x00",
    Qt.Key.Key_2: b"\x00",
    Qt.Key.Key_BracketLeft: b"\x1b",
    Qt.Key.Key_Backslash: b"\x1c",
    Qt.Key.Key_BracketRight: b"\x1d",
    Qt.Key.Key_AsciiCircum: b"\x1e",
    Qt.Key.Key_6: b"\x1e",
    Qt.Key.Key_Underscore: b"\x1f",
    Qt.Key.Key_Minus: b"\x1f",
    Qt.Key.Key_Slash: b"\x1f",
    Qt.Key.Key_Question: b"\x7f",
    Qt.Key.Key_Backspace: b"\x08",
}

_MODE_DECCKM = 1 << 5  # pyte stores private modes shifted left by 5
_MODE_BRACKETED_PASTE = 2004 << 5
_ALT_SCREEN_MODES = (47, 1047, 1049)


def encode_key(key: int, modifiers: Qt.KeyboardModifier, text: str, app_cursor: bool = False) -> bytes:
    """Returns the bytes xterm would send to the pty for one key press
    (b"" for keys that send nothing, e.g. a bare Shift).
    """
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    # Option on macOS composes characters (é, ø, ...) rather than acting
    # as Meta, so it's left alone there. Ctrl+Alt is how Windows reports
    # AltGr, which also composes characters -- treated the same way.
    alt = bool(modifiers & Qt.KeyboardModifier.AltModifier) and sys.platform != "darwin" and not ctrl
    # xterm's modifier parameter: 1 + Shift(1) + Alt(2) + Ctrl(4).
    mod_param = 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)

    if key in _CURSOR_KEYS:
        final = _CURSOR_KEYS[key]
        if mod_param > 1:
            return f"\x1b[1;{mod_param}{final}".encode()
        return f"\x1b{'O' if app_cursor else '['}{final}".encode()
    if key in _SS3_FUNCTION_KEYS:
        final = _SS3_FUNCTION_KEYS[key]
        if mod_param > 1:
            return f"\x1b[1;{mod_param}{final}".encode()
        return f"\x1bO{final}".encode()
    if key in _TILDE_KEYS:
        number = _TILDE_KEYS[key]
        if mod_param > 1:
            return f"\x1b[{number};{mod_param}~".encode()
        return f"\x1b[{number}~".encode()

    prefix = b"\x1b" if alt else b""
    if ctrl:
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return prefix + bytes([key - Qt.Key.Key_A + 1])
        if key in _CTRL_SYMBOL_KEYS:
            return prefix + _CTRL_SYMBOL_KEYS[key]
    if key in _SPECIAL_KEYS:
        return (b"" if key == Qt.Key.Key_Backtab else prefix) + _SPECIAL_KEYS[key]
    if text:
        return prefix + text.encode()
    return b""


def _drop_private_calls(handler):
    def wrapper(*args, private: bool = False):
        if not private:
            handler(*args)

    return wrapper


class _TerminalScreen(pyte.Screen):
    """pyte.Screen plus the alternate screen buffer (private modes
    47/1047/1049), which pyte itself ignores. Full-screen programs switch
    to it on start and back on exit, which is what restores the shell's
    own output afterwards instead of leaving the program's last frame on
    screen.
    """

    def __init__(self, columns: int, lines: int) -> None:
        super().__init__(columns, lines)
        self._saved_buffer = None
        # pyte dispatches "CSI ? ..." / "CSI > ..." sequences to the same
        # handler with private=True, but most handlers don't take that
        # argument -- vim's "CSI > 4;2 m" (modifyOtherKeys) raised a
        # TypeError that threw away the rest of that read's output,
        # leaving holes in vim's first screen. Private variants of those
        # sequences have no meaning here, so they're dropped instead.
        for name in set(pyte.Stream.csi.values()):
            handler = getattr(self, name)
            parameters = inspect.signature(handler).parameters
            takes_private = "private" in parameters or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
            )
            if not takes_private:
                setattr(self, name, _drop_private_calls(handler))

    @property
    def in_alternate_screen(self) -> bool:
        return self._saved_buffer is not None

    def set_mode(self, *modes: int, **kwargs) -> None:
        if kwargs.get("private") and any(m in _ALT_SCREEN_MODES for m in modes):
            self._enter_alternate_screen(save_cursor=1049 in modes)
            modes = tuple(m for m in modes if m not in _ALT_SCREEN_MODES)
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes: int, **kwargs) -> None:
        if kwargs.get("private") and any(m in _ALT_SCREEN_MODES for m in modes):
            self._leave_alternate_screen(restore_cursor=1049 in modes)
            modes = tuple(m for m in modes if m not in _ALT_SCREEN_MODES)
        super().reset_mode(*modes, **kwargs)

    def _enter_alternate_screen(self, save_cursor: bool) -> None:
        if self.in_alternate_screen:
            return
        if save_cursor:
            self.save_cursor()
        self._saved_buffer = self.buffer
        self.buffer = type(self.buffer)(self.buffer.default_factory)
        self.dirty.update(range(self.lines))

    def _leave_alternate_screen(self, restore_cursor: bool) -> None:
        if not self.in_alternate_screen:
            return
        self.buffer = self._saved_buffer
        self._saved_buffer = None
        if restore_cursor:
            self.restore_cursor()
        self.dirty.update(range(self.lines))

    def reset(self) -> None:
        self._saved_buffer = None
        super().reset()


# xterm-ish 16-color palette, keyed by pyte's color names (pyte calls ANSI
# yellow "brown"). 256-color and truecolor values arrive as hex strings.
_ANSI_COLORS: dict[str, str] = {
    "black": "#000000",
    "red": "#cd3131",
    "green": "#0dbc79",
    "brown": "#e5e510",
    "blue": "#2472c8",
    "magenta": "#bc3fbc",
    "cyan": "#11a8cd",
    "white": "#e5e5e5",
    "brightblack": "#666666",
    "brightred": "#f14c4c",
    "brightgreen": "#23d18b",
    "brightbrown": "#f5f543",
    "brightblue": "#3b8eea",
    "brightmagenta": "#d670d6",
    "brightcyan": "#29b8db",
    "brightwhite": "#ffffff",
}


def _resolve_color(name: str, default: QColor) -> QColor:
    if name == "default":
        return default
    if name in _ANSI_COLORS:
        return QColor(_ANSI_COLORS[name])
    color = QColor(f"#{name}")
    return color if color.isValid() else default


class TerminalWidget(QPlainTextEdit):
    """Spawns `argv` in a pty and renders its output; keystrokes are sent
    straight to the child process rather than edited locally.
    """

    finished = Signal()
    _output_ready = Signal(bytes)  # background-thread -> main-thread bridge (Windows only)

    def __init__(
        self,
        argv: list[str],
        cols: int = 100,
        rows: int = 30,
        font_point_size: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Always a dark terminal, in light mode too -- _ANSI_COLORS is an
        # xterm palette tuned for a dark background (bright yellow/white
        # vanish on white). Colors come from ui/theme.py's #Terminal rule.
        self.setObjectName("Terminal")
        # QFont("Monospace") is a Linux/fontconfig generic-alias name --
        # Windows has no font literally called that, and Qt's substitution
        # for an unrecognized family name there is not guaranteed to give
        # metrics (self.fontMetrics(), used by resizeEvent below) that
        # match what's actually rendered. QFontDatabase's FixedFont is the
        # correct, cross-platform-safe way to ask for "the system's real
        # monospace font" -- resolves to Consolas on Windows, an
        # appropriate default elsewhere -- with no name-lookup ambiguity.
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if font_point_size is not None:
            font.setPointSize(font_point_size)
        self.setFont(font)
        logger.debug(
            "terminal-resize: font requested family=%r pointSize=%d -> "
            "effective family=%r pointSize=%d exactMatch=%s",
            font.family(),
            font.pointSize(),
            self.font().family(),
            self.font().pointSize(),
            self.fontInfo().exactMatch(),
        )

        self._cols = cols
        self._rows = rows
        self._screen = _TerminalScreen(cols, rows)
        # ByteStream decodes UTF-8 incrementally -- decoding each pty read
        # on its own garbled any multi-byte character (tmux's and htop's
        # box-drawing borders, for one) split across two reads.
        self._stream = pyte.ByteStream(self._screen)
        self._pty = PtyHandle(argv, cols=cols, rows=rows)
        # Replies to the program's own queries (device attributes, cursor
        # position) -- pyte generates them but drops them by default, and
        # programs like vim and tmux ask on startup.
        self._screen.write_process_input = lambda reply: self._pty.write(reply.encode())
        self._formats: dict[tuple, QTextCharFormat] = {}

        # Rendering is coalesced: a full-screen redraw usually arrives as
        # several pty reads in a row, and rebuilding the document for each
        # one made tmux/vim visibly lag.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(5)
        self._render_timer.timeout.connect(self._render)

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
        self._stream.feed(data)
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _render(self) -> None:
        # Rows are rendered padded to exactly `cols` characters wide, same
        # as pyte's own Screen.display -- trimming them would shorten lines
        # and misalign the cursor's column index against the rendered text.
        self._render_document()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, n=self._screen.cursor.y)
        cursor.movePosition(QTextCursor.MoveOperation.Right, n=self._screen.cursor.x)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self._paint_cursor_block(cursor)

    def _render_document(self) -> None:
        screen = self._screen
        document = self.document()
        document.clear()
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        for y in range(screen.lines):
            if y:
                cursor.insertText("\n", self._char_format(None))
            line = screen.buffer[y]
            run_text: list[str] = []
            run_key = None
            skip_next = False
            for x in range(screen.columns):
                if skip_next:  # the right half of a wide character
                    skip_next = False
                    continue
                char = line[x]
                skip_next = bool(char.data) and wcwidth(char.data[0]) == 2
                key = (char.fg, char.bg, char.bold, char.italics, char.underscore, char.strikethrough, char.reverse)
                if key != run_key and run_text:
                    cursor.insertText("".join(run_text), self._char_format(run_key))
                    run_text = []
                run_key = key
                run_text.append(char.data or " ")
            if run_text:
                cursor.insertText("".join(run_text), self._char_format(run_key))
        cursor.endEditBlock()

    def _char_format(self, key: tuple | None) -> QTextCharFormat:
        fmt = self._formats.get(key)
        if fmt is not None:
            return fmt
        fmt = QTextCharFormat()
        if key is not None:
            fg_name, bg_name, bold, italics, underscore, strikethrough, reverse = key
            palette = self.palette()
            fg = _resolve_color(fg_name, palette.text().color())
            bg = _resolve_color(bg_name, palette.base().color())
            if reverse:
                fg, bg = bg, fg
            fmt.setForeground(fg)
            if bg_name != "default" or reverse:
                fmt.setBackground(bg)
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontItalic(italics)
            fmt.setFontUnderline(underscore)
            fmt.setFontStrikeOut(strikethrough)
        self._formats[key] = fmt
        return fmt

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._formats.clear()  # default colors follow the palette

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

    def event(self, e) -> bool:  # noqa: N802 - Qt override signature
        # Same fix as RdpWidget/SpiceWidget's own event() override --
        # QWidget's default focus-traversal intercepts Key_Tab/Key_Backtab
        # at this level, before keyPressEvent() ever runs, so shell
        # tab-completion silently never reached the pty: Tab just moved
        # Qt focus to whatever widget was next in line instead. Forward
        # these directly and report the event as handled so that
        # focus-traversal never runs.
        if e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(e)
            return True
        return super().event(e)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()

        # Checked ahead of the Ctrl+letter branch below: on the platforms
        # this resolves to Ctrl+V (Windows/Linux) it would otherwise be
        # swallowed as the literal ^V control byte, which is where "can't
        # paste into the terminal" came from — Ctrl+V never reached
        # anything but that byte. Ctrl+Shift+V is also accepted directly
        # (real terminal emulators — GNOME Terminal, Konsole, etc. — bind
        # paste there instead of/alongside Ctrl+V, precisely because Ctrl+V
        # is already a real, differently-meaningful control byte to a
        # shell): QKeySequence.StandardKey.Paste never matches it, so
        # without this it fell through to the same Ctrl+letter branch and
        # sent ^V instead of pasting, exactly the bug this whole check
        # exists to avoid for plain Ctrl+V.
        if event.matches(QKeySequence.StandardKey.Paste) or (
            modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            and key == Qt.Key.Key_V
        ):
            self._paste_clipboard()
            return

        data = encode_key(key, modifiers, event.text(), app_cursor=_MODE_DECCKM in self._screen.mode)
        if data:
            self._pty.write(data)

    def send_text(self, text: str) -> None:
        """Types text into the session as if entered at the keyboard --
        used by the session tab's "Run Automation" menu. Line breaks are
        sent as Enter's own byte (CR, see _SPECIAL_KEYS) rather than LF,
        so each line is submitted the same way a typed one would be.
        """
        normalized = text.replace("\r\n", "\n").replace("\n", "\r")
        if normalized:
            self._pty.write(normalized.encode())

    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        if _MODE_BRACKETED_PASTE in self._screen.mode:
            # Programs that ask for bracketed paste (vim, nano, bash's
            # readline) then take the text literally instead of
            # auto-indenting or running it line by line.
            self._pty.write(b"\x1b[200~" + text.encode() + b"\x1b[201~")
        else:
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

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        super().resizeEvent(event)
        # The pty/pyte screen is otherwise a fixed cols x rows grid (100x30
        # by default) with no connection at all to this widget's actual
        # pixel size -- a real terminal emulator always keeps the two in
        # sync (via TIOCSWINCH, which resizeTerminal's _pty.resize already
        # sends), so a full-screen program like nano or vim only ever
        # redraws to fill whatever size the pty *reports*, regardless of
        # how large the widget itself has grown to. Without this, the
        # rendered content stays pinned to its size at construction time,
        # leaving the rest of the widget as dead, unused space.
        # Fractional metrics: a monospace advance is rarely a whole number
        # of pixels (7.19px, say), and rounding it down to QFontMetrics'
        # int made cols too large -- the rightmost columns (tmux's status
        # bar clock, vim's ruler) ended up clipped behind a horizontal
        # scrollbar. Line height stays the integer one: QPlainTextEdit lays
        # each line out at a whole number of pixels.
        char_width = QFontMetricsF(self.font()).horizontalAdvance("M") or 1
        char_height = self.fontMetrics().height() or 1
        # QPlainTextEdit's document has its own margin around the text
        # (QTextDocument.documentMargin(), 4px on each side by default) --
        # real usable space for character cells is inside that, not the
        # full viewport.
        margin = self.document().documentMargin()
        available_width = max(0, self.viewport().width() - 2 * margin)
        available_height = max(0, self.viewport().height() - 2 * margin)
        cols = max(1, int(available_width // char_width))
        rows = max(1, int(available_height // char_height))
        logger.debug(
            "terminal-resize: widget=%dx%d viewport=%dx%d margin=%.1f "
            "char=%.2fx%d -> cols=%d rows=%d (was %d,%d)",
            self.width(),
            self.height(),
            self.viewport().width(),
            self.viewport().height(),
            margin,
            char_width,
            char_height,
            cols,
            rows,
            self._cols,
            self._rows,
        )
        if (cols, rows) != (self._cols, self._rows):
            self.resizeTerminal(cols, rows)

    def close_session(self) -> None:
        self._render_timer.stop()
        if self._notifier is not None:
            self._notifier.setEnabled(False)
        self._pty.close()

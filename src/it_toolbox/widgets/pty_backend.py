"""Cross-platform pseudo-terminal process spawning.

Linux/macOS: ptyprocess (wraps the POSIX pty/fork/exec APIs).
Windows: pywinpty (wraps ConPTY). Its `winpty.PtyProcess` class was
deliberately built API-compatible with ptyprocess — the same pattern
Jupyter's terminado package relies on to support both from one code path —
so this wrapper is thin. The Windows path hasn't been exercised on real
Windows yet; verify there before trusting it.
"""

import sys

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import winpty as _pty_impl
else:
    import ptyprocess as _pty_impl


class PtyHandle:
    def __init__(self, argv: list[str], cols: int = 80, rows: int = 24) -> None:
        self._proc = _pty_impl.PtyProcess.spawn(argv, dimensions=(rows, cols))

    @property
    def fd(self) -> int | None:
        """The master file descriptor, for event-loop integration.

        Only meaningful on Unix (ptyprocess) — Windows' ConPTY handle isn't
        a pollable fd, so pywinpty callers must fall back to polling reads
        on a background thread instead.
        """
        return getattr(self._proc, "fd", None)

    def read(self, size: int = 65536) -> bytes:
        """Blocking read. Returns b"" once the child process has exited."""
        try:
            data = self._proc.read(size)
        except EOFError:
            return b""
        return data if isinstance(data, bytes) else data.encode()

    def write(self, data: bytes) -> None:
        try:
            self._proc.write(data)
        except OSError:
            pass  # child already exited; caller will see it via read()

    def resize(self, cols: int, rows: int) -> None:
        self._proc.setwinsize(rows, cols)

    def is_alive(self) -> bool:
        return bool(self._proc.isalive())

    def close(self) -> None:
        try:
            self._proc.terminate(force=True)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

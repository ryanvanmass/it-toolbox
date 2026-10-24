import sys

import pytest

from it_toolbox.widgets.pty_backend import PtyHandle

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty only")


def test_child_gets_xterm_term_even_when_parent_term_is_dumb(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    handle = PtyHandle(["sh", "-c", 'printf "%s" "$TERM"'])
    out = b""
    while chunk := handle.read():
        out += chunk
    handle.close()
    assert out.strip() == b"xterm-256color"

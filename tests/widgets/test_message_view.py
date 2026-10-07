import os
import time

from PySide6.QtWidgets import QMessageBox

from it_toolbox.core.mbox_reader import Attachment, MessageDetail
from it_toolbox.widgets import message_view
from it_toolbox.widgets.message_view import (
    MessageView,
    _safe_filename,
    write_attachment_for_opening,
)

PDF = Attachment(0, "invoice.pdf", "application/pdf", 13)


def _make_view(qtbot, detail=None, data=b"%PDF-1.4 fake"):
    view = MessageView()
    qtbot.addWidget(view)
    if detail is None:
        detail = MessageDetail(0, [("Subject", "Invoice")], "See attached.", None, [PDF])
    view.show_detail(detail, lambda index: data)
    return view


def test_shows_headers_body_and_attachments(qtbot):
    view = _make_view(qtbot)

    assert view._headers_label.text() == "Subject: Invoice"
    assert view._body_view.toPlainText() == "See attached."
    assert view._attachments.count() == 1
    assert view._attachments.item(0).text() == "invoice.pdf  (13 B, application/pdf)"
    assert not view._attachments.isHidden()


def test_html_body_is_used_when_there_is_no_text_part(qtbot):
    view = _make_view(qtbot, MessageDetail(0, [], None, "<p>Hello <b>there</b></p>"))

    assert view._body_view.toPlainText() == "Hello there"
    assert view._attachments.isHidden()


def test_show_error_clears_the_message(qtbot):
    view = _make_view(qtbot)

    view.show_error("Couldn't read this message: boom")

    assert view._headers_label.text() == ""
    assert view._body_view.toPlainText() == "Couldn't read this message: boom"
    assert view._attachments.count() == 0
    assert view._attachment_source is None


def test_saving_an_attachment(qtbot, tmp_path, monkeypatch):
    view = _make_view(qtbot)
    destination = tmp_path / "saved.pdf"
    monkeypatch.setattr(
        message_view.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )

    view._save_attachment(PDF)
    qtbot.waitUntil(destination.exists, timeout=5000)

    assert destination.read_bytes() == b"%PDF-1.4 fake"


def test_double_clicking_an_attachment_opens_a_temp_copy(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(message_view, "OPENED_ATTACHMENTS_DIR", tmp_path / "opened")
    opened = []
    monkeypatch.setattr(
        message_view.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
    )
    view = _make_view(qtbot)

    view._on_attachment_activated(view._attachments.item(0))
    qtbot.waitUntil(lambda: bool(opened), timeout=5000)

    path = opened[0].toLocalFile()
    assert path.endswith("invoice.pdf")
    assert path.startswith(str(tmp_path / "opened"))
    assert open(path, "rb").read() == b"%PDF-1.4 fake"


def test_executable_attachment_asks_before_opening(qtbot, monkeypatch):
    asked = []
    monkeypatch.setattr(
        message_view.QMessageBox,
        "question",
        lambda *args: asked.append(args) or QMessageBox.StandardButton.Cancel,
    )
    view = _make_view(qtbot)
    started = []
    monkeypatch.setattr(
        message_view.async_utils, "run_in_background", lambda *a, **k: started.append(a)
    )

    view._open_attachment(Attachment(0, "invoice.PDF.exe", "application/octet-stream", 3))

    assert "will run it" in asked[0][2].replace("\n", " ")
    assert started == []


def test_write_attachment_for_opening_sweeps_old_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(message_view, "OPENED_ATTACHMENTS_DIR", tmp_path)
    old = tmp_path / "old"
    old.mkdir()
    day_ago = time.time() - 2 * 24 * 60 * 60
    os.utime(old, (day_ago, day_ago))

    first = write_attachment_for_opening("report.pdf", b"a")
    second = write_attachment_for_opening("report.pdf", b"b")

    assert not old.exists()
    assert first != second
    assert (first.read_bytes(), second.read_bytes()) == (b"a", b"b")


def test_safe_filename():
    assert _safe_filename("../../etc/passwd") == "passwd"
    assert _safe_filename("C:\\Users\\x\\evil.txt") == "evil.txt"
    assert _safe_filename('a<b>:"c|?*.txt') == "abc.txt"
    assert _safe_filename("..") == "attachment"

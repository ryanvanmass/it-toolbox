from it_toolbox.widgets import mbox_browser_widget
import os
import time

from PySide6.QtWidgets import QMessageBox

from it_toolbox.widgets.mbox_browser_widget import (
    ATTACHMENT_ROLE,
    SUMMARY_ROLE,
    MboxBrowserWidget,
    _safe_filename,
    write_attachment_for_opening,
)


def _make_widget(qtbot, path):
    widget = MboxBrowserWidget(path)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000) as blocker:
        pass
    return widget, blocker.args[0]


def _visible_subjects(widget):
    items = [widget._list.topLevelItem(i) for i in range(widget._list.topLevelItemCount())]
    return sorted(i.data(0, SUMMARY_ROLE).subject for i in items if not i.isHidden())


def test_lists_messages_newest_first(qtbot, sample_mbox, tmp_path):
    widget, count = _make_widget(qtbot, sample_mbox())

    assert count == 5
    assert widget._list.topLevelItemCount() == 5
    assert widget._list.topLevelItem(0).text(2) == "Café news"
    assert widget._list.topLevelItem(4).text(2) == "No date"
    assert widget._count_label.text() == "5 messages"
    assert widget._search_edit.isEnabled()


def test_header_search_filters_as_you_type(qtbot, sample_mbox, tmp_path):
    widget, _ = _make_widget(qtbot, sample_mbox())

    widget._search_edit.setText("ALICE")
    assert _visible_subjects(widget) == ["Server down"]
    assert widget._count_label.text() == "1 of 5 messages"

    widget._search_edit.setText("raid")
    assert _visible_subjects(widget) == []

    widget._search_edit.clear()
    assert len(_visible_subjects(widget)) == 5


def test_body_search_runs_in_background(qtbot, sample_mbox, tmp_path):
    widget, _ = _make_widget(qtbot, sample_mbox())

    widget._bodies_check.setChecked(True)
    widget._search_edit.setText("raid array")
    qtbot.waitUntil(lambda: _visible_subjects(widget) == ["Disk alert"], timeout=5000)
    assert widget._count_label.text() == "1 of 5 messages"


def test_stale_body_search_result_is_dropped(qtbot, sample_mbox, tmp_path):
    widget, _ = _make_widget(qtbot, sample_mbox())
    widget._search_generation = 5

    widget._on_body_search_done({123}, 4, mbox_browser_widget.status_bar.StatusTask(None, ""))

    assert widget._body_matches == set()


def test_selecting_a_message_shows_preview_and_attachments(qtbot, sample_mbox, tmp_path):
    widget, _ = _make_widget(qtbot, sample_mbox())
    item = next(
        widget._list.topLevelItem(i)
        for i in range(5)
        if widget._list.topLevelItem(i).text(2) == "Invoice"
    )

    widget._list.setCurrentItem(item)
    qtbot.waitUntil(lambda: widget._attachments.count() == 1, timeout=5000)

    assert "Subject: Invoice" in widget._headers_label.text()
    assert widget._body_view.toPlainText().strip() == "See attached."
    assert "invoice.pdf" in widget._attachments.item(0).text()


def test_saving_an_attachment(qtbot, sample_mbox, tmp_path, monkeypatch):
    widget, _ = _make_widget(qtbot, sample_mbox())
    item = next(
        widget._list.topLevelItem(i)
        for i in range(5)
        if widget._list.topLevelItem(i).text(2) == "Invoice"
    )
    widget._list.setCurrentItem(item)
    qtbot.waitUntil(lambda: widget._attachments.count() == 1, timeout=5000)
    destination = tmp_path / "saved.pdf"
    monkeypatch.setattr(
        mbox_browser_widget.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )

    widget._save_attachment(widget._attachments.item(0).data(ATTACHMENT_ROLE))
    qtbot.waitUntil(destination.exists, timeout=5000)

    assert destination.read_bytes() == b"%PDF-1.4 fake"


def test_unreadable_file_reports_error(qtbot, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        mbox_browser_widget.QMessageBox, "warning", lambda *args: warnings.append(args)
    )

    widget, count = _make_widget(qtbot, tmp_path / "missing.mbox")

    assert count == -1
    assert warnings and warnings[0][1] == "Couldn't open mbox file"
    assert not widget._search_edit.isEnabled()


def test_progress_panel_hides_once_loaded(qtbot, sample_mbox):
    widget, _ = _make_widget(qtbot, sample_mbox())

    assert widget._progress_panel.isHidden()
    assert not widget._progress_timer.isActive()


def test_progress_panel_shows_scan_then_message_counts(qtbot, tmp_path):
    widget = MboxBrowserWidget(tmp_path / "missing.mbox")
    qtbot.addWidget(widget)
    widget._closed = True  # keep the (failing) background load quiet

    widget._load_progress = ("scanning", 512, 2048)
    widget._update_load_progress()
    assert widget._progress_label.text() == "Scanning missing.mbox…"
    assert (widget._progress_bar.maximum(), widget._progress_bar.value()) == (100, 25)

    widget._load_progress = ("reading", 1200, 50000)
    widget._update_load_progress()
    assert widget._progress_label.text() == "Reading messages: 1,200 of 50,000"
    assert (widget._progress_bar.maximum(), widget._progress_bar.value()) == (50000, 1200)


def test_closing_during_load_cancels_the_index(qtbot, sample_mbox):
    widget = MboxBrowserWidget(sample_mbox())
    qtbot.addWidget(widget)

    widget.close_session()

    with qtbot.assertNotEmitted(widget.loaded, wait=500):
        pass
    assert widget._reader is None


def _select_invoice(qtbot, widget):
    item = next(
        widget._list.topLevelItem(i)
        for i in range(5)
        if widget._list.topLevelItem(i).text(2) == "Invoice"
    )
    widget._list.setCurrentItem(item)
    qtbot.waitUntil(lambda: widget._attachments.count() == 1, timeout=5000)


def test_double_clicking_an_attachment_opens_a_temp_copy(
    qtbot, sample_mbox, tmp_path, monkeypatch
):
    monkeypatch.setattr(mbox_browser_widget, "OPENED_ATTACHMENTS_DIR", tmp_path / "opened")
    opened = []
    monkeypatch.setattr(
        mbox_browser_widget.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
    )
    widget, _ = _make_widget(qtbot, sample_mbox())
    _select_invoice(qtbot, widget)

    widget._on_attachment_activated(widget._attachments.item(0))
    qtbot.waitUntil(lambda: bool(opened), timeout=5000)

    path = opened[0].toLocalFile()
    assert path.endswith("invoice.pdf")
    assert path.startswith(str(tmp_path / "opened"))
    assert open(path, "rb").read() == b"%PDF-1.4 fake"


def test_executable_attachment_asks_before_opening(qtbot, sample_mbox, monkeypatch):
    from it_toolbox.core.mbox_reader import Attachment

    asked = []
    monkeypatch.setattr(
        mbox_browser_widget.QMessageBox,
        "question",
        lambda *args: asked.append(args) or QMessageBox.StandardButton.Cancel,
    )
    widget, _ = _make_widget(qtbot, sample_mbox())
    started = []
    monkeypatch.setattr(
        mbox_browser_widget.async_utils, "run_in_background", lambda *a, **k: started.append(a)
    )
    widget._current_key = 0

    widget._open_attachment(Attachment(0, "invoice.PDF.exe", "application/octet-stream", 3))

    assert "will run it" in asked[0][2].replace("\n", " ")
    assert started == []


def test_write_attachment_for_opening_sweeps_old_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(mbox_browser_widget, "OPENED_ATTACHMENTS_DIR", tmp_path)
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

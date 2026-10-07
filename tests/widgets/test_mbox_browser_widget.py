from it_toolbox.widgets import mbox_browser_widget
from it_toolbox.widgets.mbox_browser_widget import SUMMARY_ROLE, MboxBrowserWidget


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

    widget._on_attachment_activated(widget._attachments.item(0))
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

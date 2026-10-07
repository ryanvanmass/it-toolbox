from it_toolbox.widgets import eml_viewer_widget
from it_toolbox.widgets.eml_viewer_widget import EmlViewerWidget


def _make_widget(qtbot, path):
    widget = EmlViewerWidget(path)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000) as blocker:
        pass
    return widget, blocker.args[0]


def test_shows_the_message(qtbot, sample_eml):
    widget, ok = _make_widget(qtbot, sample_eml())

    assert ok
    assert "Subject: Invoice" in widget._view._headers_label.text()
    assert widget._view._body_view.toPlainText().strip() == "See attached."
    assert "invoice.pdf" in widget._view._attachments.item(0).text()
    assert widget._view._attachment_source(0) == b"%PDF-1.4 fake"


def test_unreadable_file_reports_error(qtbot, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        eml_viewer_widget.QMessageBox, "warning", lambda *args: warnings.append(args)
    )

    widget, ok = _make_widget(qtbot, tmp_path / "missing.eml")

    assert not ok
    assert warnings and warnings[0][1] == "Couldn't open .eml file"
    assert widget._view._body_view.toPlainText().startswith("Couldn't read this message")


def test_closing_during_load_drops_the_result(qtbot, sample_eml):
    widget = EmlViewerWidget(sample_eml())
    qtbot.addWidget(widget)

    widget.close_session()

    with qtbot.assertNotEmitted(widget.loaded, wait=500):
        pass

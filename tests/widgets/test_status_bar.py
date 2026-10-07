from PySide6.QtWidgets import QMainWindow, QWidget

from it_toolbox.widgets import status_bar


def _window_with_child(qtbot):
    window = QMainWindow()
    child = QWidget()
    window.setCentralWidget(child)
    window.statusBar().showMessage("Ready")
    qtbot.addWidget(window)
    return window, child


def test_begin_shows_message_and_finish_shows_result(qtbot):
    window, child = _window_with_child(qtbot)

    task = status_bar.begin(child, "Uploading a.txt…")
    assert window.statusBar().currentMessage() == "Uploading a.txt…"

    task.finish("Uploaded a.txt")
    assert window.statusBar().currentMessage() == "Uploaded a.txt"


def test_finish_without_message_returns_to_ready(qtbot):
    window, child = _window_with_child(qtbot)

    status_bar.begin(child, "Loading…").finish()

    assert window.statusBar().currentMessage() == "Ready"


def test_finish_message_reverts_to_ready_after_timeout(qtbot, monkeypatch):
    monkeypatch.setattr(status_bar, "FINISH_MESSAGE_MS", 10)
    window, child = _window_with_child(qtbot)

    status_bar.begin(child, "Deleting x…").finish("Deleted x")

    qtbot.waitUntil(lambda: window.statusBar().currentMessage() == "Ready", timeout=2000)


def test_overlapping_tasks_keep_the_still_running_one_visible(qtbot):
    window, child = _window_with_child(qtbot)

    upload = status_bar.begin(child, "Uploading big.iso…")
    listing = status_bar.begin(child, "Loading gdrive:…")
    listing.finish()
    assert window.statusBar().currentMessage() == "Uploading big.iso…"

    upload.finish("Uploaded big.iso")
    assert window.statusBar().currentMessage() == "Uploaded big.iso"


def test_finish_twice_is_harmless(qtbot):
    window, child = _window_with_child(qtbot)

    task = status_bar.begin(child, "Loading…")
    task.finish()
    task.finish("ignored")

    assert window.statusBar().currentMessage() == "Ready"


def test_no_main_window_is_a_noop(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)

    task = status_bar.begin(widget, "Loading…")
    task.finish("Done")

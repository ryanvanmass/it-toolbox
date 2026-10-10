from PySide6.QtWidgets import QMainWindow, QProgressBar, QWidget

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


def _progress_bar(window):
    return window.statusBar().findChild(QProgressBar, status_bar.PROGRESS_BAR_NAME)


def test_set_progress_shows_bar_with_percentage_until_finished(qtbot):
    window, child = _window_with_child(qtbot)
    window.show()

    task = status_bar.begin(child, "Downloading big.iso…")
    task.set_progress(42)
    bar = _progress_bar(window)
    assert bar.isVisible()
    assert bar.value() == 42
    assert bar.text() == "42%"

    task.finish("Downloaded big.iso")
    assert not bar.isVisible()


def test_progress_bar_follows_latest_task_with_progress(qtbot):
    window, child = _window_with_child(qtbot)
    window.show()

    first = status_bar.begin(child, "Downloading a…")
    first.set_progress(10)
    second = status_bar.begin(child, "Downloading b…")
    second.set_progress(80)
    status_bar.begin(child, "Loading gdrive:…")  # no progress; bar keeps b
    bar = _progress_bar(window)
    assert bar.value() == 80

    second.finish()
    assert bar.isVisible() and bar.value() == 10


def test_set_progress_after_finish_is_ignored(qtbot):
    window, child = _window_with_child(qtbot)
    window.show()

    task = status_bar.begin(child, "Downloading a…")
    task.finish()
    task.set_progress(50)

    bar = _progress_bar(window)
    assert bar is None or not bar.isVisible()


def test_set_progress_without_main_window_is_a_noop(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    status_bar.begin(widget, "Downloading a…").set_progress(50)

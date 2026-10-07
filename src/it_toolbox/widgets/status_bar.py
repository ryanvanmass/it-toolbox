"""Bottom-left status bar messages for background work, so an operation
that has no window of its own (rclone runs with no console since the
no_window_kwargs change) still shows that something is happening.

    task = status_bar.begin(self, "Uploading report.pdf to gdrive…")
    ...
    task.finish("Uploaded report.pdf")  # shown briefly, then back to "Ready"

Several operations can be in flight at once (an upload in one tab, a
listing in another): the bar shows the most recently started one still
running, and only falls back to a finish message or "Ready" once nothing
is left. A task that knows how far it's got can also drive a progress
bar with a percentage at the bar's right edge:

    task.set_progress(42)

The bar follows the most recently started running task that has
reported progress, and hides once none has. Every call is a no-op where there's no main window (standalone
widgets, most tests).
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QProgressBar, QStatusBar, QWidget

IDLE_MESSAGE = "Ready"
FINISH_MESSAGE_MS = 5000
PROGRESS_BAR_NAME = "itToolboxStatusProgress"


def _find_status_bar(widget: QWidget) -> QStatusBar | None:
    window = widget.window()
    if isinstance(window, QMainWindow):
        return window.statusBar()
    # A widget built before it's been put in a tab (e.g. a browser loading
    # its first listing from __init__) has no main window ancestor yet.
    for top_level in QApplication.topLevelWidgets():
        if isinstance(top_level, QMainWindow):
            return top_level.statusBar()
    return None


def _running(status_bar: QStatusBar) -> list["StatusTask"]:
    if not hasattr(status_bar, "_it_toolbox_tasks"):
        status_bar._it_toolbox_tasks = []
    return status_bar._it_toolbox_tasks


class StatusTask:
    def __init__(self, status_bar: QStatusBar | None, message: str) -> None:
        self._status_bar = status_bar
        self.message = message
        self.progress: int | None = None
        self._finished = False

    def set_progress(self, percent: int) -> None:
        """Shows this task's progress (0-100) in the status bar's progress
        bar. Safe to call after finish() or after the window is gone."""
        if self._finished or self._status_bar is None:
            return
        self.progress = max(0, min(100, int(percent)))
        try:
            _update_progress_bar(self._status_bar)
        except RuntimeError:
            pass  # window torn down before the operation finished

    def finish(self, message: str = "") -> None:
        """Takes this task off the bar, showing `message` for a few seconds
        if nothing else is still running. Safe to call more than once and
        after the window is gone."""
        if self._finished or self._status_bar is None:
            return
        self._finished = True
        status_bar = self._status_bar
        try:
            running = _running(status_bar)
            if self in running:
                running.remove(self)
            _update_progress_bar(status_bar)
            if running:
                status_bar.showMessage(running[-1].message)
                return
            status_bar.showMessage(message or IDLE_MESSAGE)
        except RuntimeError:
            return  # window torn down before the operation finished
        if message:
            QTimer.singleShot(
                FINISH_MESSAGE_MS, status_bar, lambda: _reset_if_idle(status_bar, message)
            )


def _progress_bar(status_bar: QStatusBar) -> QProgressBar:
    bar = status_bar.findChild(QProgressBar, PROGRESS_BAR_NAME)
    if bar is None:
        bar = QProgressBar()
        bar.setObjectName(PROGRESS_BAR_NAME)
        bar.setRange(0, 100)
        bar.setFormat("%p%")
        bar.setMaximumWidth(200)
        bar.hide()
        # Permanent (right-hand) rather than a normal widget, which
        # showMessage() would cover up.
        status_bar.addPermanentWidget(bar)
    return bar


def _update_progress_bar(status_bar: QStatusBar) -> None:
    with_progress = [task for task in _running(status_bar) if task.progress is not None]
    bar = _progress_bar(status_bar)
    if not with_progress:
        bar.hide()
        return
    task = with_progress[-1]
    bar.setValue(task.progress)
    bar.setToolTip(task.message)
    bar.show()


def _reset_if_idle(status_bar: QStatusBar, message: str) -> None:
    if not _running(status_bar) and status_bar.currentMessage() == message:
        status_bar.showMessage(IDLE_MESSAGE)


def begin(widget: QWidget, message: str) -> StatusTask:
    """Shows `message` in the main window's status bar until the returned
    task is finished."""
    status_bar = _find_status_bar(widget)
    task = StatusTask(status_bar, message)
    if status_bar is not None:
        _running(status_bar).append(task)
        status_bar.showMessage(message)
    return task

"""Suite-wide safety nets for the Qt tests.

Background: widgets report failed background calls with a blocking, modal
``QMessageBox.warning(...)``. Headless, nothing ever dismisses that dialog,
so a call that fails unexpectedly during a test (a mock that was already
undone, a real network/CLI call nobody mocked, a bug in a test double) does
not fail the test -- it hangs, or aborts the whole pytest process with
"double free or corruption" from inside ``QDialog::exec``. The two fixtures
below turn both failure modes into ordinary, attributable test failures.
"""

import pytest
from PySide6.QtCore import QCoreApplication, QThreadPool
from PySide6.QtWidgets import QMessageBox

_STATIC_DIALOGS = ("warning", "critical", "information", "question", "about")


@pytest.fixture(autouse=True)
def _forbid_unmocked_message_boxes(monkeypatch):
    """Fail the test instead of opening a real modal dialog nobody can close.

    A test that expects a dialog patches it itself (e.g.
    ``monkeypatch.setattr(module.QMessageBox, "warning", ...)``); that later
    patch takes precedence over this one.
    """

    def _make(kind):
        def _unexpected(parent, title, text="", *args, **kwargs):
            raise AssertionError(
                f"Unexpected blocking QMessageBox.{kind}({title!r}, {str(text)!r}) -- "
                "mock the call that failed, or patch QMessageBox if the dialog is expected."
            )

        return staticmethod(_unexpected)

    for kind in _STATIC_DIALOGS:
        monkeypatch.setattr(QMessageBox, kind, _make(kind))


@pytest.fixture(autouse=True)
def _drain_background_tasks(monkeypatch):
    """Let in-flight ``async_utils.run_in_background`` tasks finish, and
    deliver their results, before this test's mocks are undone.

    Otherwise a task the test never waited for can run *after*
    ``monkeypatch`` restores the real function, hit the real thing (no
    rclone binary, the real JumpCloud API, ...), and report the failure into
    whichever later test happens to be running.

    Requesting ``monkeypatch`` here makes it set up before -- and so tear
    down after -- this fixture, which is what guarantees that ordering.
    """
    yield
    if QCoreApplication.instance() is None:
        return  # a non-Qt test; no worker tasks can be in flight
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(3):  # queued cross-thread results arrive one loop pass later
        QCoreApplication.processEvents()

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

# Keeps runnables alive until their result/error has actually been delivered.
# Removal happens only from _cleanup() below, which — because it's invoked
# via a signal connection rather than called directly from run() — is always
# dispatched on the main thread. See the note in _FunctionRunnable for why
# that matters.
_active_runnables: set["_FunctionRunnable"] = set()

# These tasks are I/O-bound (network calls, gcloud subprocesses), not CPU
# work, so a bigger pool than Qt's CPU-count-based default is cheap and
# avoids one slow/stuck task queuing up everything behind it (e.g. expanding
# several tree nodes in a large GCP org while one project is unresponsive).
QThreadPool.globalInstance().setMaxThreadCount(16)


class _WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(Exception)


class _FunctionRunnable(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _WorkerSignals()
        # QThreadPool's default autoDelete() destroys this QRunnable itself
        # right after run() returns — from the worker thread. That's fine
        # for the QRunnable, but self.signals is a QObject whose thread
        # affinity is the main thread (it's constructed here, in
        # run_in_background(), which only ever runs on the main thread) —
        # and Qt requires a QObject to be destroyed on the thread it belongs
        # to. Letting Qt's C++ side tear this down from the worker thread is
        # a cross-thread QObject deletion: undefined behavior that can
        # silently drop the pending result (looks like a permanent hang) or
        # crash natively with no Python traceback. Managing the lifetime
        # ourselves via _active_runnables, and only ever releasing it from a
        # main-thread-dispatched slot, keeps every teardown on the right
        # thread.
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001 - reported to caller, not swallowed
            self._emit_safely(self.signals.error, exc)
        else:
            self._emit_safely(self.signals.result, result)

    def _emit_safely(self, signal: Signal, value: Any) -> None:
        # The receiving widget (or the whole app) can be torn down while this
        # was still running in the background — that's not an error case for
        # the caller, just a delivery that no longer has anywhere to go.
        try:
            signal.emit(value)
        except RuntimeError:
            pass


def run_in_background(
    fn: Callable[[], Any],
    on_result: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    """Run `fn` on a Qt thread-pool thread; deliver the outcome back on the
    calling (Qt main) thread via queued signal connections.
    """
    runnable = _FunctionRunnable(fn)

    def cleanup_and_call(callback: Callable[[Any], None] | None, value: Any) -> None:
        # Runs on the main thread — see _FunctionRunnable.__init__.
        _active_runnables.discard(runnable)
        if callback is not None:
            callback(value)

    runnable.signals.result.connect(lambda value: cleanup_and_call(on_result, value))
    runnable.signals.error.connect(lambda error: cleanup_and_call(on_error, error))

    _active_runnables.add(runnable)
    QThreadPool.globalInstance().start(runnable)

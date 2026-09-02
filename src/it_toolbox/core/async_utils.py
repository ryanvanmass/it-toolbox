from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

# Keeps runnables alive for the duration of run() — without this, nothing
# holds a Python reference to a runnable once run_in_background() returns,
# and it can be garbage-collected mid-execution.
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

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001 - reported to caller, not swallowed
            self._emit_safely(self.signals.error, exc)
        else:
            self._emit_safely(self.signals.result, result)
        finally:
            _active_runnables.discard(self)

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
    if on_result is not None:
        runnable.signals.result.connect(on_result)
    if on_error is not None:
        runnable.signals.error.connect(on_error)
    _active_runnables.add(runnable)
    QThreadPool.globalInstance().start(runnable)

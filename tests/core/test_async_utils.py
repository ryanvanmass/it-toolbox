import time

from it_toolbox.core import async_utils


def test_run_in_background_delivers_result_on_main_thread(qtbot):
    results = []

    def slow_call():
        time.sleep(0.01)
        return 42

    async_utils.run_in_background(slow_call, on_result=results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=2000)

    assert results == [42]


def test_run_in_background_delivers_error(qtbot):
    errors = []

    def failing_call():
        raise ValueError("boom")

    async_utils.run_in_background(failing_call, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=2000)

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)


def test_many_concurrent_background_calls_all_complete_without_crashing(qtbot):
    """Regression test for a cross-thread QObject-deletion bug: QThreadPool's
    default autoDelete() destroyed each task's signal-emitting QObject from
    the worker thread instead of its own (main) thread, which could silently
    drop results or crash natively. Firing many of these back-to-back is
    what actually surfaced it — a single call in isolation usually "worked".
    """
    N = 200
    completed = []

    def make_call(i):
        return lambda: i * 2

    for i in range(N):
        async_utils.run_in_background(make_call(i), on_result=completed.append)

    qtbot.waitUntil(lambda: len(completed) == N, timeout=10000)

    assert sorted(completed) == [i * 2 for i in range(N)]
    assert async_utils._active_runnables == set()

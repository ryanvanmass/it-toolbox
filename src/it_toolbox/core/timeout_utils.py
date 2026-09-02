import concurrent.futures
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_with_timeout(fn: Callable[[], T], timeout: float) -> T:
    """Run fn() and hard-enforce a wall-clock timeout.

    Google's client libraries have their own internal retry/deadline
    policies that a `timeout=` kwarg doesn't always fully bound — this
    guarantees the caller gets control back within `timeout` seconds
    regardless. If fn() is still running when that elapses, the call is
    abandoned (Python can't forcibly kill a running thread) and a
    concurrent.futures.TimeoutError is raised.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(fn)
        return future.result(timeout=timeout)
    finally:
        executor.shutdown(wait=False)

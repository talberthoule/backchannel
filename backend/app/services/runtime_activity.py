import threading
import time
from contextlib import contextmanager


class ShutdownReserved(RuntimeError):
    pass


_lock = threading.Lock()
_active: dict[str, int] = {}
_shutdown_deadline: float | None = None


def _expire_shutdown() -> None:
    global _shutdown_deadline
    if _shutdown_deadline is not None and time.monotonic() >= _shutdown_deadline:
        _shutdown_deadline = None


@contextmanager
def track(name: str):
    with _lock:
        _expire_shutdown()
        if _shutdown_deadline is not None:
            raise ShutdownReserved("Update installation is starting.")
        _active[name] = _active.get(name, 0) + 1
    try:
        yield
    finally:
        with _lock:
            remaining = _active[name] - 1
            if remaining:
                _active[name] = remaining
            else:
                del _active[name]


def request_tracker(name: str):
    async def dependency():
        with track(name):
            yield

    return dependency


def busy_reason() -> str:
    with _lock:
        _expire_shutdown()
        if _active:
            return next(iter(_active))
        return "update installation" if _shutdown_deadline is not None else ""


def reserve_shutdown(timeout_seconds: int = 60) -> bool:
    global _shutdown_deadline
    with _lock:
        _expire_shutdown()
        if _active or _shutdown_deadline is not None:
            return False
        _shutdown_deadline = time.monotonic() + timeout_seconds
        return True


def release_shutdown() -> None:
    global _shutdown_deadline
    with _lock:
        _shutdown_deadline = None

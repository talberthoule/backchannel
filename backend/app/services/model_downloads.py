"""Visible state for the model weights the app fetches on first use.

The PII Shield's NER model and the local ASR models are hundreds of megabytes
that arrive from the Hugging Face hub the first time something needs them.
Before this module that happened silently inside a request: a slow link looked
like a hang, and a failure looked like the feature quietly not working
(ALP-373). Every fetch now registers here, so the browser can say what is
queued, what is downloading and how far along, and what failed and why.

The registry is process-wide and thread-safe. Producers call `claim` to take
single-flight ownership of a key, then `begin`/`advance`/`finish`/`fail`; the
`download` context manager does that bookkeeping for the common case.
Consumers read `snapshot`.

Nothing here performs a download or knows how one works. Keeping the state
separate from the fetching is what lets both the hub path (which reports exact
byte totals through a tqdm shim) and the onnx-asr path (which reports polled
directory growth) describe themselves the same way.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from app.services import std_streams

# Anything that downloads may write to stdout/stderr; make sure they exist.
std_streams.ensure()

# A download is in exactly one of these states.
QUEUED = "queued"
DOWNLOADING = "downloading"
INSTALLED = "installed"
ERROR = "error"


class _Job:
    __slots__ = ("key", "label", "purpose", "state", "downloaded", "total", "error", "at")

    def __init__(self, key: str, label: str, purpose: str):
        self.key = key
        self.label = label
        self.purpose = purpose
        self.state = QUEUED
        self.downloaded = 0
        self.total = 0
        self.error = ""
        self.at = time.time()

    def as_dict(self) -> dict:
        percent: int | None = None
        if self.total > 0:
            percent = max(0, min(100, round(self.downloaded * 100 / self.total)))
        return {
            "key": self.key,
            "label": self.label,
            "purpose": self.purpose,
            "state": self.state,
            "downloaded": self.downloaded,
            "total": self.total,
            "percent": percent,
            "error": self.error,
            "updated_at": self.at,
        }


_lock = threading.Lock()
_jobs: dict[str, _Job] = {}


def claim(key: str, label: str, purpose: str = "") -> bool:
    """Take ownership of `key`, or return False if a fetch is already running.

    Single-flight: the second caller does not queue behind the first, it walks
    away. A download is never something to wait in line for.
    """
    with _lock:
        existing = _jobs.get(key)
        if existing is not None and existing.state in (QUEUED, DOWNLOADING):
            return False
        _jobs[key] = _Job(key, label, purpose)
        return True


def begin(key: str, total: int = 0) -> None:
    with _lock:
        job = _jobs.get(key)
        if job is None:
            return
        job.state = DOWNLOADING
        if total:
            job.total = total
        job.at = time.time()


def advance(key: str, downloaded: int, total: int = 0) -> None:
    """Report absolute bytes fetched so far (not a delta)."""
    with _lock:
        job = _jobs.get(key)
        if job is None:
            return
        job.state = DOWNLOADING
        job.downloaded = max(job.downloaded, int(downloaded))
        if total:
            job.total = int(total)
        job.at = time.time()


def finish(key: str) -> None:
    with _lock:
        job = _jobs.get(key)
        if job is None:
            return
        job.state = INSTALLED
        job.error = ""
        if job.total:
            job.downloaded = job.total
        job.at = time.time()


def fail(key: str, message: str) -> None:
    with _lock:
        job = _jobs.get(key)
        if job is None:
            job = _Job(key, key, "")
            _jobs[key] = job
        job.state = ERROR
        job.error = message[:400]
        job.at = time.time()


def forget(key: str) -> None:
    """Drop a job so a retry starts from a clean slate."""
    with _lock:
        _jobs.pop(key, None)


def get(key: str) -> dict | None:
    with _lock:
        job = _jobs.get(key)
        return job.as_dict() if job else None


def is_running(key: str) -> bool:
    with _lock:
        job = _jobs.get(key)
        return bool(job and job.state in (QUEUED, DOWNLOADING))


def snapshot() -> dict:
    """Everything the browser needs to describe downloads in one read."""
    with _lock:
        jobs = [job.as_dict() for job in _jobs.values()]
    jobs.sort(key=lambda j: j["updated_at"], reverse=True)
    return {
        "downloads": jobs,
        "active": sum(1 for j in jobs if j["state"] in (QUEUED, DOWNLOADING)),
        "failed": sum(1 for j in jobs if j["state"] == ERROR),
    }


def reset() -> None:
    """Clear every job. Tests only."""
    with _lock:
        _jobs.clear()


@contextmanager
def download(key: str, label: str, purpose: str = ""):
    """Mark `key` downloading for the block, then installed, or failed on error.

    Assumes the caller already won `claim`. Re-raises whatever went wrong after
    recording it, so callers keep their own error handling.
    """
    begin(key)
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
        fail(key, f"{type(exc).__name__}: {exc}")
        raise
    else:
        finish(key)


class ProgressReporter:
    """A tqdm stand-in that reports into the registry and writes nowhere.

    `huggingface_hub.hf_hub_download` takes a public `tqdm_class`, so this is
    the supported way to watch a hub download without patching internals.

    Writing nowhere is the point, not a side effect. Real tqdm renders to
    `sys.stderr`, which is None in the frozen desktop build, and `tqdm.clear`
    and `tqdm.refresh` take tqdm's process-global write lock *before* touching
    that stream and release it only on the line after. The AttributeError from
    `None.write` therefore escapes with the global lock still held, and the
    next progress bar anywhere in the process blocks on it forever. That is
    what wedged session creation in v0.6.1 (ALP-373). This class holds no
    locks, touches no stream, and cannot fail that way.
    """

    # Set by `reporter_for` on the bound subclass.
    registry_key = ""
    registry_base = 0
    registry_total = 0

    def __init__(self, *args, key: str = "", **kwargs):
        cls = type(self)
        self._key = key or cls.registry_key
        self._base = cls.registry_base
        # One registry entry can span several files; when the caller knows the
        # combined size, report against that rather than the current file.
        self._reported_total = cls.registry_total or (kwargs.get("total") or 0)
        self.total = kwargs.get("total") or 0
        self.n = kwargs.get("initial") or 0
        self.disable = False
        self._report()

    def _report(self) -> None:
        if self._key:
            advance(self._key, self._base + self.n, self._reported_total)

    # tqdm surface used by huggingface_hub.
    def update(self, n: int = 1) -> None:
        self.n += n or 0
        self._report()

    def update_transfer(self, n: int = 1) -> None:
        """Xet's second counter; the bytes are already counted by `update`."""
        return None

    def close(self) -> None:
        return None

    def reset(self, total: int | None = None) -> None:
        self.n = 0
        if total is not None:
            self.total = total

    @property
    def format_dict(self) -> dict:
        return {"n": self.n, "total": self.total, "elapsed": 0}

    def __getattr__(self, name: str):
        """Anything else tqdm offers becomes a no-op.

        Deliberate. huggingface_hub reaches for a moving set of bar methods
        (`set_postfix_str`, `set_transfer_postfix_str`, `update_progress`, and
        whatever a future version adds), all of them display concerns this
        class has no business having. Raising AttributeError from inside a
        download is the failure mode this whole class exists to prevent, so an
        unknown attribute answers with a callable that does nothing rather than
        breaking the transfer over a progress bar.
        """
        # Our own attributes are never routed here; a miss means a real bug.
        if name.startswith("_"):
            raise AttributeError(name)

        def _noop(*args, **kwargs):
            return None

        return _noop

    def __enter__(self) -> "ProgressReporter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __iter__(self):
        return iter(())


def reporter_for(key: str, *, base: int = 0, total: int = 0) -> type[ProgressReporter]:
    """A `tqdm_class` bound to one registry key.

    `base` is bytes already fetched by earlier files in the same job and
    `total` the job's combined size, so a multi-file download reports one
    continuous bar instead of restarting at zero for every file.
    """
    return type(
        "BoundProgressReporter",
        (ProgressReporter,),
        {"registry_key": key, "registry_base": base, "registry_total": total},
    )

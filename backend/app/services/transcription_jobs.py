"""In-process progress for long audio transcription work."""

from dataclasses import dataclass, field
import uuid


ACTIVE_STATUSES = {"queued", "running", "canceling"}


class JobAlreadyRunning(RuntimeError):
    pass


class JobCanceled(RuntimeError):
    pass


@dataclass
class TranscriptionJob:
    session_id: uuid.UUID
    kind: str
    model_id: str
    total_segments: int
    filename: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "queued"
    segments_done: int = 0
    entries: int = 0
    error: str = ""
    cancel_requested: bool = False

    def snapshot(self) -> dict:
        progress = 100 if self.status == "completed" else round(
            self.segments_done * 100 / max(1, self.total_segments)
        )
        return {
            "job_id": str(self.id),
            "kind": self.kind,
            "status": self.status,
            "model_id": self.model_id,
            "segments_done": self.segments_done,
            "total_segments": self.total_segments,
            "entries": self.entries,
            "progress": progress,
            "filename": self.filename,
            "error": self.error,
        }

    def check_canceled(self) -> None:
        if self.cancel_requested:
            raise JobCanceled()

    def start(self) -> None:
        self.check_canceled()
        self.status = "running"

    def update_entries(self, entries: int) -> None:
        self.entries = entries

    def finish_segment(self, entries: int) -> None:
        self.entries = entries
        self.segments_done += 1

    def complete(self) -> None:
        self.status = "completed"
        self.segments_done = self.total_segments

    def fail(self, message: str) -> None:
        self.status = "failed"
        self.error = message

    def cancel(self) -> None:
        if self.status in ACTIVE_STATUSES:
            self.cancel_requested = True
            self.status = "canceling"

    def mark_canceled(self) -> None:
        self.status = "canceled"


# ponytail: one process owns the desktop API; persist jobs if multi-worker or
# restart recovery becomes a requirement.
_jobs: dict[uuid.UUID, TranscriptionJob] = {}


def create_job(
    session_id: uuid.UUID,
    kind: str,
    model_id: str,
    total_segments: int,
    *,
    filename: str | None = None,
) -> TranscriptionJob:
    current = _jobs.get(session_id)
    if current and current.status in ACTIVE_STATUSES:
        raise JobAlreadyRunning(f"A {current.kind.replace('_', ' ')} job is already running")
    job = TranscriptionJob(
        session_id=session_id,
        kind=kind,
        model_id=model_id,
        total_segments=max(1, total_segments),
        filename=filename,
    )
    _jobs[session_id] = job
    return job


def get_job(
    session_id: uuid.UUID,
    *,
    kind: str | None = None,
    job_id: uuid.UUID | None = None,
) -> TranscriptionJob | None:
    job = _jobs.get(session_id)
    if not job or (kind and job.kind != kind) or (job_id and job.id != job_id):
        return None
    return job

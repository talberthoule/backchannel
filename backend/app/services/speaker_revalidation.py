import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

REVALIDATION_BATCH_SIZE = 25


def _value(source: Any, field: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(field, default)
    return getattr(source, field, default)


def canonical_speaker_mapping(speakers: Iterable[Any]) -> list[dict]:
    fields = (
        "id",
        "name",
        "role",
        "speaker_type",
        "is_user",
        "display_name",
        "display_name_enabled",
    )
    snapshot = [
        {
            field: str(_value(speaker, field))
            if field == "id"
            else _value(speaker, field)
            for field in fields
        }
        for speaker in speakers
    ]
    return sorted(snapshot, key=lambda speaker: speaker["id"])


def _hash_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def mapping_hash(mapping: Iterable[dict]) -> str:
    return _hash_json(sorted(mapping, key=lambda speaker: speaker["id"]))


def content_version(
    session: Any,
    questions: Iterable[Any],
    transcript_entries: Iterable[Any],
) -> str:
    question_fields = (
        "id",
        "question",
        "rationale",
        "source_context",
        "speaker_id",
        "dismissed",
        "answered",
        "answer_summary",
        "revision_count",
    )
    transcript_fields = ("id", "sequence", "text", "speaker_id")

    def rows(items: Iterable[Any], fields: tuple[str, ...]) -> list[dict]:
        result = [
            {field: _value(item, field) for field in fields}
            for item in items
        ]
        return sorted(result, key=lambda item: str(item["id"]))

    return _hash_json(
        {
            "meeting_type": _value(session, "meeting_type", "general"),
            "meeting_context": _value(session, "meeting_context", ""),
            "questions": rows(questions, question_fields),
            "transcript": rows(transcript_entries, transcript_fields),
        }
    )


def build_batch_specs(
    question_ids: list[str],
    batch_size: int = REVALIDATION_BATCH_SIZE,
) -> list[tuple[str, list[str]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    batches = [
        ("insights", question_ids[index:index + batch_size])
        for index in range(0, len(question_ids), batch_size)
    ]
    return [*batches, ("briefing", [])]


def requeue_failed_batches(run: Any, batches: Iterable[Any]) -> int:
    retried = 0
    for batch in batches:
        if batch.status != "failed":
            continue
        batch.status = "queued"
        batch.error_message = ""
        batch.started_at = None
        batch.completed_at = None
        retried += 1
    run.status = "running"
    run.error_message = ""
    run.completed_at = None
    return retried


def finalize_run_state(
    run: Any,
    batches: Iterable[Any],
    session: Any,
    mapping_revision: Any,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    batches = list(batches)
    failed = sum(batch.status == "failed" for batch in batches)
    run.completed_at = now
    if failed:
        run.status = "partial"
        run.error_message = f"{failed} revalidation batch{'es' if failed != 1 else ''} failed."
        session.speaker_context_dirty = True
        return

    run.status = "completed"
    if session.speaker_context_version == mapping_revision.source_version:
        session.speaker_context_dirty = False
        session.speaker_context_enhanced_at = now
        run.error_message = ""
    else:
        session.speaker_context_dirty = True
        run.error_message = (
            "Speaker context changed again while this revision was running."
        )


def summarize_run(run: Any, session: Any, now: datetime | None = None) -> dict:
    batches = list(run.batches)
    completed = sum(batch.status == "completed" for batch in batches)
    failed = sum(batch.status == "failed" for batch in batches)
    end = run.completed_at or now or datetime.now(timezone.utc)
    duration_ms = (
        max(0, int((end - run.started_at).total_seconds() * 1000))
        if run.started_at
        else 0
    )
    briefing = next((batch for batch in batches if batch.kind == "briefing"), None)
    briefing_status = None
    if briefing:
        briefing_status = {
            "completed": "completed",
            "failed": "error",
        }.get(briefing.status, "pending")

    return {
        "status": run.status,
        "run_id": run.id,
        "mapping_revision": run.mapping_revision.source_version,
        "content_version": run.content_version,
        "total_batches": len(batches),
        "completed_batches": completed,
        "failed_batches": failed,
        "failure_rate": failed / len(batches) if batches else 0.0,
        "processed_entries": sum(batch.processed_entries for batch in batches),
        "applied_operations": sum(batch.applied_operations for batch in batches),
        "enhanced_insights": sum(batch.enhanced_insights for batch in batches),
        "input_tokens": sum(batch.input_tokens for batch in batches),
        "output_tokens": sum(batch.output_tokens for batch in batches),
        "total_tokens": sum(batch.total_tokens for batch in batches),
        "duration_ms": duration_ms,
        "speaker_context_dirty": session.speaker_context_dirty,
        "speaker_context_enhanced_at": session.speaker_context_enhanced_at,
        "briefing_updated": bool(
            briefing and briefing.status == "completed"
        ),
        "briefing_status": briefing_status,
        "error": run.error_message or None,
        "batches": [
            {
                "id": batch.id,
                "index": batch.batch_index,
                "kind": batch.kind,
                "status": batch.status,
                "attempts": batch.attempts,
                "processed_entries": batch.processed_entries,
                "duration_ms": batch.duration_ms,
                "input_tokens": batch.input_tokens,
                "output_tokens": batch.output_tokens,
                "total_tokens": batch.total_tokens,
                "error": batch.error_message or None,
            }
            for batch in batches
        ],
    }

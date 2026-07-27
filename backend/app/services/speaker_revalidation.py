import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models import (
    Question,
    Session,
    SessionSynthesis,
    Speaker,
    SpeakerMappingRevision,
    SpeakerRevalidationBatch,
    SpeakerRevalidationRun,
    TokenUsage,
    TranscriptEntry,
)
from app.services.briefing_synthesis import run_session_synthesis
from app.services.custom_endpoints import endpoint_models
from app.services.privacy import (
    LocalOnlyModeError,
    admitted_model_ids,
    get_local_only,
)
from app.services.speaker_context_enhancer import run_speaker_context_batch

REVALIDATION_BATCH_SIZE = 25
logger = logging.getLogger(__name__)

_QUOTA_MARKERS = (
    "resource_exhausted",
    "spending cap",
    "quota",
    "rate limit",
    "too many requests",
)
_AUTH_MARKERS = (
    "api key",
    "api_key",
    "unauthenticated",
    "unauthorized",
    "permission_denied",
    "permission denied",
)
# Status codes must match as standalone numbers; a bare substring check would
# misclassify unrelated digit runs like "timed out after 14290 ms".
_QUOTA_CODE = re.compile(r"\b429\b")
_AUTH_CODE = re.compile(r"\b(?:401|403)\b")
_GOOGLE_MARKERS = ("gemini", "google", "generativelanguage", "ai studio")
# A transient rate limit usually clears in seconds; a spending cap or exhausted
# quota does not. The retry loop only re-tries the same model for the former, so
# it never wastes attempts on a wall that will not move before the fallback.
_RATE_LIMIT_MARKERS = ("rate limit", "too many requests")
_HARD_CAP_MARKERS = ("resource_exhausted", "spending cap", "quota")
_RATE_LIMIT_RETRY_DELAYS = (0.5, 2.0)


def is_quota_error(error: Exception | str) -> bool:
    """A provider quota exhaustion or rate limit (HTTP 429 or a quota marker)."""
    lowered = str(error).lower()
    return any(marker in lowered for marker in _QUOTA_MARKERS) or bool(
        _QUOTA_CODE.search(lowered)
    )


def is_rate_limit_error(error: Exception | str) -> bool:
    """The transient subset of quota errors: a rate limit, not a hard cap.

    A bare 429 with no spending-cap or resource-exhausted wording is treated as
    a transient rate limit worth retrying; an explicit hard cap is not.
    """
    lowered = str(error).lower()
    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return True
    if _QUOTA_CODE.search(lowered) and not any(
        marker in lowered for marker in _HARD_CAP_MARKERS
    ):
        return True
    return False


def batch_failure_reason(error: Exception | str) -> str:
    """Convert a batch failure into a short, actionable human-readable reason.

    Recognizes provider quota and auth errors from the exception text (and, for
    exceptions, the raising module); anything else keeps the first line of the
    original message so the real detail is not lost. The quota remedy leads with
    assigning a self-hosted model, because that is the durable fix for a cloud
    quota wall; raising the cap stays as the secondary option.
    """
    text = str(error).strip()
    lowered = text.lower()
    module = type(error).__module__ if isinstance(error, Exception) else ""
    from_google = module.startswith("google") or any(
        marker in lowered for marker in _GOOGLE_MARKERS
    )
    if is_quota_error(error):
        if from_google:
            return (
                "Gemini quota/spending cap exhausted. Assign a self-hosted model "
                "in Admin -> Agents (any on-prem endpoint), or raise the cap in "
                "AI Studio."
            )
        return (
            "Model provider quota or rate limit exhausted. Assign a self-hosted "
            "model in Admin -> Agents (any on-prem endpoint), or raise the limit "
            "in the provider console."
        )
    if any(marker in lowered for marker in _AUTH_MARKERS) or _AUTH_CODE.search(lowered):
        return (
            "The model provider rejected the API key - update it in "
            "Admin -> Connections."
        )
    if not text:
        return "Revalidation batch failed unexpectedly."
    first_line = text.splitlines()[0].strip()
    return first_line if len(first_line) <= 200 else first_line[:197] + "..."


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
        run.status = "failed" if failed == len(batches) else "partial"
        summary = f"{failed} revalidation batch{'es' if failed != 1 else ''} failed."
        reason = next(
            (
                batch.error_message
                for batch in batches
                if batch.status == "failed" and batch.error_message
            ),
            "",
        )
        run.error_message = f"{summary} {reason}".strip()
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


async def start_or_resume_revalidation(
    session_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[SpeakerRevalidationRun, bool]:
    session = (await db.execute(
        select(Session).where(Session.id == session_id).with_for_update()
    )).scalar_one()
    speakers = list((await db.execute(
        select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
    )).scalars())
    questions = list((await db.execute(
        select(Question).where(Question.session_id == session_id).order_by(Question.created_at)
    )).scalars())
    transcripts = list((await db.execute(
        select(TranscriptEntry)
        .where(TranscriptEntry.session_id == session_id)
        .order_by(TranscriptEntry.sequence)
    )).scalars())

    mapping = canonical_speaker_mapping(speakers)
    revision = (await db.execute(
        select(SpeakerMappingRevision).where(
            SpeakerMappingRevision.session_id == session_id,
            SpeakerMappingRevision.source_version == session.speaker_context_version,
        )
    )).scalar_one_or_none()
    if not revision:
        revision = SpeakerMappingRevision(
            session_id=session_id,
            source_version=session.speaker_context_version,
            mapping_hash=mapping_hash(mapping),
            mapping_snapshot=mapping,
        )
        db.add(revision)
        await db.flush()

    run = (await db.execute(
        select(SpeakerRevalidationRun)
        .where(
            SpeakerRevalidationRun.session_id == session_id,
            SpeakerRevalidationRun.mapping_revision_id == revision.id,
        )
        .options(selectinload(SpeakerRevalidationRun.batches))
        .order_by(SpeakerRevalidationRun.created_at.desc())
    )).scalars().first()
    if run and run.status in {"partial", "failed"}:
        requeue_failed_batches(run, run.batches)
        await db.commit()
        return await get_revalidation_run(run.id, db), True
    if run:
        return await get_revalidation_run(run.id, db), False

    run = SpeakerRevalidationRun(
        session_id=session_id,
        mapping_revision_id=revision.id,
        content_version=content_version(session, questions, transcripts),
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()
    for index, (kind, item_ids) in enumerate(
        build_batch_specs([str(question.id) for question in questions])
    ):
        db.add(SpeakerRevalidationBatch(
            run_id=run.id,
            batch_index=index,
            kind=kind,
            item_ids=item_ids,
        ))
    await db.commit()
    return await get_revalidation_run(run.id, db), True


async def get_revalidation_run(
    run_id: uuid.UUID,
    db: AsyncSession,
) -> SpeakerRevalidationRun | None:
    return (await db.execute(
        select(SpeakerRevalidationRun)
        .where(SpeakerRevalidationRun.id == run_id)
        .options(
            selectinload(SpeakerRevalidationRun.batches),
            selectinload(SpeakerRevalidationRun.mapping_revision),
        )
    )).scalar_one_or_none()


async def run_revalidation(run_id: uuid.UUID) -> None:
    async with async_session() as db:
        run = await get_revalidation_run(run_id, db)
        if not run:
            return
        session = await db.get(Session, run.session_id)

        for batch in run.batches:
            if batch.status != "queued":
                continue
            if batch.kind == "briefing" and any(
                prior.kind == "insights" and prior.status != "completed"
                for prior in run.batches
            ):
                break
            await _run_batch(db, run, batch)

        await db.refresh(run, attribute_names=["batches", "mapping_revision"])
        finalize_run_state(run, run.batches, session, run.mapping_revision)
        await db.commit()


async def select_fallback_models(
    primary_model_id: str,
    db: AsyncSession,
    local_only: bool,
) -> list[str]:
    """Admitted self-hosted text models to try when the primary is unavailable.

    The durable answer to a cloud quota wall - or to Privacy First refusing the
    configured cloud model - is a model that has neither problem: a self-hosted
    OpenAI-compatible endpoint on this machine or the LAN. Bundled local models
    are ASR-only (no text), so on-prem endpoint models are the only local text
    option. On-prem endpoints come first; a non-on-prem endpoint is a candidate
    only when Privacy First is off. Admission is decided by the shared
    allows_local_only helper (ALP-152) so the destination guarantee holds, and
    the exhausted primary is never offered back to itself.
    """
    models = await endpoint_models(db)
    on_prem = [m["id"] for m in models if m.get("runs_locally") and m.get("supports_text")]
    off_prem = [m["id"] for m in models if not m.get("runs_locally") and m.get("supports_text")]
    ordered = on_prem + ([] if local_only else off_prem)
    candidates = [model_id for model_id in ordered if model_id != primary_model_id]
    admitted = await admitted_model_ids(candidates, local_only)
    return [model_id for model_id in candidates if model_id in admitted]


def _should_try_fallback(error: Exception) -> bool:
    """Whether another model is worth trying for this failure.

    A quota wall or a Privacy First refusal of the configured cloud model both
    mean this model cannot do the work, which a self-hosted model can. Any other
    error - a bad key, a malformed reply, a real bug - is not fixed by switching
    models, so it propagates and the batch fails as before.
    """
    return is_quota_error(error) or isinstance(error, LocalOnlyModeError)


async def _enhance_insights_with_fallback(
    db: AsyncSession,
    session_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    mapping_revision_id: uuid.UUID,
) -> dict:
    """Run one insight batch, retrying a rate limit and falling back a model.

    The configured refinement model is tried first, with a short backoff for a
    transient rate limit. If it is quota-blocked or refused by Privacy First,
    each admitted self-hosted model is tried in turn. The generate_text call
    happens before any database write in run_speaker_context_batch, so a failed
    attempt leaves nothing applied and the next model starts clean. Raises the
    last error when no model could complete the batch, so the caller marks the
    batch failed with the usual reworded reason.
    """
    primary = settings.REFINEMENT_MODEL
    local_only = await get_local_only(db)
    models = [primary, *await select_fallback_models(primary, db, local_only)]
    last_error: Exception | None = None
    for model_id in models:
        for delay in (0.0, *_RATE_LIMIT_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                metrics = await run_speaker_context_batch(
                    session_id, item_ids, mapping_revision_id, db, model_id=model_id
                )
                if model_id != primary:
                    logger.info(
                        "Insight revalidation used fallback model %s after %s was unavailable",
                        model_id,
                        primary,
                    )
                return metrics
            except Exception as error:
                last_error = error
                if not _should_try_fallback(error):
                    raise
                if is_rate_limit_error(error):
                    continue  # brief backoff, same model
                break  # hard cap or privacy refusal - move to the next model
    assert last_error is not None
    raise last_error


async def _run_batch(
    db: AsyncSession,
    run: SpeakerRevalidationRun,
    batch: SpeakerRevalidationBatch,
) -> None:
    started = datetime.now(timezone.utc)
    batch.status = "running"
    batch.attempts += 1
    batch.started_at = started
    batch.error_message = ""
    await db.commit()
    try:
        if batch.kind == "insights":
            metrics = await _enhance_insights_with_fallback(
                db,
                run.session_id,
                [uuid.UUID(item_id) for item_id in batch.item_ids],
                run.mapping_revision_id,
            )
            batch.processed_entries = metrics["processed_entries"]
            batch.applied_operations = metrics["applied_operations"]
            batch.enhanced_insights = metrics["enhanced_insights"]
        else:
            synthesis = await run_session_synthesis(run.session_id, mode="post_call")
            if not synthesis or synthesis.status != "completed":
                raise RuntimeError("Briefing revalidation did not complete")
            stored = await db.get(SessionSynthesis, synthesis.id)
            stored.speaker_mapping_revision_id = run.mapping_revision_id

        completed = datetime.now(timezone.utc)
        usage = (await db.execute(
            select(
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
            ).where(
                TokenUsage.session_id == run.session_id,
                TokenUsage.source.in_(
                    ["speaker_context_enhancer"]
                    if batch.kind == "insights"
                    else ["brief_meeting_lens", "brief_discovery_lens", "brief_arbiter"]
                ),
                TokenUsage.created_at >= started,
                TokenUsage.created_at <= completed,
            )
        )).one()
        batch.input_tokens, batch.output_tokens, batch.total_tokens = usage
        batch.duration_ms = max(0, int((completed - started).total_seconds() * 1000))
        batch.completed_at = completed
        batch.status = "completed"
        await db.commit()
    except Exception as exc:
        await db.rollback()
        failed = await db.get(SpeakerRevalidationBatch, batch.id)
        failed.status = "failed"
        failed.error_message = batch_failure_reason(exc)
        failed.duration_ms = max(
            0,
            int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        )
        failed.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.exception("Speaker revalidation batch %s failed", batch.id)

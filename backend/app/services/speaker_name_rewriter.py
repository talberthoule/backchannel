import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Question, Speaker


INSIGHT_SPEAKER_TEXT_FIELDS = (
    "question",
    "rationale",
    "source_context",
    "answer_summary",
    "followup_question",
    "enrichment_notes",
    "offering_match",
)


def speaker_effective_name(speaker: Any) -> str:
    display_name = str(_value(speaker, "display_name") or "").strip()
    if display_name and bool(_value(speaker, "display_name_enabled")):
        return display_name
    return str(_value(speaker, "name") or "Unknown").strip() or "Unknown"


def build_speaker_label_replacements(
    speakers: Iterable[Any],
    extra_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    replacements: dict[str, str] = {}

    for speaker in speakers:
        original = str(_value(speaker, "name") or "").strip()
        effective = speaker_effective_name(speaker)
        if original and effective and original.casefold() != effective.casefold():
            replacements[original] = effective

    for source, target in (extra_aliases or {}).items():
        source = str(source or "").strip()
        target = str(target or "").strip()
        if source and target and source.casefold() != target.casefold():
            replacements[source] = target

    return replacements


def replace_speaker_labels(text: str, replacements: dict[str, str]) -> str:
    if not text or not replacements:
        return text

    updated = text
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        updated = pattern.sub(target, updated)
    return updated


def rewrite_question_speaker_labels(
    question: Question,
    replacements: dict[str, str],
    *,
    now: datetime | None = None,
    enhanced: bool = False,
    note: str | None = None,
) -> bool:
    changed_fields: list[str] = []

    for field in INSIGHT_SPEAKER_TEXT_FIELDS:
        current = getattr(question, field, "") or ""
        updated = replace_speaker_labels(current, replacements)
        if updated != current:
            setattr(question, field, updated)
            changed_fields.append(field)

    if not changed_fields:
        return False

    timestamp = now or datetime.now(timezone.utc)
    question.updated_at = timestamp
    question.revision_count = (question.revision_count or 0) + 1
    if enhanced:
        question.enhanced = True

    suffix = f" ({', '.join(changed_fields)})"
    _append_note(question, note or f"Applied corrected speaker names{suffix}.")
    return True


async def rewrite_session_insight_speaker_labels(
    db: AsyncSession,
    session_id: uuid.UUID,
    speakers: Iterable[Speaker | dict],
    *,
    now: datetime | None = None,
    enhanced: bool = True,
) -> set[str]:
    replacements = build_speaker_label_replacements(speakers)
    return await rewrite_session_insight_labels_with_replacements(
        db,
        session_id,
        replacements,
        now=now,
        enhanced=enhanced,
    )


async def rewrite_session_insight_labels_with_replacements(
    db: AsyncSession,
    session_id: uuid.UUID,
    replacements: dict[str, str],
    *,
    now: datetime | None = None,
    enhanced: bool = False,
    note: str | None = None,
) -> set[str]:
    if not replacements:
        return set()

    result = await db.execute(select(Question).where(Question.session_id == session_id))
    questions = list(result.scalars().all())
    changed_ids: set[str] = set()
    timestamp = now or datetime.now(timezone.utc)

    for question in questions:
        if rewrite_question_speaker_labels(
            question,
            replacements,
            now=timestamp,
            enhanced=enhanced,
            note=note,
        ):
            changed_ids.add(str(question.id))

    return changed_ids


def _value(source: Any, field: str) -> Any:
    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)


def _append_note(question: Question, note: str):
    if not note:
        return
    existing = question.enrichment_notes or ""
    if existing:
        question.enrichment_notes = f"{existing}\n{note}"
    else:
        question.enrichment_notes = note

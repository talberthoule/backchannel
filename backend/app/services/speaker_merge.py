import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Question, Speaker, TranscriptEntry
from app.services.speaker_name_rewriter import (
    build_speaker_label_replacements,
    rewrite_session_insight_labels_with_replacements,
    speaker_effective_name,
)


class SpeakerMergeError(ValueError):
    pass


@dataclass(frozen=True)
class SpeakerMergeResult:
    source_speaker_id: uuid.UUID
    target_speaker_id: uuid.UUID
    transcript_entries_updated: int
    questions_updated: int


async def merge_speakers(
    db: AsyncSession,
    session_id: uuid.UUID,
    source_speaker_id: uuid.UUID,
    target_speaker_id: uuid.UUID,
) -> SpeakerMergeResult:
    """Merge a detected speaker fragment into another speaker for the same session."""
    if source_speaker_id == target_speaker_id:
        raise SpeakerMergeError("Source and target speakers must be different")

    source = await db.get(Speaker, source_speaker_id)
    target = await db.get(Speaker, target_speaker_id)
    if not source or source.session_id != session_id:
        raise SpeakerMergeError("Source speaker not found")
    if not target or target.session_id != session_id:
        raise SpeakerMergeError("Target speaker not found")

    transcript_result = await db.execute(
        update(TranscriptEntry)
        .where(
            TranscriptEntry.session_id == session_id,
            TranscriptEntry.speaker_id == source_speaker_id,
        )
        .values(speaker_id=target_speaker_id)
    )
    question_result = await db.execute(
        update(Question)
        .where(
            Question.session_id == session_id,
            Question.speaker_id == source_speaker_id,
        )
        .values(speaker_id=target_speaker_id)
    )

    _preserve_source_profile(source, target)
    target_label = speaker_effective_name(target)
    replacements = build_speaker_label_replacements(
        [target],
        extra_aliases={
            source.name: target_label,
            speaker_effective_name(source): target_label,
        },
    )
    await rewrite_session_insight_labels_with_replacements(
        db,
        session_id,
        replacements,
        now=datetime.now(timezone.utc),
        enhanced=True,
        note="Updated insight text after speaker merge.",
    )
    await db.delete(source)
    await db.commit()

    return SpeakerMergeResult(
        source_speaker_id=source_speaker_id,
        target_speaker_id=target_speaker_id,
        transcript_entries_updated=_rowcount(transcript_result),
        questions_updated=_rowcount(question_result),
    )


def _preserve_source_profile(source: Speaker, target: Speaker):
    if source.is_user:
        target.is_user = True
        target.speaker_type = "team"
    if source.speaker_type == "team" and target.speaker_type != "team":
        target.speaker_type = "team"
    if source.role and not target.role:
        target.role = source.role
    if source.display_name and not target.display_name:
        target.display_name = source.display_name
        target.display_name_enabled = source.display_name_enabled


def _rowcount(result: object) -> int:
    count = getattr(result, "rowcount", 0)
    return count if isinstance(count, int) else 0

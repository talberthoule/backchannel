import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.services.llm import generate_text
from app.database import async_session
from app.models import Question, Session, Speaker, TranscriptEntry
from app.services.agents.speaker_context import (
    format_speaker_context,
    format_transcript_segment,
    speaker_display_name,
)
from app.services.insight_refiner import _apply_operations
from app.services.meeting_context import build_meeting_context_text
from app.services.speaker_name_rewriter import rewrite_session_insight_speaker_labels

logger = logging.getLogger(__name__)

CONTEXT_CHANGE_FIELDS = {"name", "display_name", "display_name_enabled", "speaker_type", "is_user"}

ENHANCEMENT_PROMPT_TEMPLATE = """You are re-evaluating a completed conversation after speaker context was corrected.

The user may have renamed speakers, merged duplicate detected speakers, or corrected whether a speaker is an internal participant or an external participant.

## Meeting Context
{meeting_context_text}

Your job:
- Ingest the current insights and the full transcript.
- Use the corrected speaker roster and transcript speaker metadata.
- Identify insights that should change because a statement was misattributed or because team/external context changes the interpretation.
- Mark every created, modified, or dismissed insight as enhanced by returning `"enhanced": true` in each operation.

Critical interpretation rules:
- `speaker_type=team` means an internal speaker from the user's organization.
- `speaker_type=external` means outside the internal team; use Meeting Context to decide whether they are a client, vendor, partner, candidate, or other participant.
- Do not treat external statements as client evidence unless the Meeting Context or transcript supports that.
- Do not change the item_type/category/tag of an existing insight. Enhancement should add corrected context, adjusted text, dismissal state, or a new enhanced insight, while preserving the original tag on existing items.
- If an opportunity was based only on a team-member summary, do not convert the existing opportunity into another type. Dismiss it if it is unsupported, enrich/adjust it if the corrected context still supports it, or create a separate enhanced question/observation if useful.
- If an insight is clearly bad, stale, duplicative, or no longer supported after corrected speaker context, dismiss it.
- Do not touch dismissed insights.

## Corrected Speakers
{speakers_text}

## Current Insights
{insights_json}

## Full Transcript
{transcript_text}

## Output Format
Return a JSON array of operation objects. If nothing should change, return `[]`.

Operations:
{{"op": "answer", "id": "<insight-uuid>", "answer_summary": "what we learned", "needs_followup": true/false, "followup": "next question if needed", "enhanced": true}}
{{"op": "enrich", "id": "<insight-uuid>", "additional_context": "new supporting evidence from corrected context", "reason": "why this matters", "enhanced": true}}
{{"op": "adjust", "id": "<insight-uuid>", "new_text": "updated insight text", "new_rationale": "updated rationale", "new_source_context": "updated source context", "reason": "what changed after speaker correction", "enhanced": true}}
{{"op": "dismiss", "id": "<insight-uuid>", "reason": "why corrected speaker context makes this insight bad, stale, duplicative, or unsupported", "enhanced": true}}
{{"op": "create", "item_type": "question|observation|opportunity|action_item", "question": "the insight text", "rationale": "why this matters", "source_context": "what was said", "enhanced": true}}
{{"op": "merge", "keep_id": "<uuid-to-keep>", "remove_id": "<uuid-to-remove>", "merged_text": "combined text", "reason": "why these are the same", "enhanced": true}}

Return ONLY valid JSON array, no other text.
"""


def _value(source: Any, field: str) -> Any:
    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)


def speaker_update_changes_enhancement_context(speaker: Any, updates: dict[str, Any]) -> bool:
    for field in CONTEXT_CHANGE_FIELDS:
        if field in updates and updates[field] != _value(speaker, field):
            return True
    return False


async def mark_speaker_context_dirty_if_completed(db: AsyncSession, session_id: uuid.UUID) -> bool:
    session = await db.get(Session, session_id)
    if not session or session.state != "completed":
        return False
    session.speaker_context_dirty = True
    return True


def build_enhancement_prompt(
    speakers: list[dict],
    insights: list[dict],
    transcript_lines: list[dict],
    meeting_context_text: str | None = None,
) -> str:
    speakers_text = "\n".join(format_speaker_context(speaker) for speaker in speakers) or "(No speaker information)"
    insights_json = json.dumps(insights, indent=2)
    transcript_text = "\n".join(
        format_transcript_segment(
            line.get("text", ""),
            line.get("speaker_name"),
            speaker_id=line.get("speaker_id"),
            speaker_type=line.get("speaker_type"),
        )
        for line in transcript_lines
    ) or "(No transcript)"

    return ENHANCEMENT_PROMPT_TEMPLATE.format(
        meeting_context_text=meeting_context_text or build_meeting_context_text(),
        speakers_text=speakers_text,
        insights_json=insights_json,
        transcript_text=transcript_text,
    )


async def run_speaker_context_enhancement(session_id: uuid.UUID) -> dict:
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if not session:
            raise ValueError("Session not found")
        meeting_context_text = build_meeting_context_text(session)

        speakers_result = await db.execute(
            select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
        )
        speakers = [_speaker_dict(speaker) for speaker in speakers_result.scalars().all()]

        questions_result = await db.execute(
            select(Question)
            .where(Question.session_id == session_id)
            .options(selectinload(Question.speaker))
            .order_by(Question.created_at)
        )
        questions = list(questions_result.scalars().all())

        transcript_result = await db.execute(
            select(TranscriptEntry)
            .where(TranscriptEntry.session_id == session_id)
            .options(selectinload(TranscriptEntry.speaker))
            .order_by(TranscriptEntry.sequence)
        )
        transcript_entries = list(transcript_result.scalars().all())

        prompt = build_enhancement_prompt(
            speakers=speakers,
            insights=[_insight_dict(question) for question in questions],
            transcript_lines=[_transcript_dict(entry) for entry in transcript_entries],
            meeting_context_text=meeting_context_text,
        )

    try:
        raw = await generate_text(settings.REFINEMENT_MODEL, prompt)
    except Exception as exc:
        logger.error(f"[speaker_context_enhancer] API call failed: {exc}")
        changed_ids = await _rewrite_speaker_labels(session_id, speakers)
        return {
            "applied_operations": len(changed_ids),
            "enhanced_insights": len(changed_ids),
            "speaker_context_dirty": True,
            "speaker_context_enhanced_at": None,
        }

    ops = _parse_ops(raw)
    applied = await _apply_operations(
        session_id,
        ops,
        questions,
        agent_source="speaker_context_enhancer",
        enhanced=True,
    )

    enhanced_ids = {
        op.get("id") or op.get("keep_id")
        for op in applied
        if op.get("applied") and (op.get("id") or op.get("keep_id"))
    }
    for op in applied:
        ws_data = op.get("ws_data")
        if isinstance(ws_data, dict) and ws_data.get("id"):
            enhanced_ids.add(ws_data["id"])

    now = datetime.now(timezone.utc)
    replacement_ids = await _rewrite_speaker_labels(session_id, speakers, now=now)
    enhanced_ids.update(replacement_ids)

    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session:
            session.speaker_context_dirty = False
            session.speaker_context_enhanced_at = now
            await db.commit()

    return {
        "applied_operations": len(applied) + len(replacement_ids),
        "enhanced_insights": len(enhanced_ids),
        "speaker_context_dirty": False,
        "speaker_context_enhanced_at": now,
    }


async def _rewrite_speaker_labels(
    session_id: uuid.UUID,
    speakers: list[dict],
    now: datetime | None = None,
) -> set[str]:
    async with async_session() as db:
        changed_ids = await rewrite_session_insight_speaker_labels(
            db,
            session_id,
            speakers,
            now=now,
            enhanced=True,
        )
        if changed_ids:
            await db.commit()
        return changed_ids


def _speaker_dict(speaker: Speaker) -> dict:
    return {
        "id": str(speaker.id),
        "name": speaker.name,
        "role": speaker.role,
        "speaker_type": speaker.speaker_type,
        "display_name": speaker.display_name,
        "display_name_enabled": speaker.display_name_enabled,
    }


def _insight_dict(question: Question) -> dict:
    return {
        "id": str(question.id),
        "item_type": question.item_type,
        "question": question.question,
        "rationale": question.rationale,
        "source_context": question.source_context,
        "speaker_id": str(question.speaker_id) if question.speaker_id else None,
        "speaker": format_speaker_context(_speaker_dict(question.speaker)) if question.speaker else None,
        "dismissed": question.dismissed,
        "answered": question.answered,
        "answer_summary": question.answer_summary,
        "enhanced": question.enhanced,
        "agent_source": question.agent_source,
    }


def _transcript_dict(entry: TranscriptEntry) -> dict:
    speaker = _speaker_dict(entry.speaker) if entry.speaker else None
    return {
        "text": entry.text,
        "speaker_name": speaker_display_name(speaker) if speaker else "Unknown",
        "speaker_id": str(entry.speaker_id) if entry.speaker_id else None,
        "speaker_type": speaker["speaker_type"] if speaker else None,
    }


def _parse_ops(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    if not raw or raw == "[]":
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            parsed = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return []
    return parsed if isinstance(parsed, list) else []

"""Synthesizer agent — meta-agent for cross-agent reconciliation.

Replaces the current insight_refiner.py refinement loop with enhanced
cross-agent deduplication and reconciliation capabilities.
"""

import json
import logging
import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.services.llm import generate_json
from app.database import async_session
from app.models import Question, Session, TranscriptEntry
from app.services.agents.prompts import PRINCIPAL_AGENT_PROMPT
from app.services.agents.speaker_context import format_speaker_context, format_transcript_segment
from app.services.insight_refiner import _apply_operations
from app.services.meeting_context import build_meeting_context_text, format_prompt_with_meeting_context

logger = logging.getLogger(__name__)

# Mirrors ASK_ITEM_TYPE in app.routers.ask (ALP-178). Redeclared here rather
# than imported to avoid a services -> routers dependency for one string.
ASKED_ITEM_TYPE = "asked"


class SynthesizerOperation(BaseModel):
    op: str
    id: str | None = None
    keep_id: str | None = None
    remove_id: str | None = None
    answer_summary: str | None = None
    needs_followup: bool | None = None
    followup: str | None = None
    additional_context: str | None = None
    reason: str | None = None
    new_type: str | None = None
    new_text: str | None = None
    new_rationale: str | None = None
    new_source_context: str | None = None
    new_answer_summary: str | None = None
    new_followup_question: str | None = None
    new_followup: str | None = None
    new_offering_match: str | None = None
    offering_match: str | None = None
    followup_question: str | None = None
    item_type: str | None = None
    question: str | None = None
    rationale: str | None = None
    source_context: str | None = None
    merged_text: str | None = None


class SynthesizerOutput(BaseModel):
    items: list[SynthesizerOperation]


def _build_insights_json(questions: list[Question]) -> str:
    items = []
    for q in questions:
        speaker = _speaker_dict(q.speaker) if q.speaker else None
        items.append({
            "id": str(q.id),
            "item_type": q.item_type,
            "text": q.question,
            "rationale": q.rationale,
            "source_context": q.source_context,
            "speaker_id": str(q.speaker_id) if q.speaker_id else None,
            "speaker": format_speaker_context(speaker) if speaker else None,
            "answered": q.answered,
            "answer_summary": q.answer_summary,
            "starred": q.starred,
            "enrichment_notes": q.enrichment_notes or "",
            "agent_source": q.agent_source,
        })
    return json.dumps(items, indent=2)


def _speaker_dict(speaker) -> dict:
    return {
        "id": str(speaker.id),
        "name": speaker.name,
        "role": speaker.role,
        "speaker_type": speaker.speaker_type,
        "display_name": speaker.display_name,
        "display_name_enabled": speaker.display_name_enabled,
    }


def _format_transcript_entries(entries: list[TranscriptEntry]) -> str:
    lines = []
    for entry in entries:
        speaker = _speaker_dict(entry.speaker) if entry.speaker else None
        lines.append(format_transcript_segment(
            entry.text,
            speaker.get("name") if speaker else "Unknown",
            speaker_id=str(entry.speaker_id) if entry.speaker_id else None,
            speaker_type=speaker.get("speaker_type") if speaker else None,
        ))
    return "\n".join(lines) if lines else "(No transcript yet)"


async def run_synthesizer_cycle(session_id: uuid.UUID, model_override: str | None = None, prompt_override: str | None = None) -> list[dict]:
    """Execute one synthesizer cycle. Returns list of applied operations."""
    async with async_session() as db:
        session = await db.get(Session, session_id)
        meeting_context_text = build_meeting_context_text(session)

        result = await db.execute(
            select(Question).where(
                Question.session_id == session_id,
                Question.dismissed.is_(False),
                # The operator's own live-chat Q&A is a private read, not
                # agent material: excluded so the Principal Agent cannot
                # dismiss, adjust, or elevate an answer it did not produce.
                Question.item_type != ASKED_ITEM_TYPE,
            ).options(selectinload(Question.speaker))
        )
        questions = list(result.scalars().all())

        if not questions:
            return []

        # Load recent transcript (~5 min window)
        result = await db.execute(
            select(TranscriptEntry)
            .where(TranscriptEntry.session_id == session_id)
            .options(selectinload(TranscriptEntry.speaker))
            .order_by(TranscriptEntry.sequence.desc())
            .limit(30)
        )
        entries = list(reversed(result.scalars().all()))

    transcript_text = _format_transcript_entries(entries)
    insights_json = _build_insights_json(questions)

    prompt_template = prompt_override or PRINCIPAL_AGENT_PROMPT
    prompt = format_prompt_with_meeting_context(
        prompt_template,
        meeting_context_text,
        insights_json=insights_json,
        transcript_text=transcript_text,
    )

    model_id = model_override or settings.REFINEMENT_MODEL

    try:
        output = await generate_json(
            model_id,
            prompt,
            SynthesizerOutput,
            session_id=session_id,
            source="synthesizer",
        )
    except Exception as e:
        logger.error(f"[synthesizer] API call failed: {e}")
        return []

    ops = [item.model_dump(exclude_unset=True) for item in output.items]
    applied = await _apply_operations(session_id, ops, questions, agent_source="synthesizer")
    return applied

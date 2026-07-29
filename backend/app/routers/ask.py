"""Live in-call chat (ALP-178).

Deliberately separate from routers/chat.py: the post-call path is multi-session,
carries conversation history, and spends a large budget oldest-first. This one is
single-session, stateless, small-budget and newest-first, and it persists its
answer as an insight instead of returning a chat reply.
"""

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document, Question, Session, SessionSynthesis, Speaker, TranscriptEntry
from app.schemas import QuestionOut
from app.services.custom_endpoints import endpoint_model_entry
from app.services.live_chat_context import (
    LIVE_SYSTEM_PROMPT,
    build_live_prompt,
    format_live_insights,
)
from app.services.llm import generate_text, provider_for, registry_entry
from app.services.privacy import LocalOnlyModeError, allows_local_only, is_local_only
from app.services.provider_errors import PROVIDER_ERROR_TYPES, provider_error_to_http
from app.services.session_manager import get_active_directives

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["ask"])

ASK_ITEM_TYPE = "asked"
ASK_AGENT_SOURCE = "live_chat"
MAX_QUESTION_CHARS = 2000


class AskIn(BaseModel):
    model_id: str
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


def build_asked_row(
    session_id,
    question: str,
    answer: str,
    model_name: str = "",
    elapsed_seconds: float = 0.0,
) -> Question:
    """The persisted shape of an answered live question.

    Split out from the handler so the row contract is testable without a
    database or a provider call. The model and latency ride in `rationale`,
    which QuestionCard already renders, rather than earning a schema change for
    what is a caption.
    """
    return Question(
        session_id=session_id,
        item_type=ASK_ITEM_TYPE,
        question=question,
        rationale=f"Answered by {model_name} in {elapsed_seconds:.1f}s" if model_name else "",
        answer_summary=answer,
        answered=True,
        starred=True,
        agent_source=ASK_AGENT_SOURCE,
    )


async def load_live_context(session_id: uuid.UUID, db: AsyncSession) -> dict:
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, f"Session not found: {session_id}")

    speakers_result = await db.execute(select(Speaker).where(Speaker.session_id == session_id))
    speaker_names = {str(s.id): s.name for s in speakers_result.scalars().all()}

    entries_result = await db.execute(
        select(TranscriptEntry)
        .where(TranscriptEntry.session_id == session_id)
        .order_by(TranscriptEntry.sequence)
    )
    lines = [
        (speaker_names.get(str(e.speaker_id), "Unknown"), e.text)
        for e in entries_result.scalars().all()
    ]

    insights_result = await db.execute(
        select(Question)
        .where(
            Question.session_id == session_id,
            Question.dismissed.is_(False),
            Question.item_type != ASK_ITEM_TYPE,
        )
        .order_by(Question.created_at)
    )
    insights = insights_result.scalars().all()

    signals_result = await db.execute(
        select(SessionSynthesis).where(
            SessionSynthesis.session_id == session_id,
            SessionSynthesis.mode == "live",
        )
    )
    signals_row = signals_result.scalar_one_or_none()
    signals = "\n".join(
        f"- {s}" for s in (getattr(signals_row, "strategic_signals", None) or [])
    )

    documents_result = await db.execute(
        select(Document.filename).where(Document.session_id == session_id)
    )

    return {
        "name": session.name,
        "meeting_type": session.meeting_type or "general",
        "meeting_context": session.meeting_context or "",
        "directives": await get_active_directives(session_id, db),
        "document_filenames": list(documents_result.scalars().all()),
        "insights": format_live_insights(insights, speaker_names),
        "signals": signals,
        "lines": lines,
    }


@router.post("/{session_id}/ask", response_model=QuestionOut)
async def ask(session_id: uuid.UUID, body: AskIn, db: AsyncSession = Depends(get_db)):
    entry = registry_entry(body.model_id) or await endpoint_model_entry(db, body.model_id)
    if not entry or not entry.get("supports_text"):
        raise HTTPException(400, f"Model {body.model_id} does not support text generation")

    if await is_local_only() and not await allows_local_only(body.model_id):
        raise HTTPException(
            400, str(LocalOnlyModeError("asking the call a question", body.model_id))
        )

    context = await load_live_context(session_id, db)
    prompt = build_live_prompt(context, body.question)

    started = time.monotonic()
    try:
        answer = await generate_text(
            body.model_id,
            prompt,
            system=LIVE_SYSTEM_PROMPT,
            session_id=session_id,
            source=ASK_AGENT_SOURCE,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PROVIDER_ERROR_TYPES as e:
        raise provider_error_to_http(
            provider_for(body.model_id), e, context="Ask failed"
        ) from e

    row = build_asked_row(
        session_id,
        body.question,
        answer,
        model_name=entry.get("name") or body.model_id,
        elapsed_seconds=time.monotonic() - started,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Session, Speaker, TranscriptEntry
from app.services.llm import generate_text, registry_entry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

CONTEXT_BUDGET_CHARS = 60000
MAX_CHAT_HISTORY_MESSAGES = 8
MAX_CHAT_MESSAGE_CHARS = 8000

SYSTEM_PROMPT = (
    "You are a meeting analysis assistant. Use ONLY the supplied meeting "
    "briefings, saved insights, transcripts, and chat history. Begin from the "
    "briefing when deciding priorities, themes, outcomes, risks, and next steps. "
    "Use saved insights for supporting analysis and unresolved detail. Use the "
    "transcript as factual grounding and the only source for direct quotations. "
    "If sources conflict, identify the conflict and ground factual claims in the "
    "transcript. If the supplied context does not contain the answer, say so "
    "plainly. Format the response as concise GitHub-flavored Markdown with short "
    "headings, bullets, and tables only when they improve readability."
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)


class ChatIn(BaseModel):
    model_id: str
    session_ids: list[uuid.UUID]
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_HISTORY_MESSAGES)


def _layer_blocks(sessions_data: list[dict], key: str, remaining: int) -> tuple[str, int]:
    blocks: list[str] = []
    for data in reversed(sessions_data):
        if key == "transcript":
            content = "\n".join(f"{speaker}: {text}" for speaker, text in data["lines"])
        else:
            content = data.get(key, "").strip()
        if not content:
            continue

        block = f"## {data['name']} ({data['started_at']})\n{content}"
        if len(block) > remaining:
            marker = "\n[truncated]"
            keep = remaining - len(marker)
            block = (block[:keep] + marker) if keep > 100 else ""
        if block:
            blocks.insert(0, block)
            remaining -= len(block)
        if remaining <= 0:
            break
    return "\n\n".join(blocks), remaining


def build_chat_prompt(
    sessions_data: list[dict],
    messages: list[dict],
    budget: int = CONTEXT_BUDGET_CHARS,
) -> str:
    """Assemble brief-first meeting context plus bounded conversation history."""
    messages = messages[-MAX_CHAT_HISTORY_MESSAGES:]
    remaining = budget
    sections: list[str] = []
    for heading, key in (
        ("Meeting Briefings (primary context)", "briefing"),
        ("Saved Insights (supporting context)", "insights"),
        ("Meeting Transcripts (grounding evidence)", "transcript"),
    ):
        content, remaining = _layer_blocks(sessions_data, key, remaining)
        if content:
            sections.append(f"# {heading}\n\n{content}")
        if remaining <= 0:
            break

    conversation = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in messages)
    sections.append(f"# Conversation\n{conversation}\nAssistant:")
    return "\n\n".join(sections)


@router.post("")
async def chat(body: ChatIn, db: AsyncSession = Depends(get_db)):
    if not body.session_ids:
        raise HTTPException(400, "session_ids must not be empty")
    if not body.messages:
        raise HTTPException(400, "messages must not be empty")
    entry = registry_entry(body.model_id)
    if not entry or not entry.get("supports_text"):
        raise HTTPException(400, f"Model {body.model_id} does not support text generation")

    sessions_data = []
    for session_id in body.session_ids:
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
        started = session.started_at or session.created_at
        sessions_data.append({
            "name": session.name,
            "started_at": started.date().isoformat() if started else "unknown date",
            "lines": lines,
        })

    # Keep chronological order (oldest first) so truncation drops the oldest.
    prompt = build_chat_prompt(sessions_data, [m.model_dump() for m in body.messages])

    try:
        reply = await generate_text(body.model_id, prompt, system=SYSTEM_PROMPT)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"reply": reply}

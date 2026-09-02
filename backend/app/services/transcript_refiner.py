"""Transcript refinement over tokenized text.

Under the PII Shield the only thing that may hear audio is a local model,
and local transcripts are rougher than cloud ones: punctuation is thin,
casing is flat, and a product name comes out as two words. This stage sends
the *tokenized* text of recent entries to whichever text model the
``transcript_refiner`` agent is assigned, local or cloud, and writes back the
corrected wording. The model sees ``[PERSON_1]`` and ``[ORG_1]``; it never
sees the audio and never sees a name.

Safety is a rule, not a hope: a refined entry is accepted only if it carries
exactly the same multiset of tokens as the original and stays within a sane
length band. A model that drops, invents or renumbers a token loses that
entry and the original stands. The transcriber's text is kept in
``raw_text`` the first time an entry is refined.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Speaker, TranscriptEntry
from app.services.pii.vault import TOKEN_PATTERN

logger = logging.getLogger(__name__)

REFINER_SLUG = "transcript_refiner"
REFINER_SOURCE = "transcript_refiner"
# Entries a live cycle looks back over; the end-of-call pass takes them all.
REFINER_LIVE_WINDOW = 60

# Entries per model call. Enough for sentence context, small enough that one
# bad reply costs little.
DEFAULT_BATCH = 24
# Earlier entries shown for context only (never rewritten in that call).
CONTEXT_ENTRIES = 4

MIN_LENGTH_RATIO = 0.5
MAX_LENGTH_RATIO = 1.6

# Synthetic rows the live handler writes on a resume; not speech.
_MARKER_PREFIX = "--- Session Resumed"


class RefinedEntry(BaseModel):
    id: str = Field(description="The entry id exactly as given")
    text: str = Field(description="The corrected wording, tokens untouched")


class RefinementReply(BaseModel):
    entries: list[RefinedEntry] = Field(default_factory=list)


SYSTEM_PROMPT = (
    "You are a transcript editor. You receive lines of a meeting transcript "
    "produced by an automatic speech recognizer. Fix punctuation, sentence "
    "boundaries, capitalization, spacing, filler-word run-ons and obvious "
    "mishearings of common words and product names. Keep the meaning, the "
    "speaker's phrasing and the line boundaries. Bracketed placeholders such as "
    "[PERSON_1], [ORG_2] or [EMAIL_1] stand for redacted values: copy each one "
    "through exactly as written, never remove, add, renumber or paraphrase one."
)


def token_multiset(text: str) -> Counter:
    return Counter(m.group(0).strip("[]") for m in TOKEN_PATTERN.finditer(text or ""))


def accept_refinement(original: str, refined: str | None) -> bool:
    """True when ``refined`` may replace ``original``."""
    if not refined or not refined.strip():
        return False
    refined = refined.strip()
    if refined == original.strip():
        return False
    if token_multiset(original) != token_multiset(refined):
        return False
    ratio = len(refined) / max(len(original.strip()), 1)
    return MIN_LENGTH_RATIO <= ratio <= MAX_LENGTH_RATIO


def is_refinable(entry: TranscriptEntry) -> bool:
    text = (entry.text or "").strip()
    return bool(text) and not text.startswith(_MARKER_PREFIX) and entry.refined_at is None


def build_prompt(
    targets: list[tuple[str, str, str]],
    context: list[tuple[str, str]],
) -> str:
    """``targets`` are (id, speaker label, text); ``context`` (speaker, text)."""
    lines = []
    if context:
        lines.append("Earlier lines, for context only (do not return these):")
        lines.extend(f"  {speaker}: {text}" for speaker, text in context)
        lines.append("")
    lines.append("Lines to correct. Return every id with its corrected text:")
    lines.extend(f"  [{entry_id}] {speaker}: {text}" for entry_id, speaker, text in targets)
    return "\n".join(lines)


async def _speaker_labels(db: AsyncSession, session_id: uuid.UUID) -> dict[str, str]:
    rows = (await db.execute(select(Speaker).where(Speaker.session_id == session_id))).scalars().all()
    return {str(s.id): (s.display_name if s.display_name and s.display_name_enabled else s.name) for s in rows}


async def refine_batch(
    db: AsyncSession,
    session_id: uuid.UUID,
    model_id: str,
    entries: list[TranscriptEntry],
    context: list[TranscriptEntry],
    *,
    source: str = REFINER_SOURCE,
) -> list[TranscriptEntry]:
    """Refine ``entries`` in place (not committed). Returns the changed rows."""
    from app.services.llm import generate_json

    if not entries:
        return []
    labels = await _speaker_labels(db, session_id)

    def label(entry: TranscriptEntry) -> str:
        return labels.get(str(entry.speaker_id), "Unknown") if entry.speaker_id else "Unknown"

    prompt = build_prompt(
        [(str(e.id), label(e), e.text) for e in entries],
        [(label(e), e.text) for e in context],
    )
    reply = await generate_json(
        model_id,
        f"{SYSTEM_PROMPT}\n\n{prompt}",
        RefinementReply,
        session_id=session_id,
        source=source,
    )
    by_id = {str(e.id): e for e in entries}
    changed: list[TranscriptEntry] = []
    now = datetime.now(timezone.utc)
    for item in reply.entries if reply else []:
        entry = by_id.get(item.id)
        if entry is None or not accept_refinement(entry.text, item.text):
            continue
        if entry.raw_text is None:
            entry.raw_text = entry.text
        entry.text = item.text.strip()
        entry.refined_at = now
        changed.append(entry)
    return changed


async def refine_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    model_id: str,
    *,
    batch_size: int = DEFAULT_BATCH,
    limit: int | None = None,
    source: str = REFINER_SOURCE,
) -> list[TranscriptEntry]:
    """Refine every unrefined entry of a session, oldest first, in batches.

    Rows are flushed per batch and committed once at the end by the caller's
    session. ``limit`` caps the number of entries considered (a live cycle
    works on a recent window; a post-import pass takes them all).
    """
    rows = (
        await db.execute(
            select(TranscriptEntry)
            .where(TranscriptEntry.session_id == session_id)
            .order_by(TranscriptEntry.sequence)
        )
    ).scalars().all()
    pending = [r for r in rows if is_refinable(r)]
    if limit is not None:
        pending = pending[-limit:]
    if not pending:
        return []
    index = {r.id: i for i, r in enumerate(rows)}
    changed: list[TranscriptEntry] = []
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        first = index[batch[0].id]
        context = rows[max(0, first - CONTEXT_ENTRIES):first]
        try:
            changed.extend(await refine_batch(db, session_id, model_id, batch, context, source=source))
        except Exception:  # noqa: BLE001 - a failed batch leaves the originals standing
            logger.warning("Transcript refinement batch failed; originals kept", exc_info=True)
            continue
        await db.flush()
    return changed


def update_payload(entry: TranscriptEntry) -> dict:
    """The WebSocket ``transcript_updated`` message body for one entry."""
    return {
        "id": str(entry.id),
        "session_id": str(entry.session_id),
        "text": entry.text,
        "raw_text": entry.raw_text,
        "refined_at": entry.refined_at.isoformat() if entry.refined_at else None,
        "sequence": entry.sequence,
        "speaker_id": str(entry.speaker_id) if entry.speaker_id else None,
    }

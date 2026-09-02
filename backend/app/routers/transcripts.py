import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TranscriptEntry
from app.schemas import TranscriptEntryOut
from app.services.pii import shield
from app.services.session_manager import get_next_sequence

router = APIRouter(prefix="/api/sessions/{session_id}/transcripts", tags=["transcripts"])


class TranscriptCreate(BaseModel):
    text: str
    speaker_id: uuid.UUID | None = None


class TranscriptUpdate(BaseModel):
    speaker_id: uuid.UUID | None = None


@router.post("", status_code=201)
async def create_transcript(session_id: uuid.UUID, body: TranscriptCreate, db: AsyncSession = Depends(get_db)):
    """Save a transcript entry from the browser's Speech Recognition API."""
    seq = await get_next_sequence(session_id, db)
    text = await shield.protect_text(db, session_id, body.text)
    entry = TranscriptEntry(session_id=session_id, text=text, sequence=seq, speaker_id=body.speaker_id)
    db.add(entry)
    await db.commit()
    return {"ok": True}


@router.get("", response_model=list[TranscriptEntryOut])
async def list_transcripts(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TranscriptEntry)
        .where(TranscriptEntry.session_id == session_id)
        .order_by(TranscriptEntry.sequence)
    )
    return result.scalars().all()


@router.patch("/{transcript_id}", response_model=TranscriptEntryOut)
async def update_transcript(
    session_id: uuid.UUID,
    transcript_id: uuid.UUID,
    body: TranscriptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a transcript entry's speaker assignment."""
    entry = await db.get(TranscriptEntry, transcript_id)
    if not entry or entry.session_id != session_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Transcript entry not found")
    if "speaker_id" in body.model_fields_set:
        entry.speaker_id = body.speaker_id
    await db.commit()
    await db.refresh(entry)
    return entry

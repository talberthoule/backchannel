import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CallSegment, Session, TranscriptEntry
from app.routers.imports import _transcribe_audio_diarized
from app.services.llm import registry_entry
from app.services.privacy import get_local_only, is_local_model
from app.services.secrets import data_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/retranscribe", tags=["retranscribe"])


class RetranscribeIn(BaseModel):
    model_id: str


@router.post("")
async def retranscribe_session(session_id: uuid.UUID, body: RetranscribeIn, db: AsyncSession = Depends(get_db)):
    """Replay stored segment audio through diarization + the chosen transcriber.

    Destructive: replaces all existing transcript entries for the session.
    """
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.state == "active":
        raise HTTPException(409, "Cannot re-transcribe while a call is active")

    entry = registry_entry(body.model_id)
    supports_batch = (entry or {}).get("supports_batch_audio", False)
    if not supports_batch:
        raise HTTPException(400, f"Model {body.model_id} does not support batch transcription")
    if not is_local_model(body.model_id) and await get_local_only(db):
        raise HTTPException(400, "Privacy First mode is on: only local transcription models can be used")

    result = await db.execute(
        select(CallSegment)
        .where(CallSegment.session_id == session_id, CallSegment.audio_path.is_not(None))
        .order_by(CallSegment.segment_number)
    )
    segments = list(result.scalars().all())
    audio_files = [data_dir() / s.audio_path for s in segments]
    audio_files = [p for p in audio_files if p.exists()]
    if not audio_files:
        raise HTTPException(404, "No stored audio for this session")

    await db.execute(delete(TranscriptEntry).where(TranscriptEntry.session_id == session_id))
    await db.commit()

    # ponytail: one diarizer pass per segment; speaker identity across segments
    # relies on in-order auto-id mapping onto existing speaker rows. Share one
    # registry across segments if cross-segment voice matching ever matters.
    total = 0
    for path in audio_files:
        total += await _transcribe_audio_diarized(path.read_bytes(), "wav", session_id, db, model_id=body.model_id)

    logger.info(f"Re-transcribed session {session_id}: {total} entries via {body.model_id}")
    return {"entries": total}

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CallSegment, Session, TranscriptEntry
from app.routers.imports import _transcribe_audio_diarized, _transcribe_split_audio_diarized
from app.services.diarizer_runtime import get_diarizer_runtime_config
from app.services.llm import registry_entry
from app.services.privacy import get_local_only, is_local_model
from app.services.secrets import data_dir
from app.services.speaker_diarizer import SpeakerRegistry
from app.services.runtime_activity import request_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/retranscribe", tags=["retranscribe"])


class RetranscribeIn(BaseModel):
    model_id: str


def _stored_audio_path(relative_path: str | None):
    if not relative_path:
        return None
    path = data_dir() / relative_path
    return path if path.exists() else None


async def _transcribe_stored_segments(
    segments: list[CallSegment],
    session_id: uuid.UUID,
    db: AsyncSession,
    model_id: str,
) -> int:
    runtime_config = await get_diarizer_runtime_config(db)
    mic_registry = SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold)
    remote_registry = SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold)
    mic_speaker_map: dict[str, str] = {}
    remote_speaker_map: dict[str, str] = {}
    total = 0

    for segment in segments:
        mic_path = _stored_audio_path(segment.mic_audio_path)
        system_path = _stored_audio_path(segment.system_audio_path)
        if mic_path and system_path:
            total += await _transcribe_split_audio_diarized(
                mic_path.read_bytes(),
                system_path.read_bytes(),
                session_id,
                db,
                model_id=model_id,
                mic_registry=mic_registry,
                remote_registry=remote_registry,
                mic_auto_speaker_map=mic_speaker_map,
                remote_auto_speaker_map=remote_speaker_map,
                runtime_config=runtime_config,
            )
            continue

        mixed_path = _stored_audio_path(segment.audio_path)
        if mixed_path:
            total += await _transcribe_audio_diarized(
                mixed_path.read_bytes(),
                "wav",
                session_id,
                db,
                model_id=model_id,
            )
        elif mic_path:
            total += await _transcribe_audio_diarized(
                mic_path.read_bytes(),
                "wav",
                session_id,
                db,
                model_id=model_id,
                registry=mic_registry,
                auto_speaker_map=mic_speaker_map,
                runtime_config=runtime_config,
                local_track=True,
            )
        elif system_path:
            total += await _transcribe_audio_diarized(
                system_path.read_bytes(),
                "wav",
                session_id,
                db,
                model_id=model_id,
                registry=remote_registry,
                auto_speaker_map=remote_speaker_map,
                runtime_config=runtime_config,
            )

    return total


@router.post("", dependencies=[Depends(request_tracker("retranscription"))])
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
        .where(
            CallSegment.session_id == session_id,
            or_(
                CallSegment.audio_path.is_not(None),
                CallSegment.mic_audio_path.is_not(None),
                CallSegment.system_audio_path.is_not(None),
            ),
        )
        .order_by(CallSegment.segment_number)
    )
    segments = list(result.scalars().all())
    if not any(
        _stored_audio_path(path)
        for segment in segments
        for path in (segment.mic_audio_path, segment.system_audio_path, segment.audio_path)
    ):
        raise HTTPException(404, "No stored audio for this session")

    await db.execute(delete(TranscriptEntry).where(TranscriptEntry.session_id == session_id))
    await db.commit()

    total = await _transcribe_stored_segments(segments, session_id, db, body.model_id)

    logger.info(f"Re-transcribed session {session_id}: {total} entries via {body.model_id}")
    return {"entries": total}

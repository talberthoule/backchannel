import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models import CallSegment, Session, TranscriptEntry
from app.routers.imports import _transcribe_audio_diarized, _transcribe_split_audio_diarized
from app.services.diarizer_runtime import get_diarizer_runtime_config
from app.services.llm import registry_entry
from app.services.privacy import get_local_only, is_local_model
from app.services.secrets import data_dir
from app.services.transcription_readiness import local_asr_status
from app.services.speaker_diarizer import SpeakerRegistry
from app.services import runtime_activity, transcription_jobs

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
    job: transcription_jobs.TranscriptionJob | None = None,
) -> int:
    runtime_config = await get_diarizer_runtime_config(db)
    mic_registry = SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold)
    remote_registry = SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold)
    mic_speaker_map: dict[str, str] = {}
    remote_speaker_map: dict[str, str] = {}
    total = 0

    for segment in segments:
        if job:
            job.check_canceled()
        segment_start = total
        job_kwargs = {}
        if job:
            job_kwargs = {
                "cancel_check": job.check_canceled,
                "entry_callback": lambda count, start=segment_start: job.update_entries(start + count),
                "commit": False,
            }
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
                **job_kwargs,
            )
        else:
            mixed_path = _stored_audio_path(segment.audio_path)
            if mixed_path:
                total += await _transcribe_audio_diarized(
                    mixed_path.read_bytes(),
                    "wav",
                    session_id,
                    db,
                    model_id=model_id,
                    **job_kwargs,
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
                    **job_kwargs,
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
                    **job_kwargs,
                )
        if job:
            job.finish_segment(total)
        await asyncio.sleep(0)

    return total


async def _stored_segments(session_id: uuid.UUID, db: AsyncSession) -> list[CallSegment]:
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
    return list(result.scalars().all())


def _available_segments(segments: list[CallSegment]) -> list[CallSegment]:
    return [
        segment
        for segment in segments
        if any(
            _stored_audio_path(path)
            for path in (segment.mic_audio_path, segment.system_audio_path, segment.audio_path)
        )
    ]


async def _run_retranscription_job(
    session_id: uuid.UUID,
    job_id: uuid.UUID,
) -> None:
    job = transcription_jobs.get_job(session_id, kind="retranscription", job_id=job_id)
    if not job:
        return
    try:
        with runtime_activity.track("retranscription"):
            job.start()
            async with async_session() as db:
                segments = _available_segments(await _stored_segments(session_id, db))
                if not segments:
                    raise FileNotFoundError("No stored audio for this session")
                await db.execute(delete(TranscriptEntry).where(TranscriptEntry.session_id == session_id))
                total = await _transcribe_stored_segments(
                    segments,
                    session_id,
                    db,
                    job.model_id,
                    job,
                )
                if total == 0:
                    raise ValueError(
                        "No speech was transcribed; the existing transcript was kept."
                    )
                job.check_canceled()
                await db.commit()
            job.complete()
            logger.info(
                "Re-transcribed session %s: %s entries via %s",
                session_id,
                total,
                job.model_id,
            )
    except transcription_jobs.JobCanceled:
        job.mark_canceled()
    except FileNotFoundError as exc:
        job.fail(str(exc))
    except ValueError as exc:
        job.fail(str(exc))
    except Exception:
        logger.exception("Re-transcription job %s failed", job.id)
        job.fail("Re-transcription failed. Check the application logs for details.")


@router.post("", status_code=202)
async def retranscribe_session(
    session_id: uuid.UUID,
    body: RetranscribeIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
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
    # Prove the transcriber can run before starting the replacement. The job
    # also keeps deletion and replacement in one transaction, so cancellation
    # or failure leaves the existing transcript intact (ALP-376).
    if is_local_model(body.model_id):
        usable, why = local_asr_status()
        if not usable:
            raise HTTPException(
                503,
                f"Cannot re-transcribe with '{body.model_id}': {why}. "
                "Nothing was changed. Pick a cloud transcription model, or "
                "update the app.",
            )

    segments = _available_segments(await _stored_segments(session_id, db))
    if not segments:
        raise HTTPException(404, "No stored audio for this session")

    try:
        job = transcription_jobs.create_job(
            session_id,
            "retranscription",
            body.model_id,
            len(segments),
        )
    except transcription_jobs.JobAlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    background_tasks.add_task(_run_retranscription_job, session_id, job.id)
    return job.snapshot()


@router.get("")
async def get_retranscription_status(session_id: uuid.UUID):
    job = transcription_jobs.get_job(session_id, kind="retranscription")
    if not job:
        raise HTTPException(404, "Re-transcription job not found")
    return job.snapshot()


@router.delete("")
async def cancel_retranscription(session_id: uuid.UUID):
    job = transcription_jobs.get_job(session_id, kind="retranscription")
    if not job:
        raise HTTPException(404, "Re-transcription job not found")
    job.cancel()
    return job.snapshot()

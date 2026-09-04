import asyncio
import logging
import re
import uuid
import os
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models import CallSegment, Speaker, TranscriptEntry
from app.services.pii import shield
from app.services.audio_store import SegmentAudioWriter
from app.services.batch_transcriber import TranscriptionError
from app.services.file_parsing import parse_docx, parse_markdown, parse_text
from app.services.audio_utils import convert_to_pcm16
from app.services.local_transcriber import create_transcriber
from app.services.diarizer_factory import create_diarizer
from app.services.diarizer_runtime import DiarizerRuntimeConfig, get_diarizer_runtime_config
from app.services.diarizer_selection import flush_diarizer_segments
from app.services.session_manager import get_next_sequence
from app.services.speaker_assignment import (
    auto_speaker_would_create_new_speaker,
    is_unknown_auto_speaker,
    resolve_existing_auto_speaker,
    resolve_live_mic_speaker,
)
from app.services.speaker_ghost_filter import should_defer_new_speaker_segment
from app.services.speaker_diarizer import DiarizedSegment, SpeakerRegistry
from app.services.transcription_runtime import get_transcription_runtime_config
from app.services import runtime_activity, transcription_jobs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/import", tags=["import"])


# Parsing helpers moved to app.services.file_parsing (shared with knowledge imports)
_parse_text = parse_text
_parse_markdown = parse_markdown
_parse_docx = parse_docx


# Default colors for auto-created speakers during import
_SPEAKER_COLORS = ["#0d9488", "#f59e0b", "#e74c3c", "#2ecc71", "#9b59b6", "#f39c12"]


def import_segment_would_create_new_speaker(
    auto_id: str,
    auto_speaker_map: dict[str, str],
    speakers: list[Speaker],
) -> bool:
    return auto_speaker_would_create_new_speaker(auto_id, auto_speaker_map, speakers)


def should_skip_import_ghost_speaker_segment(
    auto_id: str,
    auto_speaker_map: dict[str, str],
    speakers: list[Speaker],
    pcm_bytes: bytes,
    text: str,
) -> bool:
    return import_segment_would_create_new_speaker(auto_id, auto_speaker_map, speakers) and should_defer_new_speaker_segment(
        pcm_bytes,
        text,
    )


async def _persist_import_audio(pcm_data: bytes, session_id: uuid.UUID, db: AsyncSession) -> None:
    """Store imported audio as a call segment WAV so it can be replayed/re-transcribed."""
    result = await db.execute(
        select(CallSegment.segment_number)
        .where(CallSegment.session_id == session_id)
        .order_by(CallSegment.segment_number.desc())
        .limit(1)
    )
    seg_num = (result.scalar_one_or_none() or 0) + 1
    writer = SegmentAudioWriter(session_id, seg_num)
    writer.append(pcm_data)
    rel_path = writer.close()
    now = datetime.now(timezone.utc)
    db.add(CallSegment(session_id=session_id, segment_number=seg_num, started_at=now, ended_at=now, audio_path=rel_path))
    await db.flush()


async def _diarize_pcm(
    pcm_data: bytes,
    diarizer,
    cancel_check: Callable[[], None] | None = None,
) -> list[DiarizedSegment]:
    chunk_size = 16000 * 2 // 10
    segments = []
    for offset in range(0, len(pcm_data), chunk_size):
        if cancel_check:
            cancel_check()
        chunk = pcm_data[offset:offset + chunk_size]
        emitted = await asyncio.to_thread(diarizer.feed_audio, chunk)
        for segment in emitted:
            if segment.start_sample is None:
                segment.start_sample = max(0, offset + len(chunk) - len(segment.pcm_bytes)) // 2
            segments.append(segment)
    if cancel_check:
        cancel_check()
    for segment in await asyncio.to_thread(flush_diarizer_segments, diarizer):
        if segment.start_sample is None:
            segment.start_sample = max(0, len(pcm_data) - len(segment.pcm_bytes)) // 2
        segments.append(segment)
    return segments


async def _persist_diarized_segments(
    segments: list[tuple[DiarizedSegment, bool, dict[str, str]]],
    session_id: uuid.UUID,
    db: AsyncSession,
    transcriber,
    speakers: list[Speaker],
    cancel_check: Callable[[], None] | None = None,
    entry_callback: Callable[[int], None] | None = None,
) -> int:
    count = 0
    for seg, local_track, auto_speaker_map in segments:
        if cancel_check:
            cancel_check()
        try:
            text = await transcriber.transcribe_segment(seg.pcm_bytes)
        except TranscriptionError as exc:
            # Keep import best-effort: a failed segment is skipped, not fatal.
            logger.warning(f"Audio import: segment transcription failed: {exc}")
            continue
        if not text:
            continue
        if cancel_check:
            cancel_check()
        text = await shield.protect_text(db, session_id, text)

        local_speaker = resolve_live_mic_speaker(seg.speaker_id, speakers, local_track)
        unknown_speaker = is_unknown_auto_speaker(seg.speaker_id)
        if not local_speaker and not unknown_speaker and should_skip_import_ghost_speaker_segment(
            seg.speaker_id, auto_speaker_map, speakers, seg.pcm_bytes, text
        ):
            continue

        mapped_speaker = (
            None
            if local_speaker or unknown_speaker
            else resolve_existing_auto_speaker(seg.speaker_id, auto_speaker_map, speakers)
        )
        if local_speaker:
            speaker_id_str = str(local_speaker.id)
        elif unknown_speaker:
            speaker_id_str = None
        elif mapped_speaker:
            speaker_id_str = str(mapped_speaker.id)
        else:
            color = _SPEAKER_COLORS[len(speakers) % len(_SPEAKER_COLORS)]
            new_speaker = Speaker(
                session_id=session_id,
                name=f"Participant {len(speakers) + 1}",
                color=color,
                is_user=False,
                speaker_type="external",
            )
            db.add(new_speaker)
            await db.flush()
            speakers.append(new_speaker)
            auto_speaker_map[seg.speaker_id] = str(new_speaker.id)
            speaker_id_str = str(new_speaker.id)

        seq = await get_next_sequence(session_id, db)
        db.add(
            TranscriptEntry(
                session_id=session_id,
                text=text,
                sequence=seq,
                speaker_id=uuid.UUID(speaker_id_str) if speaker_id_str else None,
            )
        )
        count += 1
        if entry_callback:
            entry_callback(count)
    return count


async def _transcribe_audio_diarized(
    file_bytes: bytes,
    source_format: str,
    session_id: uuid.UUID,
    db: AsyncSession,
    model_id: str | None = None,
    persist_audio: bool = False,
    probe_sortformer: bool = True,
    registry: SpeakerRegistry | None = None,
    auto_speaker_map: dict[str, str] | None = None,
    runtime_config: DiarizerRuntimeConfig | None = None,
    local_track: bool = False,
    cancel_check: Callable[[], None] | None = None,
    entry_callback: Callable[[int], None] | None = None,
    commit: bool = True,
) -> int:
    """Transcribe audio using diarization pipeline. Returns count of entries created."""
    # Convert to PCM16 16kHz mono
    pcm_data = await asyncio.to_thread(convert_to_pcm16, file_bytes, source_format)

    if persist_audio:
        await _persist_import_audio(pcm_data, session_id, db)

    if runtime_config is None:
        runtime_config = await get_diarizer_runtime_config(db, probe_sortformer=probe_sortformer)
    if registry is None:
        registry = SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold)
    diarizer = create_diarizer(runtime_config.effective_live_diarizer, registry=registry)
    transcription_config = await get_transcription_runtime_config(db)
    transcriber = create_transcriber(
        model_id or transcription_config.batch_model_id,
        session_id=session_id,
    )

    result = await db.execute(
        select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
    )
    speakers = list(result.scalars().all())

    if auto_speaker_map is None:
        auto_speaker_map = {}
    segments = await _diarize_pcm(pcm_data, diarizer, cancel_check)
    count = await _persist_diarized_segments(
        [(segment, local_track, auto_speaker_map) for segment in segments],
        session_id,
        db,
        transcriber,
        speakers,
        cancel_check,
        entry_callback,
    )

    if commit:
        await db.commit()
    return count


async def _transcribe_split_audio_diarized(
    mic_file_bytes: bytes,
    system_file_bytes: bytes,
    session_id: uuid.UUID,
    db: AsyncSession,
    model_id: str,
    mic_registry: SpeakerRegistry,
    remote_registry: SpeakerRegistry,
    mic_auto_speaker_map: dict[str, str],
    remote_auto_speaker_map: dict[str, str],
    runtime_config: DiarizerRuntimeConfig,
    cancel_check: Callable[[], None] | None = None,
    entry_callback: Callable[[int], None] | None = None,
    commit: bool = True,
) -> int:
    mic_pcm = await asyncio.to_thread(convert_to_pcm16, mic_file_bytes, "wav")
    system_pcm = await asyncio.to_thread(convert_to_pcm16, system_file_bytes, "wav")
    mic_diarizer = create_diarizer(runtime_config.effective_live_diarizer, registry=mic_registry)
    system_diarizer = create_diarizer(runtime_config.effective_live_diarizer, registry=remote_registry)
    transcription_config = await get_transcription_runtime_config(db)
    transcriber = create_transcriber(
        model_id or transcription_config.batch_model_id,
        session_id=session_id,
    )
    result = await db.execute(
        select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
    )
    speakers = list(result.scalars().all())

    ordered_segments = []
    emitted_order = 0
    tracks = (
        (mic_pcm, mic_diarizer, True, mic_auto_speaker_map),
        (system_pcm, system_diarizer, False, remote_auto_speaker_map),
    )
    for pcm, diarizer, local_track, speaker_map in tracks:
        for segment in await _diarize_pcm(pcm, diarizer, cancel_check):
            ordered_segments.append(
                (segment.start_sample or 0, emitted_order, segment, local_track, speaker_map)
            )
            emitted_order += 1

    ordered_segments.sort(key=lambda item: (item[0], item[1]))
    count = await _persist_diarized_segments(
        [(segment, local_track, speaker_map) for _, _, segment, local_track, speaker_map in ordered_segments],
        session_id,
        db,
        transcriber,
        speakers,
        cancel_check,
        entry_callback,
    )
    if commit:
        await db.commit()
    return count


async def _run_audio_import_job(
    session_id: uuid.UUID,
    job_id: uuid.UUID,
    content: bytes,
    source_format: str,
) -> None:
    job = transcription_jobs.get_job(session_id, kind="audio_import", job_id=job_id)
    if not job:
        return
    try:
        with runtime_activity.track("audio import"):
            job.start()
            async with async_session() as db:
                count = await _transcribe_audio_diarized(
                    content,
                    source_format,
                    session_id,
                    db,
                    model_id=job.model_id,
                    persist_audio=True,
                    probe_sortformer=False,
                    cancel_check=job.check_canceled,
                    entry_callback=job.update_entries,
                    commit=False,
                )
                if count == 0:
                    raise ValueError("No speech detected in audio file")
                job.check_canceled()
                await db.commit()
            job.finish_segment(count)
            job.complete()
    except transcription_jobs.JobCanceled:
        job.mark_canceled()
    except ValueError as exc:
        job.fail(str(exc))
    except Exception:
        logger.exception("Audio import job %s failed", job.id)
        job.fail("Audio import failed. Check the application logs for details.")


@router.post("/transcript")
async def import_transcript(
    session_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Import a transcript file (.txt, .md, .docx) into the session's transcript entries."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".txt", ".md", ".docx"):
        raise HTTPException(400, f"Unsupported format: {ext}. Use .txt, .md, or .docx")

    content = await file.read()

    if ext == ".docx":
        segments = _parse_docx(content)
    elif ext == ".md":
        segments = _parse_markdown(content.decode("utf-8", errors="replace"))
    else:
        segments = _parse_text(content.decode("utf-8", errors="replace"))

    if not segments:
        raise HTTPException(400, "No text content found in file")

    count = 0
    for text in segments:
        seq = await get_next_sequence(session_id, db)
        entry = TranscriptEntry(session_id=session_id, text=await shield.protect_text(db, session_id, text), sequence=seq)
        db.add(entry)
        count += 1

    await db.commit()
    return {"imported": count, "filename": filename}


@router.post("/audio", status_code=202)
async def import_audio(
    session_id: uuid.UUID,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Import an audio file — diarizes and transcribes via acoustic fingerprinting."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".m4a", ".mp3", ".wav", ".ogg", ".flac"):
        raise HTTPException(400, f"Unsupported audio format: {ext}")

    content = await file.read()
    source_format = ext.lstrip(".")
    config = await get_transcription_runtime_config(db)
    try:
        job = transcription_jobs.create_job(
            session_id,
            "audio_import",
            config.batch_model_id,
            1,
            filename=filename,
        )
    except transcription_jobs.JobAlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    background_tasks.add_task(
        _run_audio_import_job,
        session_id,
        job.id,
        content,
        source_format,
    )
    return job.snapshot()


@router.get("/audio/status")
async def get_audio_import_status(session_id: uuid.UUID):
    job = transcription_jobs.get_job(session_id, kind="audio_import")
    if not job:
        raise HTTPException(404, "Audio import job not found")
    return job.snapshot()


@router.delete("/audio")
async def cancel_audio_import(session_id: uuid.UUID):
    job = transcription_jobs.get_job(session_id, kind="audio_import")
    if not job:
        raise HTTPException(404, "Audio import job not found")
    job.cancel()
    return job.snapshot()

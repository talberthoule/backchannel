import re
import uuid
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CallSegment, Speaker, TranscriptEntry
from app.services.audio_store import SegmentAudioWriter
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
from app.services.speaker_diarizer import SpeakerRegistry
from app.services.transcription_runtime import get_transcription_runtime_config

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
) -> int:
    """Transcribe audio using diarization pipeline. Returns count of entries created."""
    # Convert to PCM16 16kHz mono
    pcm_data = convert_to_pcm16(file_bytes, source_format)

    if persist_audio:
        await _persist_import_audio(pcm_data, session_id, db)

    if runtime_config is None:
        runtime_config = await get_diarizer_runtime_config(db, probe_sortformer=probe_sortformer)
    if registry is None:
        registry = SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold)
    diarizer = create_diarizer(runtime_config.effective_live_diarizer, registry=registry)
    transcription_config = await get_transcription_runtime_config(db)
    transcriber = create_transcriber(model_id or transcription_config.batch_model_id)

    # Load existing speakers
    result = await db.execute(
        select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
    )
    speakers = list(result.scalars().all())

    if auto_speaker_map is None:
        auto_speaker_map = {}

    def resolve_speaker(auto_id: str) -> str | None:
        if auto_id in auto_speaker_map:
            return auto_speaker_map[auto_id]

        mapped_speaker = resolve_existing_auto_speaker(auto_id, auto_speaker_map, speakers)
        if mapped_speaker:
            return str(mapped_speaker.id)

        return None

    # Feed audio through diarizer in chunks (100ms at a time)
    chunk_size = 16000 * 2 // 10  # 100ms of PCM16
    all_segments = []

    for i in range(0, len(pcm_data), chunk_size):
        chunk = pcm_data[i:i + chunk_size]
        segments = diarizer.feed_audio(chunk)
        all_segments.extend(segments)

    # Flush remaining
    all_segments.extend(flush_diarizer_segments(diarizer))

    # Transcribe each segment
    count = 0
    for seg in all_segments:
        text = await transcriber.transcribe_segment(seg.pcm_bytes)
        if not text:
            continue

        local_speaker = resolve_live_mic_speaker(seg.speaker_id, speakers, local_track)
        unknown_speaker = is_unknown_auto_speaker(seg.speaker_id)
        if not local_speaker and not unknown_speaker and should_skip_import_ghost_speaker_segment(
            seg.speaker_id, auto_speaker_map, speakers, seg.pcm_bytes, text
        ):
            continue

        if local_speaker:
            speaker_id_str = str(local_speaker.id)
        elif unknown_speaker:
            speaker_id_str = None
        else:
            speaker_id_str = resolve_speaker(seg.speaker_id)
        # Auto-create speaker if needed
        if speaker_id_str is None and not unknown_speaker:
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
        entry = TranscriptEntry(
            session_id=session_id,
            text=text,
            sequence=seq,
            speaker_id=uuid.UUID(speaker_id_str) if speaker_id_str else None,
        )
        db.add(entry)
        count += 1

    await db.commit()
    return count


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
        entry = TranscriptEntry(session_id=session_id, text=text, sequence=seq)
        db.add(entry)
        count += 1

    await db.commit()
    return {"imported": count, "filename": filename}


@router.post("/audio")
async def import_audio(
    session_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Import an audio file — diarizes and transcribes via acoustic fingerprinting."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".m4a", ".mp3", ".wav", ".ogg", ".flac"):
        raise HTTPException(400, f"Unsupported audio format: {ext}")

    content = await file.read()
    source_format = ext.lstrip(".")

    count = await _transcribe_audio_diarized(
        content,
        source_format,
        session_id,
        db,
        persist_audio=True,
        probe_sortformer=False,
    )
    if count == 0:
        raise HTTPException(400, "No speech detected in audio file")

    return {"imported": count, "filename": filename}

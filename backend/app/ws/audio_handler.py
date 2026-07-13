import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import async_session
from app.models import AgentConfig, CallSegment, Directive, Question, Session, SessionAgentOverride, Speaker, TranscriptEntry
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.session_manager import get_active_directives, get_document_summaries, get_next_sequence
from app.services.audio_store import SegmentAudioWriter
from app.services.local_transcriber import create_transcriber
from app.services.track_mixer import TrackMixer
from app.services.diarizer_factory import create_diarizer
from app.services.diarizer_runtime import get_diarizer_runtime_config
from app.services.diarizer_selection import flush_diarizer_segments
from app.services.speaker_assignment import auto_speaker_would_create_new_speaker, resolve_existing_auto_speaker
from app.services.speaker_ghost_filter import should_defer_new_speaker_segment
from app.services.speaker_diarizer import SpeakerRegistry
from app.services.ordered_transcription import OrderedTranscriptionQueue
from app.services.privacy import get_local_only
from app.services.transcription_runtime import get_transcription_runtime_config

logger = logging.getLogger(__name__)

router = APIRouter()

# Default colors for auto-created speakers
_SPEAKER_COLORS = ["#0d9488", "#f59e0b", "#e74c3c", "#2ecc71", "#9b59b6", "#f39c12"]


async def _send_status(websocket: WebSocket, state: str, message: str, **extra: Any):
    try:
        await websocket.send_json({"type": "status", "data": {"state": state, "message": message, **extra}})
    except Exception:
        pass


async def _send_post_processing_status(
    websocket: WebSocket,
    stage: str,
    message: str,
    current_step: int,
    total_steps: int,
    progress: int,
    details: dict[str, Any] | None = None,
):
    payload: dict[str, Any] = {
        "stage": stage,
        "current_step": current_step,
        "total_steps": total_steps,
        "progress": progress,
    }
    if details is not None:
        payload["details"] = details
    await _send_status(websocket, "post_processing", message, **payload)


def _speaker_context(speaker: Speaker) -> dict:
    return {
        "id": str(speaker.id),
        "name": speaker.name,
        "role": speaker.role,
        "is_user": speaker.is_user,
        "speaker_type": speaker.speaker_type,
        "display_name": speaker.display_name,
        "display_name_enabled": speaker.display_name_enabled,
    }


def _sync_orchestrator_speaker(orchestrator: AgentOrchestrator, speaker: Speaker):
    speaker_id = str(speaker.id)
    if any(str(s.get("id")) == speaker_id for s in orchestrator.speakers):
        return
    orchestrator.speakers.append(_speaker_context(speaker))


async def _would_create_new_speaker(
    session_id: uuid.UUID,
    auto_id: str,
    auto_speaker_map: dict[str, str],
) -> bool:
    if auto_id in auto_speaker_map:
        return False

    async with async_session() as db:
        result = await db.execute(
            select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
        )
        speakers = list(result.scalars().all())

    return auto_speaker_would_create_new_speaker(auto_id, auto_speaker_map, speakers)


def _decode_audio_frame(raw_frame: bytes) -> tuple[int, bytes]:
    if len(raw_frame) % 2 == 0:
        return 0, raw_frame
    track = raw_frame[0] if raw_frame[0] in (0, 1) else 0
    return track, raw_frame[1:]


async def _flush_remaining_audio(
    diarizer: Any,
    transcription_queue: OrderedTranscriptionQueue,
    speaker_prefix: str = "",
):
    for seg in await asyncio.to_thread(flush_diarizer_segments, diarizer):
        try:
            transcription_queue.add(f"{speaker_prefix}{seg.speaker_id}", seg.pcm_bytes)
        except Exception:
            pass


async def _finalize_call(
    session_id: uuid.UUID,
    websocket: WebSocket,
    diarizer: Any,
    orchestrator: AgentOrchestrator,
    transcription_queue: OrderedTranscriptionQueue,
    audio_writer: SegmentAudioWriter | None = None,
    sys_diarizer: Any = None,
):
    total_steps = 6 if orchestrator.briefing_enabled() else 5
    await _send_post_processing_status(
        websocket,
        "speaker_assignment",
        "Finalizing speaker assignments...",
        1,
        total_steps,
        15,
    )
    await _flush_remaining_audio(diarizer, transcription_queue)
    if sys_diarizer is not None:
        await _flush_remaining_audio(sys_diarizer, transcription_queue, speaker_prefix="sys_")
    await transcription_queue.drain()

    async def _forward_drain_progress(event: dict[str, object]):
        await _send_status(
            websocket,
            "post_processing",
            str(event.get("message", "Post-processing call output...")),
            **{
                key: value
                for key, value in event.items()
                if key != "message"
            },
        )

    drain_result = await orchestrator.graceful_drain(progress_callback=_forward_drain_progress)
    await orchestrator.close_all()

    await _send_post_processing_status(
        websocket,
        "saving_session",
        "Saving completed session...",
        total_steps,
        total_steps,
        95,
        details=drain_result,
    )

    async with async_session() as db:
        result = await db.execute(
            select(CallSegment)
            .where(CallSegment.session_id == session_id, CallSegment.ended_at.is_(None))
            .order_by(CallSegment.segment_number.desc())
            .limit(1)
        )
        open_segment = result.scalar_one_or_none()
        if open_segment:
            open_segment.ended_at = datetime.now(timezone.utc)
            if audio_writer:
                try:
                    audio_rel_path = audio_writer.close()
                    if audio_rel_path:
                        open_segment.audio_path = audio_rel_path
                except Exception as e:
                    logger.warning(f"Failed to finalize segment audio: {e}")

        session = await db.get(Session, session_id)
        if session and session.state == "active":
            session.state = "completed"
            session.ended_at = datetime.now(timezone.utc)
        await db.commit()

    await _send_status(
        websocket,
        "completed",
        "Post-processing complete",
        stage="complete",
        current_step=total_steps,
        total_steps=total_steps,
        progress=100,
        details=drain_result,
    )


@router.websocket("/ws/{session_id}")
async def audio_websocket(websocket: WebSocket, session_id: uuid.UUID):
    await websocket.accept()

    async with async_session() as db:
        session = await db.get(Session, session_id)
        if not session:
            await websocket.send_json({"type": "status", "data": {"state": "error", "message": "Session not found"}})
            await websocket.close()
            return

        directives = await get_active_directives(session_id, db)
        doc_summaries = await get_document_summaries(session_id, db)
        meeting_type = session.meeting_type
        meeting_context = session.meeting_context or session.notes or ""
        is_resume = session.state == "completed" or session.started_at is not None

        # Load existing questions to give agents context on what to track
        result = await db.execute(
            select(Question).where(
                Question.session_id == session_id,
                Question.answered.is_(False),
                Question.dismissed.is_(False),
            )
        )
        existing_questions = [{"id": str(q.id), "question": q.question} for q in result.scalars().all()]

        # Load speakers for agent context
        result = await db.execute(
            select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
        )
        speakers_list = [_speaker_context(s) for s in result.scalars().all()]

        # Load agent configs from DB
        agent_result = await db.execute(
            select(AgentConfig).order_by(AgentConfig.display_order)
        )
        agent_configs_list = agent_result.scalars().all()
        agent_configs = {a.slug: a for a in agent_configs_list}

        # Load per-session overrides
        override_result = await db.execute(
            select(SessionAgentOverride).where(SessionAgentOverride.session_id == session_id)
        )
        session_overrides = {o.agent_slug: o.enabled for o in override_result.scalars().all()}

        # Merge: override trumps global
        for slug, config in agent_configs.items():
            if slug in session_overrides:
                config.enabled = session_overrides[slug]

        runtime_config = await get_diarizer_runtime_config(db)
        transcription_config = await get_transcription_runtime_config(db)
        local_only = await get_local_only(db)

    stopped = False
    audio_chunks_received = 0
    audio_bytes_received = 0
    last_audio_status_at = 0.0
    # Track active (unanswered) questions for agent context
    active_questions: list[dict] = list(existing_questions)

    # --- Agent Orchestrator ---
    orchestrator = AgentOrchestrator(
        session_id=session_id,
        websocket=websocket,
        directives=directives,
        doc_summaries=doc_summaries,
        active_questions=active_questions,
        speakers=speakers_list,
        agent_configs=agent_configs,
        meeting_type=meeting_type,
        meeting_context=meeting_context,
        local_only=local_only,
    )

    # --- Speaker diarization ---
    registry = SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold)
    diarizer = create_diarizer(runtime_config.effective_live_diarizer, registry=registry)
    # Second diarizer for the system-audio track, created on first use.
    sys_diarizer = None
    mixer = TrackMixer()
    transcriber = create_transcriber(transcription_config.batch_model_id)

    # Map auto-assigned speaker IDs ("auto_1", "auto_2") to DB Speaker rows
    auto_speaker_map: dict[str, str] = {}  # "auto_1" -> str(speaker.id)
    # Also track speaker names for transcript buffer
    speaker_name_map: dict[str, str] = {}  # str(speaker.id) -> speaker.name
    speaker_type_map: dict[str, str] = {}  # str(speaker.id) -> team/external

    async def _resolve_auto_speaker(auto_id: str) -> str | None:
        """Map diarizer's auto-assigned IDs to DB Speaker rows."""
        if auto_id in auto_speaker_map:
            return auto_speaker_map[auto_id]

        async with async_session() as db:
            result = await db.execute(
                select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
            )
            speakers = list(result.scalars().all())

        mapped_speaker = resolve_existing_auto_speaker(auto_id, auto_speaker_map, speakers)
        if mapped_speaker:
            speaker_name_map[str(mapped_speaker.id)] = mapped_speaker.name
            speaker_type_map[str(mapped_speaker.id)] = mapped_speaker.speaker_type
            _sync_orchestrator_speaker(orchestrator, mapped_speaker)
            logger.info(f"Speaker mapping: {auto_id} -> {mapped_speaker.name}")
            return str(mapped_speaker.id)

        # No speaker row is auto-assigned to the user without voice enrollment.
        # First detected voice stays a generic participant.

        # More speakers than registered — auto-create a new Speaker row
        color = _SPEAKER_COLORS[len(speakers) % len(_SPEAKER_COLORS)]
        name_prefix = "Remote Participant" if auto_id.startswith("sys_") else "Participant"
        async with async_session() as db:
            new_speaker = Speaker(
                session_id=session_id,
                name=f"{name_prefix} {len(speakers) + 1}",
                color=color,
                is_user=False,
                speaker_type="external",
            )
            db.add(new_speaker)
            await db.commit()
            await db.refresh(new_speaker)
            auto_speaker_map[auto_id] = str(new_speaker.id)
            speaker_name_map[str(new_speaker.id)] = new_speaker.name
            speaker_type_map[str(new_speaker.id)] = new_speaker.speaker_type
            _sync_orchestrator_speaker(orchestrator, new_speaker)
            logger.info(f"Auto-created speaker: {new_speaker.name} for {auto_id}")
            return str(new_speaker.id)

    async def _emit_transcript(speaker_auto_id: str, pcm_bytes: bytes, text: str):
        """Persist an already-transcribed diarized segment in original audio order."""
        if (
            await _would_create_new_speaker(session_id, speaker_auto_id, auto_speaker_map)
            and should_defer_new_speaker_segment(pcm_bytes, text)
        ):
            logger.info(
                "Deferring short one-off new-speaker segment: "
                f"auto_id={speaker_auto_id} bytes={len(pcm_bytes)} text='{text[:80]}'"
            )
            return

        speaker_id = await _resolve_auto_speaker(speaker_auto_id)
        speaker_name = speaker_name_map.get(speaker_id, "Unknown") if speaker_id else "Unknown"
        speaker_type = speaker_type_map.get(speaker_id) if speaker_id else None

        async with async_session() as db:
            seq = await get_next_sequence(session_id, db)
            entry = TranscriptEntry(
                session_id=session_id,
                text=text,
                sequence=seq,
                speaker_id=uuid.UUID(speaker_id) if speaker_id else None,
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
            transcript_payload = {
                "id": str(entry.id),
                "session_id": str(entry.session_id),
                "text": entry.text,
                "timestamp": entry.timestamp.isoformat(),
                "sequence": entry.sequence,
                "speaker_id": str(entry.speaker_id) if entry.speaker_id else None,
            }

        # Feed transcript to orchestrator for text agents
        await orchestrator.feed_transcript(text, speaker_name, speaker_id, speaker_type=speaker_type)

        try:
            await websocket.send_json({
                "type": "transcript",
                "data": transcript_payload,
            })
        except Exception:
            pass
        await _send_status(
            websocket,
            "transcript_saved",
            f"Transcript saved: seq {transcript_payload['sequence']}",
            details={
                "sequence": transcript_payload["sequence"],
                "speaker_id": speaker_id,
            },
        )

    transcription_queue = OrderedTranscriptionQueue(
        transcribe=transcriber.transcribe_segment,
        emit=_emit_transcript,
    )

    audio_writer: SegmentAudioWriter | None = None

    async def reconnect_orchestrator():
        """Reconnect the audio gateway through the orchestrator."""
        # Flush remaining diarized audio
        for seg in await asyncio.to_thread(flush_diarizer_segments, diarizer):
            transcription_queue.add(seg.speaker_id, seg.pcm_bytes)
        diarizer.reset()
        if sys_diarizer is not None:
            for seg in await asyncio.to_thread(flush_diarizer_segments, sys_diarizer):
                transcription_queue.add(f"sys_{seg.speaker_id}", seg.pcm_bytes)
            sys_diarizer.reset()

        try:
            success = await orchestrator._reconnect_gateway()
            if success:
                await websocket.send_json({
                    "type": "status",
                    "data": {"state": "active", "message": "Reconnected to AI"}
                })
            return success
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            return False

    try:
        await websocket.send_json({"type": "status", "data": {"state": "connecting", "message": "Connecting to AI agents..."}})
        await orchestrator.start()
        active_message = (
            "Listening (Privacy First: local transcription only, cloud AI agents off)..."
            if local_only
            else "Listening..."
        )
        await websocket.send_json({"type": "status", "data": {"state": "active", "message": active_message}})

        # Create a new call segment
        async with async_session() as db:
            session = await db.get(Session, session_id)
            if session:
                # Determine segment number
                result = await db.execute(
                    select(CallSegment.segment_number)
                    .where(CallSegment.session_id == session_id)
                    .order_by(CallSegment.segment_number.desc())
                    .limit(1)
                )
                last_seg = result.scalar_one_or_none()
                seg_num = (last_seg or 0) + 1

                segment = CallSegment(
                    session_id=session_id,
                    segment_number=seg_num,
                    started_at=datetime.now(timezone.utc),
                )
                db.add(segment)
                audio_writer = SegmentAudioWriter(session_id, seg_num)

                if is_resume:
                    seq = await get_next_sequence(session_id, db)
                    marker = TranscriptEntry(
                        session_id=session_id,
                        text=f"--- Session Resumed (Call {seg_num}) ---",
                        sequence=seq,
                    )
                    db.add(marker)

                if session.state in ("pre_call", "completed"):
                    session.state = "active"
                    if not session.started_at:
                        session.started_at = datetime.now(timezone.utc)
                    session.ended_at = None
                await db.commit()

        while not stopped:
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                logger.info(f"Browser disconnected for session {session_id}")
                break

            if "bytes" in message:
                track, pcm_data = _decode_audio_frame(message["bytes"])
                try:
                    audio_chunks_received += 1
                    audio_bytes_received += len(pcm_data)
                    now = monotonic()
                    if now - last_audio_status_at >= 5:
                        last_audio_status_at = now
                        await _send_status(
                            websocket,
                            "audio_received",
                            (
                                f"Backend received {audio_bytes_received // 32000}s audio "
                                f"({audio_chunks_received} chunks)"
                            ),
                            details={
                                "chunks": audio_chunks_received,
                                "bytes": audio_bytes_received,
                                "seconds": audio_bytes_received / 32000,
                            },
                        )

                    # Mix tracks into one stream for the gateway and the session recording
                    mixed = mixer.add(track, pcm_data)
                    if mixed:
                        if audio_writer:
                            try:
                                audio_writer.append(mixed)
                            except Exception as e:
                                logger.warning(f"Disabling segment audio persistence: {e}")
                                audio_writer = None
                        # Forward to orchestrator for the audio gateway and text-agent context
                        await orchestrator.send_audio(mixed)

                    # Feed into the per-track diarizer for speaker-attributed transcription
                    if track == 1:
                        if sys_diarizer is None:
                            sys_diarizer = create_diarizer(
                                runtime_config.effective_live_diarizer,
                                registry=SpeakerRegistry(threshold=runtime_config.speaker_similarity_threshold),
                            )
                        # Diarizer inference (and its lazy model load) is CPU-bound;
                        # keep it off the event loop or websocket keepalives starve
                        # and both the browser and gateway sockets die with 1011.
                        segments = await asyncio.to_thread(sys_diarizer.feed_audio, pcm_data)
                        for seg in segments:
                            seg.speaker_id = f"sys_{seg.speaker_id}"
                    else:
                        segments = await asyncio.to_thread(diarizer.feed_audio, pcm_data)
                    audio_bytes_total = getattr(audio_websocket, "_abt", 0) + len(pcm_data)
                    setattr(audio_websocket, "_abt", audio_bytes_total)
                    if audio_bytes_total // 320000 != (audio_bytes_total - len(pcm_data)) // 320000:
                        logger.info(f"Audio flow: ~{audio_bytes_total // 32000 / 10:.1f}s received")
                    for seg in segments:
                        logger.info(f"Diarized segment: speaker={seg.speaker_id} bytes={len(seg.pcm_bytes)}")
                        await _send_status(
                            websocket,
                            "audio_segment",
                            f"Queued {len(seg.pcm_bytes) // 32000}s speech segment for transcription",
                            details={
                                "speaker_auto_id": seg.speaker_id,
                                "bytes": len(seg.pcm_bytes),
                            },
                        )
                        transcription_queue.add(seg.speaker_id, seg.pcm_bytes)

                except Exception as e:
                    logger.warning(f"Audio send failed, reconnecting: {e}")
                    if not await reconnect_orchestrator():
                        break

            elif "text" in message:
                data = json.loads(message["text"])
                if data.get("type") == "stop":
                    stopped = True
                    break
                elif data.get("type") == "directive":
                    directive_text = data.get("text", "")
                    if directive_text:
                        async with async_session() as db:
                            directive = Directive(session_id=session_id, text=directive_text)
                            db.add(directive)
                            await db.commit()
                        await orchestrator.send_directive(directive_text)

            # Check audio gateway health
            if not await orchestrator.check_health():
                if not await reconnect_orchestrator():
                    break

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "status", "data": {"state": "error", "message": str(e)}})
        except Exception:
            pass
    finally:
        await _finalize_call(
            session_id,
            websocket,
            diarizer,
            orchestrator,
            transcription_queue,
            audio_writer=audio_writer,
            sys_diarizer=sys_diarizer,
        )

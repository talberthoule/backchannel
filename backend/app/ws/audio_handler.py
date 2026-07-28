import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket
from sqlalchemy import func, select

from app.database import async_session
from app.models import AgentConfig, CallSegment, Question, Session, SessionAgentOverride, Speaker, TranscriptEntry
from app.services.agents.orchestrator import AgentOrchestrator, drain_progress_percent
from app.services.privacy import admitted_model_ids
from app.services.session_manager import get_active_directives, get_document_summaries, get_next_sequence
from app.services.audio_store import SegmentAudioWriter
from app.services.speaker_assignment import (
    auto_speaker_would_create_new_speaker,
    is_unknown_auto_speaker,
    load_live_mic_voice_embedding,
    resolve_existing_auto_speaker,
    resolve_live_mic_speaker,
)
from app.services.speaker_ghost_filter import should_defer_new_speaker_segment
from app.services.ordered_transcription import OrderedTranscriptionQueue
from app.services import runtime_activity
from app.ws.audio_persistence import (
    _append_audio_frames,
    _close_audio_writers,
    _flush_remaining_audio,
)
from app.ws.audio_pipeline import (
    _run_audio_pipeline,
    _transcription_failure_handler,
)
from app.ws.audio_runtime import (
    _QueuedAudioFrame,
    _create_audio_processors,
    _decode_audio_frame,
    _load_audio_runtime,
    _new_speaker_registry,
    _queued_speaker_auto_id,
    _receive_websocket_message,
    _reconnect_audio_gateway,
    _record_audio_flow,
    _run_diarization_worker,
    _send_gateway_audio,
    _send_status,
    _split_track_established_after_frame,
    _split_track_established_after_message,
    _stop_diarization_worker,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Default colors for auto-created speakers
_SPEAKER_COLORS = ["#0d9488", "#f59e0b", "#e74c3c", "#2ecc71", "#9b59b6", "#f39c12"]
_STOP_DRAIN_MODES = ("full", "skip_analysis")


def _requested_drain_mode(data: dict) -> str:
    requested = data.get("drain")
    return requested if requested in _STOP_DRAIN_MODES else "full"


async def _load_agent_configs(db, session_id: uuid.UUID) -> dict[str, AgentConfig]:
    result = await db.execute(select(AgentConfig).order_by(AgentConfig.display_order))
    configs = {config.slug: config for config in result.scalars().all()}
    result = await db.execute(
        select(SessionAgentOverride).where(SessionAgentOverride.session_id == session_id)
    )
    overrides = {override.agent_slug: override.enabled for override in result.scalars().all()}
    for slug, config in configs.items():
        if slug in overrides:
            config._session_override = overrides[slug]
            config.enabled = overrides[slug]
    return configs


async def _send_post_processing_status(
    websocket: WebSocket,
    stage: str,
    message: str,
    current_step: int,
    total_steps: int,
    progress: int,
    details: dict[str, Any] | None = None,
    steps: list[str] | None = None,
):
    payload: dict[str, Any] = {
        "stage": stage,
        "current_step": current_step,
        "total_steps": total_steps,
        "progress": progress,
    }
    if steps is not None:
        payload["steps"] = steps
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


async def _should_defer_new_speaker(
    session_id: uuid.UUID,
    auto_id: str,
    auto_speaker_map: dict[str, str],
    pcm_bytes: bytes,
    text: str,
) -> bool:
    would_create = await _would_create_new_speaker(session_id, auto_id, auto_speaker_map)
    return would_create and should_defer_new_speaker_segment(pcm_bytes, text)


def _normalize_speaker_auto_id(auto_id: str) -> tuple[str, bool]:
    return (auto_id[4:], True) if auto_id.startswith("mic_") else (auto_id, False)


def _speaker_identity(speaker: Speaker) -> tuple[str, str, str]:
    return str(speaker.id), speaker.name, speaker.speaker_type


async def _refuse_unready_transcription(
    websocket: WebSocket,
    readiness: Any,
) -> bool:
    """Refuse to start a call whose batch transcriber cannot produce text."""
    if readiness.ready:
        return False
    await _send_status(
        websocket,
        "transcription_unready",
        readiness.reason,
        details=readiness.to_dict(),
    )
    try:
        await websocket.close()
    except Exception:
        pass
    return True


def _derive_refusal_restore_state(
    ended_at: datetime | None,
    has_finished_segment: bool,
    has_transcripts: bool,
) -> str:
    """Prior state of a session left "active" by a refused start.

    ended_at survives only when no resume PATCH cleared it. A finished call
    segment or any transcript entry proves the session had a completed life
    before this start attempt; imported/analyzed sessions can be completed
    with transcript entries but zero call segments.
    """
    if ended_at is not None:
        return "completed"
    if has_finished_segment or has_transcripts:
        return "completed"
    return "pre_call"


async def _restore_session_after_refusal(session_id: uuid.UUID) -> str | None:
    """Server-side rollback of the optimistic "active" PATCH after a refusal.

    The frontend marks the session active before the socket opens; when the
    readiness gate then refuses, this restores the row so a refused call can
    never strand a session in "active" regardless of client behavior.
    Returns the restored state, or None when nothing needed restoring or the
    restore itself failed (contained: the refusal still proceeds).
    """
    try:
        async with async_session() as db:
            session = await db.get(Session, session_id)
            if session is None or session.state != "active":
                return None

            result = await db.execute(
                select(CallSegment)
                .where(
                    CallSegment.session_id == session_id,
                    CallSegment.ended_at.is_not(None),
                )
                .limit(1)
            )
            has_finished_segment = result.scalar_one_or_none() is not None

            result = await db.execute(
                select(TranscriptEntry)
                .where(TranscriptEntry.session_id == session_id)
                .limit(1)
            )
            has_transcripts = result.scalar_one_or_none() is not None

            prior = _derive_refusal_restore_state(
                session.ended_at, has_finished_segment, has_transcripts
            )
            session.state = prior
            if prior == "completed":
                if session.ended_at is None:
                    session.ended_at = datetime.now(timezone.utc)
            else:
                # The refused start never ran; undo the optimistic started_at.
                session.started_at = None
            await db.commit()
            return prior
    except Exception:
        logger.exception(f"Failed to restore session {session_id} after refused start")
        return None


async def _start_call_segment(
    session_id: uuid.UUID,
) -> tuple[uuid.UUID, dict[str, SegmentAudioWriter | None]] | None:
    async with async_session() as db:
        result = await db.execute(
            select(Session).where(Session.id == session_id).with_for_update()
        )
        session = result.scalar_one_or_none()
        if session is None:
            return None

        result = await db.execute(
            select(CallSegment.segment_number)
            .where(CallSegment.session_id == session_id)
            .order_by(CallSegment.segment_number.desc())
            .limit(1)
        )
        last_segment_number = result.scalar_one_or_none()
        segment_number = (last_segment_number or 0) + 1
        segment_id = uuid.uuid4()
        segment = CallSegment(
            id=segment_id,
            session_id=session_id,
            segment_number=segment_number,
            started_at=datetime.now(timezone.utc),
        )
        db.add(segment)
        audio_writers = {
            "mixed": SegmentAudioWriter(session_id, segment_number),
            "mic": SegmentAudioWriter(session_id, segment_number, track="mic"),
            "system": SegmentAudioWriter(session_id, segment_number, track="sys"),
        }

        if last_segment_number is not None:
            sequence = await get_next_sequence(session_id, db)
            marker = TranscriptEntry(
                session_id=session_id,
                text=f"--- Session Resumed (Call {segment_number}) ---",
                sequence=sequence,
            )
            db.add(marker)

        session.state = "active"
        if not session.started_at:
            session.started_at = datetime.now(timezone.utc)
        session.ended_at = None

        await db.commit()
        return segment_id, audio_writers


async def _finalize_call(
    session_id: uuid.UUID,
    websocket: WebSocket,
    diarizer: Any,
    orchestrator: AgentOrchestrator,
    transcription_queue: OrderedTranscriptionQueue,
    audio_writers: dict[str, SegmentAudioWriter | None] | None = None,
    sys_diarizer: Any = None,
    split_track_established: bool = False,
    drain_mode: str = "full",
    call_segment_id: uuid.UUID | None = None,
):
    if drain_mode == "minimal":
        # Disconnect/error path: stop the orchestrator's live analysis tasks
        # before the transcription flush below, so no analysis LLM call can
        # start or continue once the disconnect is detected. A deliberate stop
        # keeps agents running through the flush so the final drain sees the
        # full transcript.
        try:
            await orchestrator.close_all()
        except Exception as e:
            logger.warning(f"Orchestrator shutdown failed during minimal finalize: {e}")

    drain_stages = orchestrator.drain_stages(drain_mode)
    total_steps = 2 + len(drain_stages)
    pipeline_steps = ["speaker_assignment", *drain_stages, "saving_session"]
    await _send_post_processing_status(
        websocket,
        "speaker_assignment",
        "Finalizing speaker assignments...",
        1,
        total_steps,
        drain_progress_percent(1, total_steps),
        steps=pipeline_steps,
    )
    await _flush_remaining_audio(
        diarizer,
        transcription_queue,
        speaker_prefix="mic_" if split_track_established else "",
    )
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

    if drain_mode == "minimal":
        # No analysis passes; the agents were already shut down above. Start
        # from an empty result so transcription stats still reach the client.
        drain_result = {}
    else:
        drain_result = await orchestrator.graceful_drain(
            progress_callback=_forward_drain_progress,
            mode=drain_mode,
        )
        await orchestrator.close_all()

    tq_stats = transcription_queue.stats
    drain_result["transcription"] = tq_stats
    # Anchor the drain counters (insights_saved / synthesizer_ops describe only
    # the final analysis pass) against the session's total insight count so the
    # client can present both without guessing from possibly stale state.
    try:
        async with async_session() as db:
            total_insights = await db.scalar(
                select(func.count())
                .select_from(Question)
                .where(Question.session_id == session_id)
            )
        drain_result["session_insight_total"] = int(total_insights or 0)
    except Exception as e:
        logger.warning(f"Failed to count session insights for the post-processing summary: {e}")
    completion_message = "Post-processing complete"
    # Name the stages that degraded. The call finalizes either way, but silence
    # here is what made a failed briefing read as a stranded call: the user saw
    # the socket drop and a summary that mentioned nothing wrong.
    stage_errors = drain_result.get("stage_errors") or []
    if stage_errors:
        stages = ", ".join(item["stage"].replace("_", " ") for item in stage_errors)
        completion_message = (
            f"Post-processing complete, but {len(stage_errors)} analysis "
            f"stage{'s' if len(stage_errors) != 1 else ''} failed ({stages}); "
            "the call was still saved"
        )
    if tq_stats["failed"]:
        if tq_stats["emitted"] == 0:
            completion_message = (
                "Post-processing complete, but transcription failed for all "
                f"{tq_stats['failed']} speech segments and no transcript text "
                "was saved"
            )
        else:
            completion_message = (
                "Post-processing complete; transcription failed for "
                f"{tq_stats['failed']} of {tq_stats['jobs']} speech segments"
            )

    await _send_post_processing_status(
        websocket,
        "saving_session",
        "Saving completed session...",
        total_steps,
        total_steps,
        drain_progress_percent(total_steps, total_steps),
        details=drain_result,
    )

    async with async_session() as db:
        result = await db.execute(
            select(Session).where(Session.id == session_id).with_for_update()
        )
        session = result.scalar_one_or_none()
        owned_segment = (
            await db.get(CallSegment, call_segment_id)
            if call_segment_id is not None
            else None
        )
        if owned_segment and owned_segment.ended_at is None:
            owned_segment.ended_at = datetime.now(timezone.utc)
            if audio_writers:
                try:
                    for field, path in _close_audio_writers(
                        audio_writers,
                        split_track_established,
                    ).items():
                        setattr(owned_segment, field, path)
                except Exception as e:
                    logger.warning(f"Failed to finalize segment audio: {e}")

        newer_open_segment_id = None
        if owned_segment is not None:
            result = await db.execute(
                select(CallSegment.id)
                .where(
                    CallSegment.session_id == session_id,
                    CallSegment.ended_at.is_(None),
                    CallSegment.segment_number > owned_segment.segment_number,
                )
                .limit(1)
            )
            newer_open_segment_id = result.scalar_one_or_none()

        if session and session.state == "active" and newer_open_segment_id is None:
            session.state = "completed"
            session.ended_at = datetime.now(timezone.utc)
            # Keep the drain outcome with the session. The completion message
            # below only reaches a client that is still connected, and the run
            # that motivated this had the browser drop three minutes before the
            # briefing failed, so the record of what degraded was lost.
            try:
                session.drain_summary = json.dumps(
                    {"message": completion_message, **drain_result},
                    default=str,
                )
            except Exception as e:
                logger.warning(f"Failed to record the drain summary: {e}")
        await db.commit()

    completed_extra: dict[str, Any] = {"details": drain_result}
    await _send_status(
        websocket,
        "completed",
        completion_message,
        stage="complete",
        current_step=total_steps,
        total_steps=total_steps,
        progress=100,
        **completed_extra,
    )


def _create_transcript_emitter(
    session_id: uuid.UUID,
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
    speaker_rows: list[Speaker],
):
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
        speaker_auto_id, split_track_mic = _normalize_speaker_auto_id(speaker_auto_id)
        local_mic_speaker = resolve_live_mic_speaker(speaker_auto_id, speaker_rows, split_track_mic)
        if is_unknown_auto_speaker(speaker_auto_id):
            speaker_id, speaker_name, speaker_type = None, "Unknown", None
        elif local_mic_speaker is not None:
            # Keep the mic ID out of auto_speaker_map so remote ordering remains intact.
            speaker_id, speaker_name, speaker_type = _speaker_identity(local_mic_speaker)
        else:
            if await _should_defer_new_speaker(session_id, speaker_auto_id, auto_speaker_map, pcm_bytes, text):
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

    return _emit_transcript


async def _audio_websocket(websocket: WebSocket, session_id: uuid.UUID):
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
        speaker_rows = list(result.scalars().all())
        speakers_list = [_speaker_context(s) for s in speaker_rows]
        local_voice_embedding = await load_live_mic_voice_embedding(db, speaker_rows)

        agent_configs = await _load_agent_configs(db, session_id)

        runtime_config, transcription_config, local_only, readiness = (
            await _load_audio_runtime(db)
        )

    if not readiness.ready:
        # Restore the row before notifying so the client's refresh reads the
        # corrected state.
        restored = await _restore_session_after_refusal(session_id)
        logger.warning(
            f"Refused call start for session {session_id} "
            f"(restored state: {restored}): {readiness.reason}"
        )
        await _refuse_unready_transcription(websocket, readiness)
        return

    # Track active (unanswered) questions for agent context
    active_questions: list[dict] = list(existing_questions)

    # Which assigned models Privacy First admits. Resolved once here because
    # each endpoint model costs a database read and the orchestrator's gate is
    # synchronous; with the mode off this is every configured model.
    admitted_models = await admitted_model_ids(
        (cfg.model_id for cfg in agent_configs.values() if getattr(cfg, "model_id", "")),
        local_only,
    )

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
        admitted_models=admitted_models,
    )

    # --- Speaker diarization ---
    diarizer, transcriber, create_system_diarizer, batch_model_is_local = (
        _create_audio_processors(
            runtime_config,
            transcription_config,
            session_id,
            local_voice_embedding,
        )
    )

    emit_transcript = _create_transcript_emitter(
        session_id,
        websocket,
        orchestrator,
        speaker_rows,
    )
    transcription_queue = OrderedTranscriptionQueue(
        transcribe=transcriber.transcribe_segment,
        emit=emit_transcript,
        on_failure=_transcription_failure_handler(
            websocket,
            batch_model_is_local,
            orchestrator.activity,
        ),
    )
    await _run_audio_pipeline(
        session_id,
        websocket,
        local_only,
        diarizer,
        orchestrator,
        transcription_queue,
        create_system_diarizer,
        _requested_drain_mode,
        _start_call_segment,
        _finalize_call,
    )


@router.websocket("/ws/{session_id}")
async def audio_websocket(websocket: WebSocket, session_id: uuid.UUID):
    try:
        with runtime_activity.track("active call"):
            await _audio_websocket(websocket, session_id)
    except runtime_activity.ShutdownReserved as exc:
        await websocket.close(code=1013, reason=str(exc))

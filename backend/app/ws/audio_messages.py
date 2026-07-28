import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import Callable
from time import monotonic
from typing import Any

from fastapi import WebSocket

from app.database import async_session
from app.models import Directive
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.audio_store import SegmentAudioWriter
from app.ws.audio_persistence import _append_audio_frames
from app.ws.audio_runtime import (
    _PCM_BYTES_PER_SECOND,
    _QueuedAudioFrame,
    _decode_audio_frame,
    _record_audio_flow,
    _send_gateway_audio,
    _shed_diarization_backlog,
    _send_status,
    _split_track_established_after_frame,
    _split_track_established_after_message,
)

logger = logging.getLogger("app.ws.audio_handler")


async def _handle_audio_frame(
    raw_frame: bytes,
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
    mixer: Any,
    audio_writers: dict[str, SegmentAudioWriter | None] | None,
    queue: asyncio.Queue[_QueuedAudioFrame | None],
    pending_enqueued_at: deque[float],
    state: Any,
) -> bool:
    track, pcm_data = _decode_audio_frame(raw_frame)
    try:
        state.audio_chunks_received += 1
        state.audio_bytes_received += len(pcm_data)
        now = monotonic()
        audio_status_due = now - state.last_audio_status_at >= 5
        if audio_status_due:
            state.last_audio_status_at = now

        mixed_frames = mixer.add(track, pcm_data)
        if mixed_frames:
            mixed, mic, system = mixed_frames
            if audio_writers:
                _append_audio_frames(
                    audio_writers,
                    (mixed, mic, system),
                    state.split_track_established,
                )

        state.split_track_established = _split_track_established_after_frame(
            track,
            state.split_track_established,
        )
        enqueued_at = monotonic()
        pending_enqueued_at.append(enqueued_at)
        queue.put_nowait(
            _QueuedAudioFrame(
                track=track,
                pcm_bytes=pcm_data,
                split_track_established=state.split_track_established,
                enqueued_at=enqueued_at,
            )
        )
        # Bound what a lagging diarizer can accumulate. Shedding the oldest
        # audio costs some speaker attribution; letting it grow costs the whole
        # call, because the process is killed for running out of memory.
        state.diarization_backlog_bytes += len(pcm_data)
        state.diarization_backlog_bytes, dropped = _shed_diarization_backlog(
            queue,
            pending_enqueued_at,
            state.diarization_backlog_bytes,
        )
        if dropped:
            state.diarization_frames_dropped += dropped
            logger.warning(
                "Diarization overloaded: shed %s frame(s), %s total this call. "
                "The diarizer is slower than realtime for this audio.",
                dropped,
                state.diarization_frames_dropped,
            )
            if not state.diarization_overload_notified:
                state.diarization_overload_notified = True
                await _send_status(
                    websocket,
                    "diarization_overloaded",
                    (
                        "Speaker detection is running slower than the call. Some "
                        "audio is being skipped to keep the call alive - speaker "
                        "labels may be incomplete. A lighter diarizer will fix this."
                    ),
                    details={"frames_dropped": state.diarization_frames_dropped},
                )
        if mixed_frames and state.gateway_available:
            state.gateway_available = await _send_gateway_audio(
                orchestrator,
                mixed,
            )
        audio_flow = _record_audio_flow(
            state.audio_bytes_by_track,
            track,
            len(pcm_data),
        )
        if audio_flow:
            mic_seconds, system_seconds = audio_flow
            logger.info(
                (
                    "Audio ingress: mic=%.1fs system=%.1fs "
                    "aggregate_track_seconds=%.1fs backlog=%s"
                ),
                mic_seconds,
                system_seconds,
                mic_seconds + system_seconds,
                len(pending_enqueued_at),
            )
        if audio_status_due:
            await _send_status(
                websocket,
                "audio_received",
                (
                    f"Backend received "
                    f"{state.audio_bytes_received // _PCM_BYTES_PER_SECOND}s "
                    f"audio ({state.audio_chunks_received} chunks)"
                ),
                details={
                    "chunks": state.audio_chunks_received,
                    "bytes": state.audio_bytes_received,
                    "seconds": (
                        state.audio_bytes_received / _PCM_BYTES_PER_SECOND
                    ),
                },
            )
        return True
    except Exception as exc:
        logger.exception("Audio frame handling failed")
        await _send_status(
            websocket,
            "audio_error",
            f"One audio frame could not be processed: {exc}",
            details={"track": track},
        )
        return False


async def _handle_text_message(
    raw_message: str,
    session_id: uuid.UUID,
    orchestrator: AgentOrchestrator,
    state: Any,
    requested_drain_mode: Callable[[dict], str],
) -> None:
    data = json.loads(raw_message)
    state.split_track_established = _split_track_established_after_message(
        data,
        state.split_track_established,
    )
    if data.get("type") == "stop":
        state.stopped = True
        state.stop_drain_mode = requested_drain_mode(data)
    elif data.get("type") == "directive":
        directive_text = data.get("text", "")
        if directive_text:
            async with async_session() as db:
                directive = Directive(session_id=session_id, text=directive_text)
                db.add(directive)
                await db.commit()
            await orchestrator.send_directive(directive_text)

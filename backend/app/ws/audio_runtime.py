import asyncio
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from fastapi import WebSocket

from app.services.agents.orchestrator import AgentOrchestrator
from app.services.diarizer_factory import create_diarizer
from app.services.diarizer_runtime import get_diarizer_runtime_config
from app.services.local_transcriber import create_transcriber
from app.services.privacy import get_local_only, is_local_model
from app.services.speaker_assignment import LOCAL_VOICE_PROFILE_ID
from app.services.speaker_diarizer import SpeakerRegistry
from app.services.transcription_readiness import get_transcription_readiness
from app.services.transcription_runtime import get_transcription_runtime_config

logger = logging.getLogger("app.ws.audio_handler")

_PCM_BYTES_PER_SECOND = 32_000
_AUDIO_FLOW_LOG_INTERVAL_BYTES = 10 * _PCM_BYTES_PER_SECOND
_GATEWAY_SEND_TIMEOUT_SECONDS = 1.0
_DIARIZATION_DRAIN_STATUS_SECONDS = 5.0


def _new_speaker_registry(
    threshold: float,
    local_embedding=None,
) -> SpeakerRegistry:
    registry = SpeakerRegistry(threshold=threshold)
    if local_embedding is not None:
        registry.enroll(
            LOCAL_VOICE_PROFILE_ID,
            local_embedding,
            fallback_for_unmatched=False,
        )
    return registry


async def _load_audio_runtime(db):
    runtime_config = await get_diarizer_runtime_config(db, probe_sortformer=False)
    transcription_config = await get_transcription_runtime_config(db)
    local_only = await get_local_only(db)
    readiness = await get_transcription_readiness(db)
    return runtime_config, transcription_config, local_only, readiness


def _create_audio_processors(
    runtime_config,
    transcription_config,
    session_id: uuid.UUID,
    local_embedding,
):
    diarizer = create_diarizer(
        runtime_config.effective_live_diarizer,
        registry=_new_speaker_registry(
            runtime_config.speaker_similarity_threshold,
            local_embedding,
        ),
    )
    transcriber = create_transcriber(
        transcription_config.batch_model_id,
        session_id=session_id,
    )

    def create_system_diarizer():
        return create_diarizer(
            runtime_config.effective_live_diarizer,
            registry=_new_speaker_registry(
                runtime_config.speaker_similarity_threshold,
            ),
        )

    return (
        diarizer,
        transcriber,
        create_system_diarizer,
        is_local_model(transcription_config.batch_model_id),
    )


@dataclass(frozen=True)
class _QueuedAudioFrame:
    track: int
    pcm_bytes: bytes
    split_track_established: bool
    enqueued_at: float


async def _send_status(
    websocket: WebSocket,
    state: str,
    message: str,
    **extra: Any,
) -> None:
    try:
        await websocket.send_json(
            {
                "type": "status",
                "data": {"state": state, "message": message, **extra},
            }
        )
    except Exception:
        pass


async def _receive_websocket_message(
    websocket: WebSocket,
    session_id: uuid.UUID,
) -> dict | None:
    message = await websocket.receive()
    if message.get("type") != "websocket.disconnect":
        return message
    logger.info(
        "Browser disconnected for session %s: code=%s reason=%s",
        session_id,
        message.get("code"),
        message.get("reason", ""),
    )
    return None


async def _send_gateway_audio(
    orchestrator: AgentOrchestrator,
    pcm_data: bytes,
) -> bool:
    try:
        await asyncio.wait_for(
            orchestrator.send_audio(pcm_data),
            timeout=_GATEWAY_SEND_TIMEOUT_SECONDS,
        )
        return True
    except Exception as exc:
        logger.warning("Audio gateway send failed: %s", exc)
        return False


async def _reconnect_audio_gateway(
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
) -> bool:
    try:
        success = await orchestrator._reconnect_gateway()
        if success:
            await _send_status(websocket, "active", "Reconnected to AI")
        return success
    except Exception as exc:
        logger.error("Audio Gateway reconnect failed: %s", exc)
        return False


def _decode_audio_frame(raw_frame: bytes) -> tuple[int, bytes]:
    if len(raw_frame) % 2 == 0:
        return 0, raw_frame
    track = raw_frame[0] if raw_frame[0] in (0, 1) else 0
    return track, raw_frame[1:]


def _record_audio_flow(
    track_bytes: list[int],
    track: int,
    byte_count: int,
) -> tuple[float, float] | None:
    previous_total = sum(track_bytes)
    track_bytes[track] += byte_count
    current_total = sum(track_bytes)
    if (
        current_total // _AUDIO_FLOW_LOG_INTERVAL_BYTES
        == previous_total // _AUDIO_FLOW_LOG_INTERVAL_BYTES
    ):
        return None
    return (
        track_bytes[0] / _PCM_BYTES_PER_SECOND,
        track_bytes[1] / _PCM_BYTES_PER_SECOND,
    )


def _split_track_established_after_message(data: dict, current: bool) -> bool:
    if data.get("type") == "track_state" and data.get("track") == 1:
        return current or data.get("active") is True
    return current


def _split_track_established_after_frame(track: int, current: bool) -> bool:
    return current or track == 1


def _queued_speaker_auto_id(
    auto_id: str,
    track: int,
    split_track_established: bool,
) -> str:
    return f"mic_{auto_id}" if track == 0 and split_track_established else auto_id


async def _run_diarization_worker(
    queue: asyncio.Queue[_QueuedAudioFrame | None],
    mic_diarizer: Any,
    create_system_diarizer: Callable[[], Any],
    on_segment: Callable[[_QueuedAudioFrame, Any], Awaitable[None]],
    on_error: Callable[[_QueuedAudioFrame, Exception], Awaitable[None]],
    on_item_done: Callable[[_QueuedAudioFrame], None] | None = None,
) -> Any | None:
    system_diarizer = None
    while True:
        item = await queue.get()
        if item is None:
            return system_diarizer
        try:
            diarizer = mic_diarizer
            if item.track == 1:
                if system_diarizer is None:
                    system_diarizer = create_system_diarizer()
                diarizer = system_diarizer
            segments = await asyncio.to_thread(diarizer.feed_audio, item.pcm_bytes)
            for segment in segments:
                await on_segment(item, segment)
            item_age = max(0.0, monotonic() - item.enqueued_at)
            if item_age >= 5.0 or queue.qsize() >= 50:
                logger.info(
                    "Diarization backlog: remaining=%s item_age=%.1fs track=%s",
                    queue.qsize(),
                    item_age,
                    item.track,
                )
        except Exception as exc:
            logger.warning(
                "Diarization failed for queued track %s: %s",
                item.track,
                exc,
            )
            try:
                await on_error(item, exc)
            except Exception:
                logger.warning("Diarization error callback failed", exc_info=True)
        finally:
            if on_item_done is not None:
                try:
                    on_item_done(item)
                except Exception:
                    logger.warning(
                        "Diarization item completion callback failed",
                        exc_info=True,
                    )


async def _stop_diarization_worker(
    websocket: WebSocket,
    queue: asyncio.Queue[_QueuedAudioFrame | None],
    worker_task: asyncio.Task,
    pending_enqueued_at: deque[float],
) -> Any | None:
    queue.put_nowait(None)
    while not worker_task.done():
        done, _ = await asyncio.wait(
            {worker_task},
            timeout=_DIARIZATION_DRAIN_STATUS_SECONDS,
        )
        if done:
            break
        oldest_age = (
            max(0.0, monotonic() - pending_enqueued_at[0])
            if pending_enqueued_at
            else 0.0
        )
        details = {
            "remaining_frames": len(pending_enqueued_at),
            "oldest_age_seconds": round(oldest_age, 1),
        }
        logger.info(
            "Draining diarization backlog: remaining=%s oldest_age=%.1fs",
            details["remaining_frames"],
            oldest_age,
        )
        await _send_status(
            websocket,
            "post_processing",
            "Finishing queued audio before transcription...",
            details=details,
        )
    return await worker_task

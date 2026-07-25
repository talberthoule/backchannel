import asyncio
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from fastapi import WebSocket

from app.services.agents.orchestrator import AgentOrchestrator
from app.services.audio_store import SegmentAudioWriter
from app.services.ordered_transcription import OrderedTranscriptionQueue
from app.services.track_mixer import TrackMixer
from app.ws.audio_messages import _handle_audio_frame, _handle_text_message
from app.ws.audio_runtime import (
    _PCM_BYTES_PER_SECOND,
    _QueuedAudioFrame,
    _queued_speaker_auto_id,
    _receive_websocket_message,
    _reconnect_audio_gateway,
    _run_diarization_worker,
    _send_status,
    _stop_diarization_worker,
)

logger = logging.getLogger("app.ws.audio_handler")

_GATEWAY_RETRY_SECONDS = 5.0


@dataclass
class _AudioPipelineState:
    stopped: bool = False
    stop_drain_mode: str = "full"
    split_track_established: bool = False
    audio_chunks_received: int = 0
    audio_bytes_received: int = 0
    audio_bytes_by_track: list[int] = field(default_factory=lambda: [0, 0])
    last_audio_status_at: float = 0.0
    gateway_available: bool = True
    gateway_reconnect_task: asyncio.Task | None = None
    gateway_retry_at: float = 0.0


async def _maintain_audio_gateway(
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
    state: _AudioPipelineState,
) -> None:
    task = state.gateway_reconnect_task
    if task and task.done():
        try:
            state.gateway_available = bool(task.result())
        except Exception as exc:
            logger.warning("Audio gateway reconnect task failed: %s", exc)
            state.gateway_available = False
        state.gateway_reconnect_task = None
        state.gateway_retry_at = monotonic() + _GATEWAY_RETRY_SECONDS

    if state.gateway_available and not await orchestrator.check_health():
        state.gateway_available = False

    if (
        not state.gateway_available
        and state.gateway_reconnect_task is None
        and monotonic() >= state.gateway_retry_at
    ):
        state.gateway_reconnect_task = asyncio.create_task(
            _reconnect_audio_gateway(websocket, orchestrator)
        )


async def _cancel_gateway_reconnect(state: _AudioPipelineState) -> None:
    task = state.gateway_reconnect_task
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _transcription_failure_handler(
    websocket: WebSocket,
    batch_model_is_local: bool,
):
    last_status_at = 0.0

    async def _on_failure(failed_count: int, kind: str):
        nonlocal last_status_at
        now = monotonic()
        if failed_count > 1 and now - last_status_at < 10:
            return
        last_status_at = now
        plural = "s" if failed_count != 1 else ""
        if kind == "emit":
            message = (
                f"Saving transcript text failed for {failed_count} speech "
                f"segment{plural} this call; transcript entries may be missing."
            )
        elif batch_model_is_local:
            message = (
                f"Local transcription failed for {failed_count} speech "
                f"segment{plural} this call; transcript text may be missing."
            )
        else:
            message = (
                f"Transcription failed for {failed_count} speech segment{plural} "
                "this call; transcript text may be missing. Check the provider "
                "API key in Admin -> API Keys."
            )
        await _send_status(
            websocket,
            "transcription_error",
            message,
            details={"failed": failed_count, "kind": kind},
        )

    return _on_failure


async def _run_audio_pipeline(
    session_id: uuid.UUID,
    websocket: WebSocket,
    local_only: bool,
    diarizer: Any,
    orchestrator: AgentOrchestrator,
    transcription_queue: OrderedTranscriptionQueue,
    create_system_diarizer: Callable[[], Any],
    requested_drain_mode: Callable[[dict], str],
    start_call_segment: Callable[..., Awaitable[Any]],
    finalize_call: Callable[..., Awaitable[None]],
) -> None:
    state = _AudioPipelineState()
    mixer = TrackMixer()
    diarization_queue: asyncio.Queue[_QueuedAudioFrame | None] = asyncio.Queue()
    pending_enqueued_at: deque[float] = deque()

    async def _on_diarized_segment(item: _QueuedAudioFrame, segment: Any):
        speaker_auto_id = (
            f"sys_{segment.speaker_id}"
            if item.track == 1
            else segment.speaker_id
        )
        logger.info(
            "Diarized segment: speaker=%s bytes=%s",
            speaker_auto_id,
            len(segment.pcm_bytes),
        )
        await _send_status(
            websocket,
            "audio_segment",
            (
                f"Queued {len(segment.pcm_bytes) // _PCM_BYTES_PER_SECOND}s "
                "speech segment for transcription"
            ),
            details={
                "speaker_auto_id": speaker_auto_id,
                "bytes": len(segment.pcm_bytes),
            },
        )
        transcription_queue.add(
            _queued_speaker_auto_id(
                speaker_auto_id,
                item.track,
                item.split_track_established,
            ),
            segment.pcm_bytes,
        )

    async def _on_diarization_error(
        item: _QueuedAudioFrame,
        exc: Exception,
    ):
        await _send_status(
            websocket,
            "transcription_error",
            f"Local speaker processing failed for one audio frame: {exc}",
            details={"track": item.track},
        )

    def _on_diarization_item_done(item: _QueuedAudioFrame):
        if pending_enqueued_at:
            pending_enqueued_at.popleft()

    diarization_worker = asyncio.create_task(
        _run_diarization_worker(
            diarization_queue,
            diarizer,
            create_system_diarizer,
            _on_diarized_segment,
            _on_diarization_error,
            _on_diarization_item_done,
        )
    )

    call_segment_id: uuid.UUID | None = None
    audio_writers: dict[str, SegmentAudioWriter | None] | None = None

    try:
        await websocket.send_json(
            {
                "type": "status",
                "data": {
                    "state": "connecting",
                    "message": "Connecting to AI agents...",
                },
            }
        )
        await orchestrator.start()
        active_message = (
            "Listening (Privacy First: local transcription only, cloud AI agents off)..."
            if local_only
            else "Listening..."
        )
        await websocket.send_json(
            {
                "type": "status",
                "data": {"state": "active", "message": active_message},
            }
        )

        segment_start = await start_call_segment(session_id)
        if segment_start is not None:
            call_segment_id, audio_writers = segment_start

        while not state.stopped:
            message = await _receive_websocket_message(websocket, session_id)
            if message is None:
                break

            if "bytes" in message:
                if not await _handle_audio_frame(
                    message["bytes"],
                    websocket,
                    orchestrator,
                    mixer,
                    audio_writers,
                    diarization_queue,
                    pending_enqueued_at,
                    state,
                ):
                    continue
            elif "text" in message:
                await _handle_text_message(
                    message["text"],
                    session_id,
                    orchestrator,
                    state,
                    requested_drain_mode,
                )
                if state.stopped:
                    break
            await _maintain_audio_gateway(websocket, orchestrator, state)

    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        try:
            await websocket.send_json(
                {
                    "type": "status",
                    "data": {"state": "error", "message": str(exc)},
                }
            )
        except Exception:
            pass
    finally:
        await _cancel_gateway_reconnect(state)

        sys_diarizer = None
        try:
            sys_diarizer = await _stop_diarization_worker(
                websocket,
                diarization_queue,
                diarization_worker,
                pending_enqueued_at,
            )
        except Exception:
            logger.exception("Diarization worker failed during shutdown")

        await finalize_call(
            session_id,
            websocket,
            diarizer,
            orchestrator,
            transcription_queue,
            call_segment_id=call_segment_id,
            audio_writers=audio_writers,
            sys_diarizer=sys_diarizer,
            split_track_established=state.split_track_established,
            drain_mode=state.stop_drain_mode if state.stopped else "minimal",
        )

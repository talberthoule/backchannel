import asyncio
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from fastapi import WebSocket

from app.services.agents.activity import ActivityRegistry
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
    # Audio queued for diarization but not yet processed, and how many frames
    # were shed because the diarizer could not keep up (see ALP-153).
    diarization_backlog_bytes: int = 0
    diarization_frames_dropped: int = 0
    diarization_overload_notified: bool = False


async def _maintain_audio_gateway(
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
    state: _AudioPipelineState,
) -> None:
    activity = getattr(orchestrator, "activity", None)
    task = state.gateway_reconnect_task
    if task and task.done():
        try:
            state.gateway_available = bool(task.result())
        except Exception as exc:
            logger.warning("Audio gateway reconnect task failed: %s", exc)
            state.gateway_available = False
        state.gateway_reconnect_task = None
        state.gateway_retry_at = monotonic() + _GATEWAY_RETRY_SECONDS
        if isinstance(activity, ActivityRegistry):
            if state.gateway_available:
                await activity.set_agent_state("audio_gateway", "running")
            else:
                await activity.cycle_error(
                    "audio_gateway",
                    {
                        "kind": "api_error",
                        "detail": "The live transcription gateway reconnect failed.",
                        "remedy": "Check the provider connection, then use Resume Audio.",
                    },
                )
            await activity.update_call(
                gateway={
                    "state": "ok" if state.gateway_available else "reconnecting",
                    "detail": "" if state.gateway_available else "Reconnect failed.",
                }
            )

    if state.gateway_available and not await orchestrator.check_health():
        state.gateway_available = False
        if isinstance(activity, ActivityRegistry):
            await activity.cycle_error(
                "audio_gateway",
                {
                    "kind": "api_error",
                    "detail": "The live transcription gateway stopped responding.",
                    "remedy": "Use Resume Audio to reconnect.",
                },
            )
            await activity.update_call(
                gateway={
                    "state": "reconnecting",
                    "detail": "The live transcription gateway stopped responding.",
                }
            )

    if (
        not state.gateway_available
        and state.gateway_reconnect_task is None
        and monotonic() >= state.gateway_retry_at
    ):
        state.gateway_reconnect_task = asyncio.create_task(
            _reconnect_audio_gateway(websocket, orchestrator)
        )
        if isinstance(activity, ActivityRegistry):
            await activity.update_call(
                gateway={
                    "state": "reconnecting",
                    "detail": "Reconnecting to the live transcription gateway.",
                }
            )


async def _cancel_gateway_reconnect(state: _AudioPipelineState) -> None:
    task = state.gateway_reconnect_task
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _transcription_failure_handler(
    websocket: WebSocket,
    batch_model_is_local: bool,
    activity=None,
):
    last_status_at = 0.0

    async def _on_failure(failed_count: int, kind: str):
        nonlocal last_status_at
        now = monotonic()
        status_throttled = failed_count > 1 and now - last_status_at < 10
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
                "API key in Admin -> Connections."
            )
        if activity:
            await activity.update_call(
                transcription={
                    "failed": failed_count,
                    "last_error": message,
                }
            )
        if status_throttled:
            return
        last_status_at = now
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
        if isinstance(getattr(orchestrator, "activity", None), ActivityRegistry):
            await orchestrator.activity.update_call(
                transcription=transcription_queue.stats
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
        state.diarization_backlog_bytes = max(
            0, state.diarization_backlog_bytes - len(item.pcm_bytes)
        )
        if isinstance(getattr(orchestrator, "activity", None), ActivityRegistry):
            asyncio.create_task(
                orchestrator.activity.update_call(
                    diarization={
                        "queued": max(0, len(pending_enqueued_at)),
                        "shed": state.diarization_frames_dropped,
                    }
                )
            )

    async def _flush_system_track_at_stop() -> None:
        """Finalize track one where the share actually ended.

        Queued rather than run inline so it lands behind the system frames
        already waiting: the tail belongs to the audio before the stop. Without
        this the buffer sat until End Call and surfaced there as a new remote
        speaker minutes after sharing had ended (ALP-103).
        """
        queued_at = monotonic()
        # Balance the backlog deque: the worker pops one entry per item, so a
        # sentinel that skipped this would consume a real frame's entry.
        pending_enqueued_at.append(queued_at)
        diarization_queue.put_nowait(
            _QueuedAudioFrame(
                track=1,
                pcm_bytes=b"",
                split_track_established=True,
                enqueued_at=queued_at,
                flush=True,
            )
        )

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
        # Say what is actually running. With a self-hosted model assigned, the
        # analysis agents do run under Privacy First, and any agent left out is
        # named so nine quiet minutes are never the first sign of a problem.
        blocked = orchestrator.privacy_blocked_agents
        if not local_only:
            active_message = "Listening..."
        elif blocked:
            # The remedy differs per agent (a text agent wants a self-hosted
            # model, the gateway wants the on-device captioner), so name who is
            # paused and let Admin carry the specific fix for each.
            names = ", ".join(b["agent"] for b in blocked)
            active_message = (
                f"Listening (Privacy First: {names} paused, see Admin -> Agents)..."
            )
        else:
            active_message = "Listening (Privacy First: everything running on your network)..."
        await websocket.send_json(
            {
                "type": "status",
                "data": {
                    "state": "active",
                    "message": active_message,
                    "privacy_blocked_agents": blocked,
                },
            }
        )
        if blocked:
            logger.warning(
                "[privacy] session %s: %d agent(s) sat out under Privacy First: %s",
                session_id,
                len(blocked),
                ", ".join(f"{b['agent']}={b['model_id'] or 'unset'}" for b in blocked),
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
                    on_system_track_stopped=_flush_system_track_at_stop,
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

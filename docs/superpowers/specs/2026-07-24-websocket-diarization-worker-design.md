# WebSocket Diarization Worker Design

**Date:** 2026-07-24

**Status:** Approved

## Goal

Keep live call audio connected and recorded when speaker diarization briefly falls behind. Continuity and eventual transcript completeness take priority over momentary live transcript latency.

## Evidence

The same desktop call lost its main audio WebSocket three times:

- 13:02:56, with about 36.6 seconds of processing lag
- 13:21:43, with about 50.0 seconds of processing lag
- 13:38:12, with about 43.8 seconds of processing lag

The backend process, browser tab, database, and provider requests remained healthy. Before each close, the WebSocket receive path awaited local diarization while 100 ms mic and system frames accumulated. The closes clustered around Uvicorn's keepalive window.

The current handler also ignores the first `websocket.disconnect` message. Its next `receive()` call raises `Cannot call "receive" once a disconnect message has been received`, which hides the original close code.

## Design

`audio_websocket` will create one per-call `asyncio.Queue` and one background diarization task.

The WebSocket receive loop will remain responsible for:

1. Receiving and decoding each audio frame.
2. Updating split-track state.
3. Persisting mixed, mic, and system audio immediately.
4. Forwarding mixed audio to the existing live audio gateway.
5. Enqueuing the local diarization item without awaiting inference.

Each queue item will snapshot the track, PCM bytes, and split-track state at arrival time. This preserves the current rule that mic frames received before system capture is established do not get retroactively treated as split-track frames.

The single worker will consume items in arrival order and run the existing mic or system diarizer through `asyncio.to_thread`. Completed segments will enter the existing `OrderedTranscriptionQueue` exactly as they do today. One worker is intentional: it preserves ordering and avoids concurrent access to stateful diarizers.

On deliberate stop or unexpected disconnect, the handler will stop accepting frames, drain the diarization queue, stop the worker, and only then flush the diarizers and drain transcription. Audio is already persisted before queueing, so a slow worker cannot lose the recording.

## Gateway separation

Gemini Live gateway reconnection will no longer flush or reset the local diarizers. The gateway and local speaker pipeline do not share state, and coupling their recovery creates unnecessary local work in the receive path.

Gateway failure will reconnect only the gateway. Diarization failures will be handled inside the worker, logged, and surfaced through the existing status channel without restarting the unrelated gateway.

## Transport hardening

The desktop launcher and source backend startup wrapper will use a 90-second WebSocket ping timeout and a protocol queue large enough for short bursts of dual-track PCM. This is a safety margin, not the primary fix; the receive/worker split removes the observed starvation mechanism.

The handler will recognize `websocket.disconnect` immediately, log its close code, and exit cleanly. It will not perform the second invalid `receive()` call.

## Backlog behavior

The per-call queue will be in memory and preserve every received frame. Temporary backlog is allowed, and live transcripts may lag while the worker catches up. Queue depth and oldest-item age will be logged when lag becomes material so future performance work has direct evidence.

`asyncio.Queue` is sufficient because producer and consumer share one process and one call lifetime. Kafka and Celery are excluded: they would add serialization, broker deployment, retry semantics, and cross-process coordination without solving a requirement this flow has.

## Error handling

- A worker item always calls `task_done`, including on failure, so final draining cannot hang from accounting errors.
- A diarization exception affects that item, reports an actionable status, and leaves later queued audio processable.
- Worker shutdown is awaited before final diarizer flush, preventing concurrent mutation.
- If the browser disconnects, already received audio is drained and saved through the existing minimal finalization path.
- Gateway failure remains independently recoverable.

## Verification

Focused backend tests will prove:

1. A deliberately slow diarizer does not prevent the receive loop from accepting subsequent audio frames.
2. Queue processing preserves frame and transcript-job order.
3. Split-track state is snapshotted per queued frame.
4. Stop and disconnect drain queued audio before final flush.
5. Worker exceptions do not deadlock queue draining.
6. A `websocket.disconnect` message logs its close code and does not produce the misleading second-receive error.
7. Gateway reconnect no longer resets local diarizers.

Desktop and backend startup tests will verify the transport settings. The full backend and desktop `unittest` suites remain the release gate.

A manual dual-track call will verify that audio remains connected through induced slow diarization, recordings contain both tracks, transcripts catch up in order, and normal End Call still completes.

## Deliberate ceiling

The queue is per call and in memory. At approximately 64 KB/s for combined PCM tracks, one minute of total worker stall is about 3.8 MB. This is the smallest reliable design for transient stalls. If real telemetry later shows sustained multi-minute backlog, add disk-backed replay from the already persisted segment audio; do not add a message broker for a single-process stream.

## Non-goals

- Do not change VAD, speaker thresholds, embedding models, transcription models, or insight agents.
- Do not add Kafka, Celery, Redis, or another service.
- Do not add frontend controls or a new live-lag UI in this change.
- Do not parallelize the two stateful diarizers until measurements show the single worker cannot catch up.

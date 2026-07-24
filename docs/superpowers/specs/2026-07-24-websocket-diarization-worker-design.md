# WebSocket Diarization Worker Design

**Date:** 2026-07-24

**Status:** Ready for final review

## Goal

Keep live call audio connected and recorded when speaker diarization or the
optional live gateway briefly falls behind. Continuity and eventual transcript
completeness take priority over momentary live transcript latency.

## Evidence and failure mechanism

The same desktop call lost its main audio WebSocket three times:

| Close | Wall time | Audio processed | Approximate lag |
| --- | ---: | ---: | ---: |
| 13:02:56 | 124.1s | 75.0s | 36.6s |
| 13:21:43 | 761.1s | 700.0s | 50.0s |
| 13:38:12 | 789.1s | 745.0s | 43.8s |

The backend process, browser tab, database, and provider requests remained
healthy. Diarization already runs off the event loop with
`asyncio.to_thread`, but the receive coroutine waits for each inference result
before calling `websocket.receive()` again. This is a sequential receive-path
throughput deficit, not event-loop starvation.

The pinned Uvicorn/websockets stack buffers 32 incoming data messages by
default. Dual-track capture sends about 20 messages per second, so 32 slots
fill in about 1.6 seconds while the receive coroutine is waiting. Once full,
the protocol reader stops consuming all frames, including PONG control frames.
The 20-second keepalive timeout then closes the connection. The final observed
stall was 23.4 seconds, matching that mechanism.

The lag was transient rather than continuously divergent: during the longest
call it repeatedly returned near zero, with about 11.2 seconds of net drift
over 12 minutes. That supports a small in-process backlog rather than a broker.

The handler also ignores the first `websocket.disconnect` message because
Starlette's raw `receive()` returns it instead of raising
`WebSocketDisconnect`. The next `receive()` raises
`Cannot call "receive" once a disconnect message has been received`, hiding
the original close code.

## Receive and diarization design

`audio_websocket` will create one per-call `asyncio.Queue` and one permanent
background diarization task.

For each audio frame, the receive loop will:

1. Receive and decode the frame.
2. Update and snapshot split-track state.
3. Mix and persist the audio immediately.
4. Enqueue the local diarization item without awaiting inference.
5. Forward mixed audio to the optional live gateway with a bounded wait.

Each item will contain the track, PCM bytes, captured split-track state, and
enqueue time. Keeping the PCM in memory is intentional: the active WAV writers
are buffered and open, so offset-based items would require per-frame
flushes/seeks while saving only a few megabytes during the observed transient
backlogs.

The single worker will consume items in arrival order. It alone will create and
mutate the mic and system diarizers, call their existing `feed_audio` methods
through `asyncio.to_thread`, and add completed segments to the existing
`OrderedTranscriptionQueue`. A single worker preserves global transcript-job
order; separate per-track diarizers do not by themselves preserve the order in
which `OrderedTranscriptionQueue.add()` is called.

Ingress audio counters will move to the receive side so they measure accepted
audio rather than completed diarization. Worker logs will separately report
queue depth, oldest-item age, and processed track seconds.

## Split-track persistence

The mixed, mic, and system writers already exist when a call segment starts.
All three aligned outputs from `TrackMixer` will be written from the beginning,
including system silence before system capture begins. If the call never
becomes split-track, finalization will keep the mixed recording and delete the
unused mic/system files as it does today.

This removes `_establish_split_audio_persistence` and its synchronous readback
of the entire mixed WAV when system capture first appears.

## Gateway isolation

The live gateway is optional and must not control call continuity:

- A gateway audio send gets a short timeout. A timeout or send failure marks
  the gateway degraded and returns control to the receive loop. The timeout is
  one second, which bounds a failed send well below the hardened protocol
  buffer.
- At most one reconnect attempt runs in the background. While degraded, gateway
  audio may be skipped; recording and local diarization continue.
- A failed reconnect reports/logs the degraded gateway but does not end the
  call. A later reconnect may restore interim transcription.
- Both current `_reconnect_audio_pipeline` call sites will become gateway-only.
  The helper will no longer receive, flush, reset, or otherwise touch either
  diarizer or the transcription queue.

## Stop, disconnect, and finalization

The raw receive loop will recognize `websocket.disconnect` immediately, log its
code and reason, and exit without a second `receive()`.

On deliberate stop or unexpected disconnect:

1. Stop accepting frames.
2. Put a sentinel in the diarization queue.
3. Await the worker, which processes all items before the sentinel.
4. Only then call `_finalize_call` to flush the diarizers and drain
   transcription.

The sentinel avoids `task_done()`/`join()` accounting and its deadlock failure
mode. The worker shutdown belongs in the handler's `finally` block before
`_finalize_call`, including error exits.

`_start_call_segment` will return the exact `CallSegment` identity with its
writers, and `_finalize_call` will close only that row. A stale disconnect
handler must not select the latest open segment or mark the session completed
when a resumed WebSocket already owns a newer open segment.

While a deliberate End Call drains backlog, the existing post-processing
status channel will report remaining frames and oldest-item age at intervals;
unexpected disconnects will log the same progress. There is no hard drain
deadline in this change. A running `asyncio.to_thread` inference cannot be
stopped safely, and abandoning a finite 45-second backlog would violate the
eventual-completeness goal. If telemetry later shows a truly stuck inference
rather than finite catch-up, the upgrade is bounded cancellation followed by
replay from the already saved WAV.

An item-level diarization exception is logged and surfaced through the existing
status channel, then the worker continues with later items. If the worker itself
fails unexpectedly, finalization records that failure and preserves the raw
recording rather than hanging.

## Transport hardening

All three Uvicorn entry points will use:

- `ws_ping_timeout=90`
- `ws_max_queue=2048`
- `ws_max_size=65536`

At 20 dual-track frames per second, 2048 slots cover about 102 seconds and hold
about 6.6 MB of actual audio frames. The 64 KiB message cap is ample for the
3,201-byte framed audio messages and prevents the larger queue from multiplying
Uvicorn's 16 MiB default message limit into an excessive memory ceiling.

The settings must be applied to the desktop launcher, Docker/source startup
wrapper, and native Windows GPU startup script. They are defense in depth: the
receive/worker split removes the observed backlog, while coherently sized
protocol limits prevent a brief regression from immediately blocking PONG
processing.

## Backlog and broker decision

The per-call application queue is in memory and preserves every received frame.
At about 64 KB/s for both PCM tracks, one minute of worker stall is about
3.8 MB. Queue depth and oldest-item age will make sustained lag visible.

`asyncio.Queue` is sufficient because producer and consumer share one process
and one call lifetime. Kafka, Celery, Redis, and another service are excluded:
they add serialization, deployment, retry, and cross-process coordination
without solving a requirement this flow has. If observed backlog becomes
multi-minute or must survive a backend process crash, replay the already
persisted segment WAV before considering a broker.

## Verification

Focused tests will prove:

1. A deliberately slow diarizer does not stop the receive loop from accepting
   later frames.
2. Worker processing and transcription-job insertion preserve arrival order.
3. Split-track state is snapshotted per queued frame.
4. The sentinel drains queued frames before final diarizer and transcription
   flushes.
5. Item exceptions do not stop later processing or hang finalization.
6. A raw `websocket.disconnect` logs code/reason and causes no second receive.
7. Gateway send timeout, reconnect, and reconnect failure never reset local
   diarizers or end the call.
8. Split-track recordings remain aligned without mixed-WAV readback.
9. A stale disconnect finalizer cannot close a newer resumed call segment or
   mark its active session completed.

Desktop launcher and backend startup tests will verify the protocol settings;
the native GPU command will be covered by a focused source assertion. The full
backend and desktop `unittest` suites remain the release gate.

A manual dual-track call will induce slow diarization and a failed gateway
reconnect. It must remain connected, keep both recordings aligned, catch
transcripts up in order, show drain progress on End Call, and complete normally.

## Non-goals

- Do not change VAD, speaker thresholds, embedding models, transcription
  models, or insight agents.
- Do not add Kafka, Celery, Redis, or another service.
- Do not add frontend controls or a new live-lag UI in this change.
- Do not add per-track workers unless backlog telemetry shows one worker cannot
  recover and the design also assigns a stable global segment order.

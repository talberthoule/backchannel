# WebSocket Protocol

Endpoint: `ws://<host>/ws/{session_id}`
(handler `backend/app/ws/audio_handler.py`, which delegates client JSON
messages to `backend/app/ws/audio_messages.py` and binary audio frame
decoding to `backend/app/ws/audio_runtime.py`; the frontend client is
`frontend/src/hooks/useWebSocket.ts`).

Connecting starts a call: the backend opens a new call segment, marks the
session active, starts the agent orchestrator, and begins accepting audio.
Reconnecting to a completed session resumes it and inserts a
`--- Session Resumed (Call N) ---` marker in the transcript.

## Client to server

### Binary frames (audio)

PCM16, 16 kHz, mono, with a 1-byte track prefix:

```
byte 0:    track id (0x00 = microphone, 0x01 = system/tab audio)
bytes 1..: PCM16 little-endian samples
```

PCM16 payloads are even-length, so the backend uses frame parity to detect
the prefix: odd-length frames are prefixed, even-length frames are treated
as legacy microphone audio without a prefix.

### JSON messages

```json
{"type": "track_state", "track": 1, "active": false}
```

Reports whether system/tab audio is currently active. The backend snapshots
this state when each microphone segment is queued so later transcription does
not change its speaker-routing policy.

```json
{"type": "stop", "drain": "full"}
```

Ends the call. The backend flushes the diarizer, drains in-flight
transcription and agent work, closes the audio recording, marks the session
completed, and reports post-processing progress via `status` messages.

The optional `drain` field selects how much post-call analysis runs:

- `"full"` (default, and the behavior of a bare `{"type": "stop"}`): final
  insight pass, insight reconciliation, opportunity matching, and briefing
  synthesis.
- `"skip_analysis"`: final insight pass and insight reconciliation only;
  briefing synthesis and opportunity matching are skipped. The briefing can
  be generated later with `POST /api/sessions/{id}/synthesis/refresh`.

Unknown values fall back to `"full"`. If the socket disconnects or errors
without a stop message, the backend runs a minimal drain instead: it flushes
and transcribes buffered audio, closes the recording, and completes the
session with no analysis agent calls. Per-agent enablement still applies
within every mode.

```json
{"type": "directive", "text": "Focus on pricing objections"}
```

Adds a mid-call directive: persisted to the database and injected into agent
context immediately.

## Server to client

All server messages are JSON with a `type` and a `data` payload.

### `status`

Connection and pipeline state. Sent for connection lifecycle
(`connecting`, `active`, `error`), audio flow heartbeats
(`audio_received` roughly every 5 seconds, `audio_segment` when a diarized
segment is queued, `transcript_saved` after persistence), and staged
post-processing progress after stop (`post_processing` with `stage`,
`current_step`, `total_steps`, `progress`, then a final `completed`). The
first post-processing status also carries `steps`, the ordered stage ids for
the selected drain mode, so the client can render the correct pipeline.

The late post-processing statuses and the final `completed` status carry a
`details` object summarizing the final analysis pass: `insights_saved` (new
insights created by the final insight pass), `synthesizer_ops` (updates
applied to already-saved insights), `opportunity_ops` (offering matches
applied), `transcription` (queue stats), and `session_insight_total` (the
session's total insight count at drain completion, so clients can anchor the
pass counters against the lifetime total).

```json
{"type": "status", "data": {"state": "active", "message": "Listening..."}}
```

### `agent_activity`

A coalesced snapshot of live agent status, emitted by the orchestrator's
activity registry (`backend/app/services/agents/activity.py`) at most every
~2 seconds, immediately on errors, blocks, and degradation changes. `data`
carries `session_id`, `at`, an `agents` array (per agent: `slug`, `state`,
`blocked_reason` / `remedy`, last run timing, `next_due_at`, `last_outcome`,
`last_error`, and cumulative `counts` of runs, insights, deduped items, and
errors), and a `call` health block: `privacy_first`, `degraded`,
`degraded_reasons`, plus `gateway` (`ok` / `reconnecting` / `off` with
detail), `transcription` (job and failure stats), and `diarization`
(queued and shed frame counts).

### `interim_transcript`

Low-latency unattributed text from the audio gateway (Gemini Live, OpenAI
Realtime, or the on-device local captioner selected as `local-parakeet-live`,
`backend/app/services/local_live_captioner.py`). Display-only; superseded by
`transcript` messages.

```json
{"type": "interim_transcript", "data": {"text": "so in terms of timeline we were hoping"}}
```

### `transcript`

A final, speaker-attributed transcript entry, already persisted.

```json
{
  "type": "transcript",
  "data": {
    "id": "6a2f...",
    "session_id": "9b1c...",
    "text": "We were hoping to launch before the end of the quarter.",
    "timestamp": "2026-07-04T17:03:21.512000+00:00",
    "sequence": 42,
    "speaker_id": "d41d..."
  }
}
```

### `question`

A new insight of any item type -- the field name is historical. `data`
carries the persisted insight including `item_type` (`question`,
`observation`, `opportunity`, `objection`, `action_item`), the content
fields, and `agent_source`. The frontend stores all of these in its
`Question` shape (`frontend/src/types/index.ts`).

### `question_answered`

The synthesizer detected that an open question was answered in conversation.
`data` identifies the question and the answer evidence.

### `insight_updated`

The synthesizer revised an existing insight (content enrichment,
consolidation with a near-duplicate, or an opportunity gaining offering
matches). `data` is the updated insight.

### `insight_elevated`

The synthesizer elevated an item to a different type (for example an
observation reclassified as an opportunity). `data` is the updated insight.

### `synthesis_updated`

The session synthesis was regenerated: by the strategic signals agent during
the call (this is how live Strategic Signals card updates reach the browser)
or by briefing synthesis at call end
(`_send_synthesis_update` in `backend/app/services/agents/orchestrator.py`).
`data` is the full persisted synthesis, the same shape
`GET /api/sessions/{id}/synthesis` returns (`SessionSynthesis` in
`frontend/src/types/index.ts`), with one deliberate omission: kept signals
arrive as a `signal_history_count` only, never as rows. The count is what the
History control needs; the rows are fetched on demand from
`GET /api/sessions/{id}/synthesis?include_history=true`, so a long call does
not push its whole signal history down the socket every cycle.

## Ordering and delivery notes

- `transcript` messages are emitted in original audio order even though
  transcription is concurrent (`OrderedTranscriptionQueue`).
- `interim_transcript` text can arrive before, after, or interleaved with
  the `transcript` entries covering the same speech; treat it as ephemeral.
- If the audio gateway connection drops, the backend reconnects it
  transparently and emits `status` state changes; buffered diarized audio is
  flushed into the transcription queue first, so no attributed transcript is
  lost.

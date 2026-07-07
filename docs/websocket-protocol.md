# WebSocket Protocol

Endpoint: `ws://<host>/ws/{session_id}`
(`backend/app/ws/audio_handler.py`; the frontend client is
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
{"type": "stop"}
```

Ends the call. The backend flushes the diarizer, drains in-flight
transcription and agent work, closes the audio recording, marks the session
completed, and reports post-processing progress via `status` messages.

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
`current_step`, `total_steps`, `progress`, then a final `completed`).

```json
{"type": "status", "data": {"state": "active", "message": "Listening..."}}
```

### `interim_transcript`

Low-latency unattributed text from the audio gateway (Gemini Live or OpenAI
Realtime). Display-only; superseded by `transcript` messages.

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

## Ordering and delivery notes

- `transcript` messages are emitted in original audio order even though
  transcription is concurrent (`OrderedTranscriptionQueue`).
- `interim_transcript` text can arrive before, after, or interleaved with
  the `transcript` entries covering the same speech; treat it as ephemeral.
- If the audio gateway connection drops, the backend reconnects it
  transparently and emits `status` state changes; buffered diarized audio is
  flushed into the transcription queue first, so no attributed transcript is
  lost.

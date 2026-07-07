# Meetily-Inspired Feature Set — Design Spec

Date: 2026-07-03
Status: Approved (design presented and user directed continuation)
Branch: `claude/merrily-comparison-kzbh27`

## Goal

Adopt the practically valuable ideas from Meetily (Zackriya-Solutions/meetily)
into Call Helper without abandoning its server-based, real-time architecture:
system-audio capture, persisted call audio with re-transcription, provider
abstraction for both text and realtime-audio LLM calls, an optional local
Whisper/Parakeet batch transcriber, chat over stored meeting transcripts, and
an admin surface for encrypted workspace API keys.

## Decisions already made (user-confirmed)

- API keys are **global workspace keys** (one per provider per install), not
  per-user. No user accounts are introduced.
- Local ASR targets **auto-detect** hardware: CPU by default, NVIDIA GPU via
  the existing `docker-compose.gpu.yml` overlay.
- System audio is sent **dual-track** (mic and system audio as separate
  streams), not premixed in the browser.
- Interim (live) transcription supports **Gemini Live and OpenAI Realtime**.
- Local Whisper/Parakeet is an **option**; Gemini Flash remains the default
  batch transcriber.
- Chat-with-meetings is provider-abstracted and can include transcripts from
  other sessions (same group or any session).

## Sub-projects and build order

Each sub-project ships independently; order chosen so foundations land first.

1. Encrypted workspace API keys + provider registry/LLM router
2. Persist call audio + re-transcription
3. Local Whisper/Parakeet batch transcription option
4. Interim provider abstraction (Gemini Live | OpenAI Realtime)
5. Dual-track system audio capture
6. Chat with meetings

---

## 1. Encrypted workspace API keys + provider abstraction

### Credentials

- New dependency: `cryptography` (Fernet). The only new security-critical dep.
- Master key: read from env `CREDENTIALS_MASTER_KEY` if set; otherwise
  auto-generated on first startup and stored at `/app/data/master.key`
  (new named Docker volume `backend_data` mounted at `/app/data`). File mode
  0600. The master key never lives in the database.
- Ciphertext storage: reuse the existing `app_settings` table with keys
  `credentials.<provider>.api_key` (providers: `google`, `openai`). Values are
  Fernet tokens.
- New module `backend/app/services/secrets.py`:
  - `get_secret(db, key) -> str` — decrypts; returns `""` when unset.
  - `set_secret(db, key, value)` — encrypts and upserts; empty value deletes.
  - `get_provider_key(db, provider) -> str` — resolves the workspace key,
    falling back to env (`GEMINI_API_KEY` for `google`, `OPENAI_API_KEY` for
    `openai`) so existing installs keep working with zero migration.
- REST (in a new `backend/app/routers/credentials.py`):
  - `GET /api/credentials` → `[{provider, configured: bool, masked: "sk-...abc"}]`
    (never returns plaintext).
  - `PUT /api/credentials/{provider}` body `{api_key}` → store encrypted.
  - `DELETE /api/credentials/{provider}` → remove.
  - `POST /api/credentials/{provider}/test` → one cheap live call
    (Gemini: `models.list`; OpenAI: `GET /v1/models`) returning
    `{ok, message}`.
- Admin UI: new "API Keys" card in `AdminPanel.tsx` — per provider: masked
  status, password input, Save, Test, Remove. No new page/route.

### Provider registry + text-LLM router

- `MODEL_REGISTRY` entries gain a machine-usable `provider` semantic:
  existing `provider: "Google"` plus new OpenAI entries
  (`provider: "OpenAI"`), e.g. `gpt-5`, `gpt-5-mini` with
  `supports_text: true`, and `gpt-realtime` with `supports_live_audio: true`.
  A `requires_key: "google" | "openai" | null` field states which credential
  a model needs (`null` for local models added in sub-project 3).
- New module `backend/app/services/llm.py` with one entry point:
  - `async generate_text(model_id, prompt, *, system=None, temperature=None) -> str`
  - Routes by registry provider: Google → existing `google-genai` client;
    OpenAI → `httpx` POST to `https://api.openai.com/v1/chat/completions`
    (no `openai` SDK; `httpx` is already installed as a FastAPI/starlette
    transitive dependency).
  - Reads the API key via `get_provider_key`. Raises a clear error naming the
    missing credential when unset.
- Call sites switched to `generate_text`: `consolidated_analyst.py`,
  `synthesizer.py`, `opportunity_specialist.py`, `analyze.py`, and the
  briefing synthesis path. `batch_transcriber.py` (audio) stays on
  `google-genai` directly.
- Fix while in the area: `routers/agents.py` model validation currently
  accepts any id containing the substring `"preview"`; tighten to
  registry-ids-only.

## 2. Persist call audio + re-transcription

- During a live call, every mic-track PCM chunk is appended to
  `/app/data/audio/<session_id>/segment_<n>.wav` (header finalized on segment
  close). Dual-track (sub-project 5) writes the system track to
  `segment_<n>_sys.wav`.
- Schema: `call_segments.audio_path` (nullable String) — added via Alembic
  migration `012_add_call_segment_audio_path` AND `_add_missing_columns()`
  in `main.py` (repo requires both mechanisms).
- Audio imports also persist their converted PCM the same way, so imported
  sessions are re-transcribable too.
- REST:
  - `GET /api/sessions/{id}/segments/{segment_number}/audio` → `audio/wav`
    file response (404 when absent).
  - `POST /api/sessions/{id}/retranscribe` body `{model_id}` → replays each
    stored segment WAV through diarization + the chosen transcriber,
    deletes the session's prior transcript entries, writes new ones, returns
    `{entries: n}`. Runs synchronously (per-session audio is bounded; the
    frontend shows a progress state).
- UI: PostCallView transcript tab gets a native `<audio>` element per call
  segment (browser plays WAV natively) and a "Re-transcribe" button with a
  model picker (batch-capable models only) and a confirm step (destructive
  to existing transcript entries).
- Storage note: WAV at 16 kHz mono ≈ 115 MB/hour. Acceptable for a local
  box; no compression/retention policy until disk pressure is real.

## 3. Local Whisper/Parakeet batch transcription

- New dependency: `onnx-asr` (pure-Python ONNX ASR loader; no torch). Runs on
  the already-installed `onnxruntime`; GPU acceleration comes from the
  existing `docker-compose.gpu.yml` overlay with `onnxruntime-gpu` via a
  build arg (mirrors the `INSTALL_SORTFORMER` pattern).
- Registry additions (`requires_key: null`, `supports_batch_audio: true`):
  - `local-whisper-base` (multilingual, light)
  - `local-parakeet-tdt-0.6b` (English, fast, high accuracy)
  Model weights download on first use into `/app/data/asr-models/` (same
  volume; survives container rebuilds).
- New `backend/app/services/local_transcriber.py`:
  `class LocalTranscriber` with the same surface as `BatchTranscriber`
  (`async transcribe_segment(pcm_bytes) -> str | None`), sharing the existing
  energy/hallucination/min-word filters (extracted, not duplicated).
  Inference runs in a thread executor to keep the event loop free.
- Selection: `transcription_runtime.get_transcription_runtime_config`
  already resolves `transcription.batch.model_id`; a small factory returns
  `LocalTranscriber` for `local-*` ids, `BatchTranscriber` otherwise.
  `audio_handler.py` and the retranscribe endpoint use the factory.
- Admin: the existing `BatchTranscriptionCard` model picker simply lists the
  new entries; a note shows download-on-first-use.

## 4. Interim provider abstraction (Gemini Live | OpenAI Realtime)

- New `backend/app/services/openai_realtime.py`:
  `class OpenAIRealtimeSession` with the same surface as `GeminiLiveSession`
  (`connect() / send_audio(bytes) / receive_responses() / close()`).
  Implementation: `websockets` (already a direct dependency) to
  `wss://api.openai.com/v1/realtime?intent=transcription`; sends
  `input_audio_buffer.append` frames (base64 PCM16 16 kHz), yields
  transcription delta/completed events as the same
  `{"type": "transcript", "data": text}` dicts GeminiLiveSession yields.
- Orchestrator: constructs the gateway session by the `audio_gateway`
  agent's `model_id` provider (registry lookup) — `gemini-*-live*` → Gemini,
  `gpt-realtime` → OpenAI. No other orchestrator changes; health-check and
  reconnect logic treat both identically.
- Admin: the audio_gateway model picker (existing AdminPanel agent row)
  lists both live-capable models.

## 5. Dual-track system audio capture

- WS protocol change (the only one): every binary frame is prefixed with
  **1 byte**: `0x00` = mic, `0x01` = system audio. Frontend always sends the
  prefix; backend requires it. (Atomic frontend+backend deploy; no
  mixed-version tolerance needed on a single box.)
- Frontend (`useAudioCapture.ts`):
  - Mic path unchanged (worklet → 1600-sample chunks).
  - `startCapture` gains an option to also request
    `getDisplayMedia({audio: true, video: true})` (video track immediately
    stopped; Chrome requires requesting it). If the user declines or the
    browser/tab has no audio, capture proceeds mic-only.
  - The system stream runs through a second instance of the same worklet;
    chunks are delivered with track id. `useWebSocket.sendAudio` prepends
    the track byte.
  - ActiveCall/PreCall UI: a "Capture meeting audio (tab/system)" toggle;
    when active, a second level indicator.
- Backend (`audio_handler.py`):
  - Splits frames by track byte. Mic track: existing flow (diarizer A).
    System track: second diarizer instance (diarizer B) whose auto-IDs are
    namespaced `sys_<auto_id>` before entering the shared resolution path;
    speakers first seen on the system track are created with
    `speaker_type="external"` and names "Remote Participant N".
  - Interim gateway receives a server-side mix: int16 add with clamp,
    chunk-aligned (both tracks are 1600-sample frames; buffer the laggard,
    flush on either stream idle >200 ms).
  - Audio persistence (sub-project 2) writes each track to its own WAV.
  - `_flush_remaining_audio` and finalize flush both diarizers.

## 6. Chat with meetings

- REST: `POST /api/chat` body
  `{model_id, session_ids: [uuid], messages: [{role, content}]}` →
  `{reply}`. Stateless: no chat tables; the frontend owns history in memory.
  Backend loads the named sessions' transcripts (speaker-attributed, with
  session name/date headers), truncating oldest-first past a character
  budget, prepends a system prompt, and calls `llm.generate_text`.
- UI: new "Chat" tab in PostCallView. Minimal picker above the thread:
  current session pre-checked; sessions in the same group listed as
  checkboxes; a search box (reuses `GET /api/sessions`) to add any other
  session. Model selector defaults to the consolidated analyst's model.
- No persistence, no RAG/vector store: transcripts fit the context window at
  current sizes; revisit only when a real limit is hit.

## Error handling (cross-cutting)

- Missing credential → 400 with `"No API key configured for <provider>; add
  one in Admin → API Keys"` (surfaced as-is by the UI).
- Local model download failure → transcriber raises; live path falls back to
  the seeded Gemini default and emits a status message; retranscribe returns
  the error.
- `getDisplayMedia` denial → mic-only capture with a non-blocking notice.
- Realtime gateway errors → existing reconnect path (both providers).
- Decryption failure (master key changed) → treat credential as unset and
  log a warning naming the key file.

## Testing

Repo has no test framework; per ponytail each non-trivial unit ships one
small runnable check under `backend/tests/` executed with plain
`python -m pytest`-free asserts (`python backend/tests/check_x.py`):
secrets round-trip, WS frame prefix split, llm router dispatch (mocked HTTP),
chat prompt assembly/truncation, WAV append/finalize. Frontend changes are
verified by `npm run build` (typecheck) as today.

## Out of scope (explicitly)

- User accounts / per-user keys (workspace keys only, revisit with
  local-vs-public architecture).
- Chat history persistence, RAG/vector search.
- Audio compression/retention policies.
- Abstracting the batch Gemini audio transcriber behind `llm.py` (audio
  inline-data APIs are provider-specific; local ASR covers the alternative).

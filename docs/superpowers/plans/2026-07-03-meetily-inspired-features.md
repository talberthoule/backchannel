# Meetily-Inspired Feature Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add encrypted workspace API keys, provider-abstracted LLM calls (text + realtime interim), persisted call audio with re-transcription, optional local Whisper/Parakeet batch ASR, dual-track system-audio capture, and chat-with-meetings.

**Architecture:** Keep the existing FastAPI + React + PostgreSQL shape. New capability lands behind existing seams: `app_settings` for encrypted credentials, `MODEL_REGISTRY` for provider metadata, `transcription_runtime` for batch-model selection, the orchestrator's gateway slot for realtime providers, a 1-byte track prefix on WS binary frames for dual-track audio.

**Tech Stack:** cryptography (Fernet), httpx (OpenAI chat), websockets (OpenAI Realtime), onnx-asr + onnxruntime (local ASR), google-genai (existing).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-03-meetily-inspired-features-design.md`.
- New columns go in BOTH an Alembic migration and `_add_missing_columns()` in `backend/app/main.py`.
- Plaintext API keys never leave the backend (`GET /api/credentials` returns masked values only).
- Gemini stays the default everywhere; env `GEMINI_API_KEY` keeps working with zero migration.
- ASCII-only in new code. No test framework; checks are standalone `python backend/tests/check_*.py` scripts with asserts.
- Frontend verification is `npm run build` (typecheck) in `frontend/`.
- Commit after every task: `git commit` per task, descriptive message.

---

## Phase 1 — Encrypted workspace API keys + LLM router

### Task 1.1: Secrets module + Docker data volume

**Files:**
- Create: `backend/app/services/secrets.py`
- Create: `backend/tests/check_secrets.py`
- Modify: `backend/requirements.txt` (add `cryptography==44.0.0`)
- Modify: `docker-compose.yml` (add `backend_data` volume mounted at `/app/data` on backend)

**Interfaces:**
- Produces: `get_secret(db, key) -> str`, `set_secret(db, key, value) -> None`,
  `get_provider_key(db, provider) -> str` (provider in `{"google", "openai"}`,
  env fallback GEMINI_API_KEY / OPENAI_API_KEY), `DATA_DIR: Path` (env
  `DATA_DIR`, default `/app/data`, test-overridable).

- [ ] Step 1: Write `check_secrets.py` — round-trip encrypt/decrypt against a temp key file and an in-memory fake db (monkeypatch `get_app_setting`/`set_app_setting`); assert masked never contains plaintext; assert env fallback works.
- [ ] Step 2: Implement `secrets.py`: master key from env `CREDENTIALS_MASTER_KEY` else keyfile `DATA_DIR/master.key` (create 0600 on first use); Fernet encrypt into `app_settings` keys `credentials.<provider>.api_key`; decrypt failure logs warning and returns `""`.
- [ ] Step 3: Run `python backend/tests/check_secrets.py` — expect `OK`.
- [ ] Step 4: Add volume to docker-compose.yml; commit.

### Task 1.2: Credentials REST API

**Files:**
- Create: `backend/app/routers/credentials.py`
- Modify: `backend/app/main.py` (include router)

**Interfaces:**
- Produces: `GET /api/credentials` → `[{provider, configured, masked}]`;
  `PUT /api/credentials/{provider}` body `{"api_key": str}`;
  `DELETE /api/credentials/{provider}`;
  `POST /api/credentials/{provider}/test` → `{"ok": bool, "message": str}`.
- Test endpoints: google → `genai.Client(api_key=k).aio.models.list()`;
  openai → httpx GET `https://api.openai.com/v1/models` with bearer.

- [ ] Step 1: Implement router (providers fixed list `["google", "openai"]`, 404 on other slugs; masked = first 4 + "..." + last 4, or "" if len < 12).
- [ ] Step 2: Verify import: `python -c "from app.main import app"` inside backend env. Commit.

### Task 1.3: Registry provider metadata + llm router

**Files:**
- Create: `backend/app/services/llm.py`
- Create: `backend/tests/check_llm_router.py`
- Modify: `backend/app/config.py` (add `requires_key` to all entries; add OpenAI text models `gpt-5`, `gpt-5-mini`; add live model `openai-realtime`)
- Modify: `backend/app/routers/agents.py:47-51` (drop `"preview"` substring loophole; validate against registry ids only)

**Interfaces:**
- Produces: `async generate_text(model_id: str, prompt: str, *, system: str | None = None, temperature: float | None = None) -> str`;
  `registry_entry(model_id) -> dict | None`; `provider_for(model_id) -> str` ("google" default for unknown gemini-* ids).
- OpenAI path: httpx POST `/v1/chat/completions`, messages = optional system + user prompt, returns `choices[0].message.content`.
- Google path: `genai.Client(api_key=...).aio.models.generate_content(model=model_id, contents=prompt, config=GenerateContentConfig(system_instruction=system, temperature=temperature))`.
- Raises `LLMKeyMissing(provider)` (ValueError subclass) with message "No API key configured for <provider>; add one in Admin -> API Keys".

- [ ] Step 1: Write `check_llm_router.py` — dispatch table test with mocked transports; key-missing raises; unknown model errors.
- [ ] Step 2: Implement; run check — `OK`. Commit.

### Task 1.4: Switch text call sites to generate_text

**Files:**
- Modify: `backend/app/services/agents/consolidated_analyst.py`, `synthesizer.py`, `opportunity_specialist.py`, `backend/app/routers/analyze.py`, briefing synthesis service (locate `genai.Client` usages via grep; leave audio paths untouched)

- [ ] Step 1: Replace direct `genai` text calls with `llm.generate_text`, preserving prompts/config semantics.
- [ ] Step 2: `python -c "from app.main import app"`; grep to confirm no text-agent file still constructs `genai.Client`. Commit.

### Task 1.5: Admin API Keys card

**Files:**
- Create: `frontend/src/components/ApiKeysCard.tsx`
- Modify: `frontend/src/services/api.ts` (credentials endpoints), `frontend/src/components/AdminPanel.tsx` (render card)

- [ ] Step 1: api.ts: `listCredentials/saveCredential/deleteCredential/testCredential`.
- [ ] Step 2: Card: per provider row — status (configured + masked), password input, Save/Test/Remove buttons, inline result message. Match AdminPanel's existing card styling.
- [ ] Step 3: `npm run build` passes. Commit.

## Phase 2 — Persist call audio + re-transcription

### Task 2.1: WAV appender + audio_path column

**Files:**
- Create: `backend/app/services/audio_store.py`
- Create: `backend/tests/check_audio_store.py`
- Create: `backend/alembic/versions/012_add_call_segment_audio_path.py`
- Modify: `backend/app/models.py` (CallSegment.audio_path nullable String(500)), `backend/app/main.py` `_add_missing_columns` (call_segments.audio_path)

**Interfaces:**
- Produces: `class SegmentAudioWriter(session_id, segment_number, track="mic")` with
  `append(pcm_bytes)`, `close() -> str | None` (returns relative path, None if no audio written).
  Files at `DATA_DIR/audio/<session_id>/segment_<n>[_sys].wav`; header written
  up front with placeholder sizes, patched on close via `struct.pack` seek.
  `audio_file_path(session_id, segment_number, track) -> Path`.

- [ ] Step 1: check script — append two chunks, close, re-open with `soundfile` and assert sample count and rate 16000.
- [ ] Step 2: Implement; run check — `OK`.
- [ ] Step 3: Migration + `_add_missing_columns` entry. Commit.

### Task 2.2: Record during live calls + serve audio

**Files:**
- Modify: `backend/app/ws/audio_handler.py` (create writer with the CallSegment, append mic PCM in the binary branch, close + save path in `_finalize_call`)
- Modify: `backend/app/routers/sessions.py` or new `backend/app/routers/segments.py`: `GET /api/sessions/{id}/segments/{n}/audio` → `FileResponse(audio/wav)`, 404 if absent

- [ ] Step 1: Wire writer into audio_handler (mic track only until Phase 5).
- [ ] Step 2: Endpoint + import check. Commit.

### Task 2.3: Re-transcription endpoint

**Files:**
- Create: `backend/app/routers/retranscribe.py` (`POST /api/sessions/{id}/retranscribe` body `{"model_id": str}`)
- Modify: `backend/app/main.py` (include router)

**Interfaces:**
- Consumes: stored segment WAVs; `create_diarizer`; transcriber factory (Task 3.2 — until then instantiate `BatchTranscriber(model_id=...)` directly and refactor in 3.2).
- Behavior: reject non-batch-capable model ids (registry check); load each segment WAV in order, run diarizer.feed_audio in 100 ms chunks + flush, transcribe segments, delete prior `TranscriptEntry` rows for the session, insert new ones with fresh sequences mapped through the existing auto-speaker resolution (reuse `resolve_existing_auto_speaker` flow simplified: create "Participant N" speakers as needed); returns `{"entries": n}`; 409 if session state is `active`; 404 if no stored audio.

- [ ] Step 1: Implement endpoint.
- [ ] Step 2: Import check; commit.

### Task 2.4: PostCallView playback + re-transcribe UI

**Files:**
- Modify: `frontend/src/services/api.ts` (`segmentAudioUrl`, `retranscribe`), `frontend/src/components/PostCallView.tsx` (transcript tab: `<audio controls src=...>` per call segment with audio; Re-transcribe button + model select + confirm)

- [ ] Step 1: Implement; models listed from existing `api.listModels()` filtered `supports_batch_audio`.
- [ ] Step 2: `npm run build`. Commit.

## Phase 3 — Local Whisper/Parakeet batch ASR

### Task 3.1: LocalTranscriber

**Files:**
- Create: `backend/app/services/local_transcriber.py`
- Modify: `backend/requirements.txt` (add `onnx-asr>=0.7`), `backend/app/config.py` (registry entries `local-whisper-base`, `local-parakeet-tdt-0.6b`, `requires_key: None`, `supports_batch_audio: True`), `backend/app/services/batch_transcriber.py` (export the shared filters `_audio_has_speech_energy`, `_is_hallucination`, `_MIN_WORD_COUNT` for reuse — move to module functions if not already)

**Interfaces:**
- Produces: `class LocalTranscriber(model_id)` with `async transcribe_segment(pcm_bytes) -> str | None` (same contract as BatchTranscriber). Maps `local-whisper-base` → onnx-asr `"whisper-base"`, `local-parakeet-tdt-0.6b` → `"nemo-parakeet-tdt-0.6b-v2"`. Loads lazily once per process into module cache dir `DATA_DIR/asr-models`; inference via `asyncio.to_thread`; input converted with existing `pcm16_to_float32`.

- [ ] Step 1: Implement with shared pre/post filters.
- [ ] Step 2: `python -c "import app.services.local_transcriber"`. Commit.

### Task 3.2: Transcriber factory + wiring

**Files:**
- Create: `backend/app/services/transcriber_factory.py` (`create_transcriber(model_id)` → LocalTranscriber for `local-*`, else BatchTranscriber)
- Modify: `backend/app/ws/audio_handler.py:258`, `backend/app/routers/retranscribe.py` (use factory), `backend/app/services/transcription_runtime.py` (accept `local-*` ids as valid)

- [ ] Step 1: Implement + wire both call sites; import check. Commit.
- [ ] Step 2: Verify `BatchTranscriptionCard` picker lists new models (it reads `/api/models`; confirm filter includes them); adjust if it filters by provider. `npm run build`. Commit.

### Task 3.3: Optional GPU runtime

**Files:**
- Modify: `backend/Dockerfile` (build arg `ONNX_GPU=false` → pip install `onnxruntime-gpu` when true), `docker-compose.gpu.yml` (set `ONNX_GPU: "true"`)

- [ ] Step 1: Implement; note in file comment that onnx-asr auto-selects CUDA provider when available. Commit.

## Phase 4 — Interim provider abstraction (OpenAI Realtime)

### Task 4.1: OpenAIRealtimeSession

**Files:**
- Create: `backend/app/services/openai_realtime.py`
- Create: `backend/tests/check_realtime_resample.py`

**Interfaces:**
- Produces: `class OpenAIRealtimeSession(api_key)` with `connect()`, `send_audio(pcm16_16k: bytes)`, `receive_responses()` async-gen yielding `{"type": "transcript", "data": text}`, `close()` — mirror of `GeminiLiveSession`.
- Protocol: `websockets.connect("wss://api.openai.com/v1/realtime?intent=transcription", additional_headers={"Authorization": "Bearer ..."})`; on open send `transcription_session.update` with `input_audio_format: "pcm16"`, `input_audio_transcription: {"model": "gpt-4o-transcribe"}`, `turn_detection: {"type": "server_vad"}`; audio frames as `{"type": "input_audio_buffer.append", "audio": base64}`; yield text from `conversation.item.input_audio_transcription.completed` events (`transcript` field), ignore deltas.
- Resample 16 k→24 k with numpy `np.interp` (OpenAI pcm16 is 24 kHz) — that is the check script's target.

- [ ] Step 1: check script: resample 16000 samples → 24000, endpoints preserved.
- [ ] Step 2: Implement; run check `OK`; import check. Commit.

### Task 4.2: Orchestrator gateway selection

**Files:**
- Modify: `backend/app/services/agents/orchestrator.py:124-125` (construct gateway by provider of `audio_gateway` model_id: `openai-realtime` → OpenAIRealtimeSession with key from `get_provider_key`, else GeminiLiveSession), `backend/app/services/gemini_live.py` (accept api_key param, default settings fallback)

- [ ] Step 1: Implement selection; missing key → skip gateway with status log (mirrors current disabled behavior).
- [ ] Step 2: Import check; confirm AdminPanel audio_gateway model picker shows both live models via registry. Commit.

## Phase 5 — Dual-track system audio capture

### Task 5.1: Frontend dual-track capture + prefixed frames

**Files:**
- Modify: `frontend/src/hooks/useAudioCapture.ts` (option `captureSystemAudio`; second stream via `getDisplayMedia({audio: true, video: true})`, stop video track; second worklet; `onChunk(chunk, track)` where track is 0|1; graceful mic-only fallback on denial)
- Modify: `frontend/src/hooks/useWebSocket.ts` `sendAudio(data, track = 0)` — prepend 1-byte prefix (`new Uint8Array(1 + n)`)
- Modify: `frontend/src/App.tsx` / `ActiveCallView`/`PreCallView` (toggle "Capture meeting audio (tab/system)", second level indicator, pass option through)

- [ ] Step 1: Implement hooks; `npm run build`. Commit.
- [ ] Step 2: UI toggle + indicator; `npm run build`. Commit.

### Task 5.2: Backend track demux + dual diarizers + gateway mix

**Files:**
- Create: `backend/app/services/track_mixer.py` (`class TrackMixer`: `add(track, pcm) -> bytes | None` int16 sum-with-clamp on 3200-byte frames, buffers laggard, flushes solo track when other idle > 200 ms)
- Create: `backend/tests/check_track_mixer.py`
- Modify: `backend/app/ws/audio_handler.py` (first byte = track; track 0 → diarizer A + mic WAV writer; track 1 → diarizer B with auto-ids namespaced `sys_<id>` + sys WAV writer; mixer output → `orchestrator.send_audio`; byte-rate status math unchanged minus prefix; flush both diarizers in finalize)
- Modify: speaker auto-create path — speakers first seen from `sys_` ids get name "Remote Participant N", `speaker_type="external"` (already the default; only the name prefix differs)

- [ ] Step 1: check_track_mixer — aligned frames sum/clamp; solo-track flush after idle. Run `OK`.
- [ ] Step 2: Wire audio_handler; frames without prefix byte are rejected (log once). Import check. Commit.

## Phase 6 — Chat with meetings

### Task 6.1: Chat endpoint

**Files:**
- Create: `backend/app/routers/chat.py` (`POST /api/chat`)
- Create: `backend/tests/check_chat_prompt.py`
- Modify: `backend/app/main.py` (include router)

**Interfaces:**
- Request: `{"model_id": str, "session_ids": [uuid], "messages": [{"role": "user"|"assistant", "content": str}]}` → `{"reply": str}`.
- Builds context: per session, header `## <name> (<started_at date>)` + speaker-attributed lines `Name: text` ordered by sequence; total budget 60000 chars, truncate oldest sessions first with a `[truncated]` marker; system prompt instructs answering only from provided transcripts; prior messages included as conversation; final call via `llm.generate_text` (history folded into the prompt for the single-string interface).
- 400 on empty session_ids or non-text model.

- [ ] Step 1: check_chat_prompt — budget truncation + speaker attribution assembly (pure function `build_chat_prompt(sessions_data, messages, budget)` exported for the check).
- [ ] Step 2: Implement; run check `OK`; import check. Commit.

### Task 6.2: Chat tab UI

**Files:**
- Modify: `frontend/src/components/PostCallView.tsx` (add `"chat"` to Tab union + tab bar), `frontend/src/services/api.ts` (`chat`, reuse `listSessions`)
- Create: `frontend/src/components/MeetingChat.tsx`

- [ ] Step 1: MeetingChat: message thread (in-memory state), input box, session picker (current pre-checked; same-group sessions listed; search adds any session), model select defaulting to consolidated analyst's model (from `api.listAgents`). Send → `api.chat`.
- [ ] Step 2: `npm run build`. Commit.

## Final

- [ ] Update CLAUDE.md snapshot sections touched by this work (WS protocol, agents/admin, REST surface, environment: `CREDENTIALS_MASTER_KEY`, `OPENAI_API_KEY`, `DATA_DIR`).
- [ ] Full pass: backend import check, all `backend/tests/check_*.py`, `npm run build`.
- [ ] Push branch `claude/merrily-comparison-kzbh27`.

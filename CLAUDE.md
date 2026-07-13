# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Current Codebase Snapshot

Backchannel (formerly Call Helper) is a real-time meeting analysis app. A React frontend captures microphone audio (and optionally tab/system audio) as PCM16 16 kHz mono and streams it over WebSocket with a 1-byte track prefix. The FastAPI backend writes speaker-attributed transcript entries, records per-segment call audio to disk, runs provider-routed analysis agents (Gemini or OpenAI) over recent transcript text, and stores insights in PostgreSQL.

Backend tests live in `backend/tests/` as stdlib `unittest` files; run them from `backend/` with `python -m unittest discover -s tests`. Frontend behavior checks are `npm run build` (typecheck).

## Build & Run

### Sentrux Structural Analysis

Sentrux is installed at `C:/Users/thoule/.local/bin/sentrux.exe` and configured as a Codex MCP server in `C:/Users/thoule/.codex/config.toml`.

```bash
sentrux .              # Open the GUI for this repo
sentrux check .        # Enforce .sentrux/rules.toml
sentrux gate .         # Compare current structure against .sentrux/baseline.json
sentrux gate --save .  # Refresh the structural baseline after intentional architecture changes
```

Current baseline quality is `6142`, with coupling `0.54`, `0` cycles, and `0` god files. The rules are calibrated to the existing codebase; tighten `max_cc`, `max_fn_lines`, and `max_file_lines` after refactoring current hotspots.

### Docker Compose (primary)

```bash
docker-compose up --build
docker-compose down -v
```

- Frontend: http://localhost:3000
- Backend container: http://localhost:8001
- Frontend nginx proxies API and WebSocket traffic from :3000 to backend :8000
- Database: PostgreSQL 16 on host port 5432

### Multi-target releases

Releases span source-built Docker images, the Cloudflare documentation site,
and tag-built Linux x64, macOS arm64, and Windows x64 desktop bundles. Follow
`docs/releasing.md` and the private R2 manifests as the authoritative checklist
and catalog. A `master` push does not update existing desktop downloads. The tag
workflow publishes verified executables to R2; GitHub releases keep source tags
and notes only, with no executable files.

The checked-in `scripts/r2-object.mjs` client is the sole release object
transport. Do not publish release objects with Amazon Web Services command-line
tools or SDKs.

### Desktop bundle (Linux/macOS/Windows)

`desktop/` contains a PyInstaller launcher that runs the backend with an
embedded zonky.io PostgreSQL and serves the built frontend via
`FRONTEND_DIST`. Desktop tests: run `python -m unittest discover -s tests`
from `desktop/`. Local build: `pyinstaller desktop/backchannel.spec`;
release builds produce a portable Linux x64 tarball plus macOS arm64 and
Windows x64 zip bundles in `.github/workflows/desktop-release.yml` on `v*`
tags (unsigned; Sortformer and ffmpeg are not bundled).

### Docs Site

`docs-site/` is an Astro Starlight project deployed as a Cloudflare Worker
(`backchannel-site`, same pattern as the quartermaster repo) by
`.github/workflows/deploy-site.yml`: the `site/` landing page at
https://backchannel.page/ and the docs at `/docs/`.
The same Worker serves the D1 review/mutation console only on
`https://admin.backchannel.page/` and the authenticated recipient portal on
`https://downloads.backchannel.page/`. Cloudflare Access protects the complete
admin hostname, and the Worker independently verifies the Access JWT issuer,
audience, and exact `ADMIN_EMAIL`; those values are encrypted Worker secrets.
The admin API reviews interests and releases and performs approval, rejection,
grant replacement, password reset, and revocation. D1 owns recipient accounts,
grants, sessions, and access events; recipient identity is not the local
application's PostgreSQL identity. Never log subscriber, credential, session,
Access, or R2 data. Run every `docs-site` release-access, migration, Worker,
admin, download, and site test plus its build before release changes.

```bash
cd docs-site
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
npm run build
```
`docs/*.md` stays the source of truth: do not
edit `docs-site/src/content/docs/` (generated, gitignored). At build time
`docs-site/sync-docs.mjs` copies the docs in, derives frontmatter titles from
each H1, and rewrites `.md` cross-links to page URLs. Build check:
`cd docs-site && npm run build`; local preview: `npm run dev`.

### Local Development

```bash
# Frontend
cd frontend
npm install
npm run dev

# Backend
cd backend
pip install -r requirements.txt
python scripts/download_models.py
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Local frontend development expects the Vite dev proxy in `frontend/vite.config.ts` for `/api` and `/ws`.

AMD GPUs cannot be used from Docker on Windows. `backend/scripts/setup_windows_gpu.ps1` sets up a native Python 3.12 backend venv with AMD's ROCm torch wheels (auto-detected by `backend/scripts/install_sortformer.py`); `-Run` starts the compose db plus a native backend on :8000. See docs/deployment.md "AMD GPU on Windows".

Audio file import uses `soundfile` first and falls back to `ffmpeg` for formats such as MP3 and M4A. If audio import fails locally, verify `ffmpeg` is installed and on `PATH`.

### Database Migrations

```bash
cd backend
alembic upgrade head
alembic downgrade -1
```

The app also runs `Base.metadata.create_all()` on startup and `_add_missing_columns()` in `backend/app/main.py` to patch older local databases. Alembic migrations exist, but startup schema patching is part of the current runtime behavior.

## Runtime Architecture

### Live Call Path

1. Browser audio capture (`frontend/src/hooks/useAudioCapture.ts`) gets mic audio via `getUserMedia`, converts it to PCM16 16 kHz chunks, and sends binary WebSocket frames.
2. WebSocket handler (`backend/app/ws/audio_handler.py`) receives `/ws/{session_id}` traffic, updates session/call-segment state, and sends the same audio into two backend paths.
3. Speaker diarization (`backend/app/services/speaker_diarizer.py`) uses Silero VAD and WeSpeaker ONNX speaker embeddings to segment speech and assign auto speaker IDs.
4. Batch transcription (`backend/app/services/batch_transcriber.py`) wraps each diarized segment as WAV and sends it to Gemini Flash for final transcript text. Low-energy segments, known phantom phrases, and single-word outputs are filtered.
5. Transcript entries are saved to PostgreSQL and sent to the frontend as `transcript` WebSocket messages.
6. Agent orchestration (`backend/app/services/agents/orchestrator.py`) feeds final transcript text into a shared in-memory transcript buffer for text agents.

### Interim Audio Gateway Path

`backend/app/services/gemini_live.py` opens a Gemini Live session as a silent listener. It relays `input_transcription` events to the frontend as `interim_transcript` messages. This is an audio gateway only; analysis is handled by text agents over saved transcript text.

The seeded default live model is currently `gemini-3.1-flash-live-preview`.

## Agent System

Agents are coordinated by `AgentOrchestrator` and configured by `agent_configs` plus optional per-session rows in `session_agent_overrides`.

| Agent slug | Type | Trigger | Code | Purpose |
| --- | --- | --- | --- | --- |
| `audio_gateway` | audio | Continuous audio stream | `backend/app/services/gemini_live.py` / `backend/app/services/openai_realtime.py` | Silent live listener (Gemini Live or OpenAI Realtime, chosen by the agent's model) for interim transcription |
| `consolidated_analyst` | text | Interval, default 15s | `backend/app/services/agents/consolidated_analyst.py` | Single Gemini call that can produce questions, observations, opportunities, and action items |
| `objection_handler` | text | Interval, default 5s, over only the last ~90s of transcript | `backend/app/services/agents/objection_handler.py` | Low-latency objection scan; each `objection` insight pairs an immediate suggested response (micro) with the underlying concern and strategic angle (macro). Skips the LLM call when the window is unchanged |
| `synthesizer` | meta | `new_insight` / `insight_updated` events, 30s cooldown, 120s max interval | `backend/app/services/agents/synthesizer.py` | Reconciles and enriches saved insights, detects answered questions, may elevate item type |
| `opportunity_specialist` | db | `new_opportunity` events, 5s batch window | `backend/app/services/agents/opportunity_specialist.py` | Matches opportunity insights against the configured knowledge sources (offerings catalog by default) |

Important: there is no standalone `question_hunter.py` in the current tree. Question generation is one enabled lens of `ConsolidatedAnalystAgent`; `question_hunter` only appears as a backward-compatible `agent_source` label for exported/saved question items.

Deduplication is in `orchestrator.py` and uses simple word-overlap similarity within a 60-second sliding window.

## Audio Pipeline Details

Values come from `backend/app/config.py`:

- `VAD_THRESHOLD`: 0.6
- `MIN_SEGMENT_MS`: 750
- `MAX_SEGMENT_MS`: 15000
- `SILENCE_GAP_MS`: 600
- `SPEAKER_SIMILARITY_THRESHOLD`: 0.68
- `MIN_NEW_SPEAKER_MS`: 4000
- `MAX_SPEAKER_PROFILES_PER_TRACK`: 4

ONNX models are expected at `backend/models/silero_vad.onnx` and `backend/models/voxceleb_resnet152_LM.onnx` (WeSpeaker ResNet152-LM speaker embeddings; the legacy `ecapa_tdnn.onnx` file - which actually held WeSpeaker ResNet34-LM - is used as a fallback when the new file is absent); use `backend/scripts/download_models.py` to fetch them. Embedding features are Kaldi fbank via `kaldi-native-fbank` with mean-only CMN, matching WeSpeaker's training frontend.

Live call audio (mixed mic + system tracks) is appended to `DATA_DIR/audio/<session_id>/segment_<n>.wav` (`backend/app/services/audio_store.py`, `call_segments.audio_path`). Batch transcription routes through `create_transcriber` (`backend/app/services/local_transcriber.py`): `local-*` model ids run ONNX Whisper/Parakeet locally via `onnx-asr` (weights download to `DATA_DIR/asr-models/` on first use), everything else goes to Gemini. Text LLM calls route through `backend/app/services/llm.py` by the model's registry provider.

## WebSocket Protocol

Endpoint: `/ws/{session_id}`

Client sends:

- Binary frames: 1-byte track prefix (`0x00` mic, `0x01` system audio) + PCM16 16 kHz mono audio chunk. Legacy even-length frames without a prefix are treated as mic audio.
- `{"type": "stop"}`: end the call
- `{"type": "directive", "text": "..."}`: add a mid-call directive

Server sends:

- `{"type": "status", "data": {"state": "...", "message": "..."}}`
- `{"type": "interim_transcript", "data": {"text": "..."}}`
- `{"type": "transcript", "data": {"text": "...", "timestamp": "...", "speaker_id": "..."}}`
- `{"type": "question", "data": {...}}` for all insight item types
- `{"type": "question_answered", "data": {...}}`
- `{"type": "insight_updated", "data": {...}}`
- `{"type": "insight_elevated", "data": {...}}`

The frontend stores all insight item types in the `Question` shape for historical reasons. Check `frontend/src/types/index.ts` before renaming fields.

## REST API Surface

Primary route modules:

- Sessions/groups: `backend/app/routers/sessions.py`, `backend/app/routers/groups.py`
- Directives/documents/speakers/transcripts/questions: per-session CRUD routers
- Agents/models: global agent config, model registry, and per-session agent overrides
- Offerings: offering catalog CRUD, CSV/XLSX import, and seed endpoint
- Imports: transcript file import (`.txt`, `.md`, `.docx`) and audio import (`.m4a`, `.mp3`, `.wav`, `.ogg`, `.flac`)
- Analyze: post-import transcript analysis through Gemini
- Artifacts: transcript TXT, insights XLSX, and summary HTML exports
- Credentials: `GET/PUT/DELETE /api/credentials[/{provider}]` and `POST /api/credentials/{provider}/test` for encrypted workspace API keys (providers: `google`, `openai`)
- Re-transcription: `POST /api/sessions/{id}/retranscribe` replays stored segment audio through any batch-capable model (destructive to existing transcript entries); `GET /api/sessions/{id}/segments/{n}/audio` serves the recorded WAV
- Chat: `POST /api/chat` answers questions over selected sessions' transcripts via the provider-routed text LLM

## Frontend Structure

Main state lives in `frontend/src/App.tsx`.

- `PreCallView`: session setup, speaker setup, directives, document upload, transcript/audio import, per-session agent selection
- `ActiveCallView`: live call controls, transcript/interim transcript display, insight list, audio indicator, mid-call directive bar
- `PostCallView`: review tabs for insights, transcript, speakers, documents, and directives; supports resume, export, delete, and speaker rename
- Admin surfaces: `AdminPanel` for global agent model/prompt/interval config and `OfferingsManager` for catalog management

Hooks:

- `useSession`: loads session metadata, directives, documents, questions, call segments, and speakers
- `useWebSocket`: manages `/ws/{session_id}` JSON and binary traffic
- `useAudioCapture`: mic capture, audio level, PCM16 conversion
- `useSpeechRecognition`: browser STT fallback hook; currently not central to the main live transcript path

## Backend Structure

Key files:

| Area | File |
| --- | --- |
| FastAPI app and startup schema patching | `backend/app/main.py` |
| WebSocket live-call handler | `backend/app/ws/audio_handler.py` |
| SQLAlchemy models | `backend/app/models.py` |
| Pydantic schemas | `backend/app/schemas.py` |
| Settings/model registry | `backend/app/config.py` |
| Session helpers | `backend/app/services/session_manager.py` |
| Diarization | `backend/app/services/speaker_diarizer.py` |
| Batch transcription | `backend/app/services/batch_transcriber.py` |
| Gemini Live gateway | `backend/app/services/gemini_live.py` |
| Gemini Files upload/summarization | `backend/app/services/gemini_files.py` |
| Agent orchestrator | `backend/app/services/agents/orchestrator.py` |
| Consolidated text analyst | `backend/app/services/agents/consolidated_analyst.py` |
| Objection handler | `backend/app/services/agents/objection_handler.py` |
| Synthesizer | `backend/app/services/agents/synthesizer.py` |
| Opportunity specialist | `backend/app/services/agents/opportunity_specialist.py` |
| Default agent seed data | `backend/app/services/seed_agents.py` |

## Environment

API keys can be set per provider in Admin -> API Keys (encrypted with Fernet; master key auto-generated at `DATA_DIR/master.key`, overridable via `CREDENTIALS_MASTER_KEY`). Env vars remain fallbacks:

- `GEMINI_API_KEY` (Google fallback)
- `OPENAI_API_KEY` (OpenAI fallback)
- `DATA_DIR` (default `/app/data`; a `backend_data` Docker volume in compose)

Database variables are optional in Docker because defaults are provided:

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

`DATABASE_URL` is set by Docker Compose for the backend container. For local backend runs, set it if your PostgreSQL host differs from the default in `backend/app/config.py`.

## Known Documentation/Code Questions

- `backend/app/config.py` still contains legacy-looking toggles such as `AGENT_QUESTION_HUNTER_ENABLED` and `AGENT_CONSOLIDATED_ENABLED`; the current orchestrator primarily uses database `AgentConfig` rows and only falls back to some subtype flags.
- Batch transcription defaults are configured through `BATCH_TRANSCRIBER_MODEL` and the persisted `transcription.batch.model_id` app setting.
- Several source files and existing docs contain non-ASCII punctuation in comments/strings. New edits should stay ASCII unless the surrounding file already requires otherwise.

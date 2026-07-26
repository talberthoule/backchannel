# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with this repository.

## Current Codebase Snapshot

Backchannel (formerly Call Helper) is a real-time meeting analysis app. A React frontend captures microphone audio as PCM16 16 kHz mono and streams it over WebSocket. The FastAPI backend writes speaker-attributed transcript entries, runs Gemini-based analysis agents over recent transcript text, and stores insights in PostgreSQL.

Backend tests live in `backend/tests/` as stdlib `unittest` files; run them from `backend/` with `python -m unittest discover -s tests`. Desktop tests use the same runner from `desktop/`, and frontend behavior checks use `npm run build` for typechecking and bundling.

## Build & Run

### Sentrux Structural Analysis

Sentrux is installed at `C:/Users/thoule/.local/bin/sentrux.exe` and configured as a Codex MCP server in `C:/Users/thoule/.codex/config.toml`.

```bash
sentrux .              # Open the GUI for this repo
sentrux check .        # Enforce .sentrux/rules.toml
sentrux gate .         # Compare current structure against .sentrux/baseline.json
sentrux gate --save .  # Refresh the structural baseline after intentional architecture changes
```

Current baseline quality is `6468`, with coupling `0.09`, `0` cycles, `1` god file, and `27` complex functions. The rules are calibrated to the existing codebase; tighten `max_cc`, `max_fn_lines`, and `max_file_lines` after refactoring current hotspots.

The baseline records the Sentrux, plugin, and source revisions used to generate it. `sentrux check .` is expected to report only the two approved generated lockfile exceptions documented next to `max_file_lines` in `.sentrux/rules.toml`; any other finding must be fixed before the baseline is refreshed.

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
`docs/releasing.md` and run `scripts/release_desktop.ps1 -Version vX.Y.Z` from
clean synchronized `master`. The coordinator builds Windows and Linux locally
and dispatches the credential-free macOS build. A fresh protected macOS runner
restores its exact checksum-verified cache handoff and publishes it; a separate
secret-free cleanup job deletes the exact cache ID. Each smoke-tested platform
is published independently through immutable progressive R2 metadata. Historical
aggregate manifests remain supported, but aggregate and progressive metadata
must not coexist for one version. A `master` push does not update existing
desktop downloads. GitHub releases keep source tags and notes only.

The checked-in `scripts/r2-object.mjs` client is the sole release object
transport. Do not publish release objects with Amazon Web Services command-line
tools or SDKs.

### Docs site and private admin

`docs-site/` builds the public `backchannel.page` site and the private
`admin.backchannel.page` operator console and authenticated
`downloads.backchannel.page` recipient portal. Early access owns request and
consent review plus approve/reject only. Users owns recipient identity state,
password reset, session sign-out, and revoke. Authorization owns Latest and
explicit-version grants only, stored in `release_access_policies` and
`release_account_versions`; the old `/api/admin/access/*` routes are removed.

Every request to the private admin host is Cloudflare Access protected and
then checked again by the Worker for a valid issuer, audience, and exact
`ADMIN_EMAIL`; all three settings are Worker secrets. D1 holds recipient
accounts, grants, sessions, and access events; recipient identity is not the
local application's PostgreSQL identity. Never add a public admin route,
commit an operator identity, or log subscriber, credential, session, Access,
or R2 data. Run the six focused `docs-site` suites, aggregate suite, and build
before release changes.

```bash
cd docs-site
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
node --test *.test.js
npm run build
```

For local admin interaction checks, `npm run preview:admin` serves deterministic
fake `.example` recipients on `http://127.0.0.1:4175`; the preview harness is
source-only and must never enter `dist-site`.

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
3. Speaker diarization (`backend/app/services/speaker_diarizer.py`) uses Silero VAD and ECAPA-TDNN ONNX embeddings to segment speech and assign auto speaker IDs.
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
| `consolidated_analyst` | text | Interval, default 40s, plus final pass | `backend/app/services/agents/consolidated_analyst.py` | Single Gemini call that can produce questions, observations, opportunities, and action items |
| `objection_handler` | text | Interval, default 10s over the last 90s | `backend/app/services/agents/objection_handler.py` | Flags objections with an immediate response and strategic context |
| `synthesizer` | meta | `new_insight` / `insight_updated` events, 75s cooldown, 120s fallback | `backend/app/services/agents/synthesizer.py` | Reconciles and enriches saved insights, detects answered questions, may elevate item type |
| `opportunity_specialist` | db | `new_opportunity` events, 55s cooldown, plus final matching | `backend/app/services/agents/opportunity_specialist.py` | Matches opportunity insights against the configured knowledge sources |
| `strategic_signals` | meta | Interval, default 45s during the call | `backend/app/services/agents/strategic_signals.py` | Produces the live strategic cards and evidence links that automatically upvote supported insights |
| `brief_meeting_lens` | meta | Full End Call or on demand | `backend/app/services/briefing_synthesis.py` | Drafts the factual meeting record |
| `brief_discovery_lens` | meta | Full End Call or on demand | `backend/app/services/briefing_synthesis.py` | Drafts the discovery and sensemaking view |
| `brief_arbiter` | meta | After the post-call lens drafts | `backend/app/services/briefing_synthesis.py` | Reconciles both drafts into the settled briefing |

Important: there is no standalone `question_hunter.py` in the current tree. Question generation is one enabled lens of `ConsolidatedAnalystAgent`; `question_hunter` only appears as a backward-compatible `agent_source` label for exported/saved question items.

Deduplication is in `orchestrator.py` and uses simple word-overlap similarity within a 60-second sliding window.

The briefing trio is post-call only. Normal **End Call** runs it, **End without briefing** skips it, and **Generate Briefing** runs it on demand. The standalone `strategic_signals` agent owns the live strategic cards.

## Audio Pipeline Details

Values come from `backend/app/config.py`:

- `VAD_THRESHOLD`: 0.6
- `MIN_SEGMENT_MS`: 750
- `MAX_SEGMENT_MS`: 15000
- `SILENCE_GAP_MS`: 600
- `SPEAKER_SIMILARITY_THRESHOLD`: 0.68
- `MIN_NEW_SPEAKER_MS`: 4000
- `MAX_SPEAKER_PROFILES_PER_TRACK`: 4

ONNX models are expected at `backend/models/silero_vad.onnx` and `backend/models/ecapa_tdnn.onnx`; use `backend/scripts/download_models.py` to fetch them.

## WebSocket Protocol

Endpoint: `/ws/{session_id}`

Client sends:

- Binary frames: PCM16 16 kHz mono audio chunks
- `{"type": "track_state", "track": 1, "active": false}`: system-audio capture state
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

## Frontend Structure

Main state lives in `frontend/src/App.tsx`.

- `PreCallView`: session setup, speaker setup, directives, document upload, transcript/audio import, per-session agent selection
- `ActiveCallView`: live call controls, transcript/interim transcript display, insight list, audio indicator, mid-call directive bar
- `PostCallView`: review tabs for insights, transcript, speakers, documents, and directives; supports resume, export, delete, and speaker rename
- Admin surfaces: `AdminPanel` for global agent model/prompt/interval config and `OfferingsManager` for catalog management

Hooks:

- `useSession`: loads session metadata, directives, documents, questions, call segments, and speakers
- `useWebSocket`: manages `/ws/{session_id}` JSON and binary traffic
- `useAudioCapture`: single-flight mic/system capture, audio levels, PCM16 conversion
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
| Synthesizer | `backend/app/services/agents/synthesizer.py` |
| Opportunity specialist | `backend/app/services/agents/opportunity_specialist.py` |
| Live strategic signals | `backend/app/services/agents/strategic_signals.py` |
| Post-call briefing synthesis | `backend/app/services/briefing_synthesis.py` |
| Default agent seed data | `backend/app/services/seed_agents.py` |

## Environment

Required:

- `GEMINI_API_KEY` (or an OpenAI key for OpenAI-routed agents)

Local ONNX transcription needs no key, and no local registry entry sets
`supports_text` -- so local analysis runs through the `openai-compatible`
provider (Ollama, LM Studio, vLLM), not through those transcription models.
Configure its base URL in Admin -> Connections or via `OPENAI_BASE_URL`. Without
it, the analysis agents require a Google or OpenAI key. Note that the Privacy
First switch gates on `provider != "local"` and so still disables the agents
even when the endpoint is local.

Database variables are optional in Docker because defaults are provided:

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

`DATABASE_URL` is set by Docker Compose for the backend container. For local backend runs, set it if your PostgreSQL host differs from the default in `backend/app/config.py`.

## Known Documentation/Code Questions

- `backend/app/config.py` still contains legacy-looking toggles such as `AGENT_QUESTION_HUNTER_ENABLED` and `AGENT_CONSOLIDATED_ENABLED`; the current orchestrator primarily uses database `AgentConfig` rows and only falls back to some subtype flags.
- Batch transcription defaults are configured through `BATCH_TRANSCRIBER_MODEL` and the persisted `transcription.batch.model_id` app setting.
- `useSession` does not currently fetch transcript entries, while `PostCallView` receives `liveTranscripts` from the current app session. Confirm whether post-call transcript review should persist across page reloads by calling `GET /api/sessions/{session_id}/transcripts`.
- Several source files and existing docs contain non-ASCII punctuation in comments/strings. New edits should stay ASCII unless the surrounding file already requires otherwise.

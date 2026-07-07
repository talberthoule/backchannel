# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with this repository.

## Current Codebase Snapshot

Backchannel (formerly Call Helper) is a real-time meeting analysis app. A React frontend captures microphone audio as PCM16 16 kHz mono and streams it over WebSocket. The FastAPI backend writes speaker-attributed transcript entries, runs Gemini-based analysis agents over recent transcript text, and stores insights in PostgreSQL.

The codebase currently has no test framework configured. Treat behavior checks as targeted build/import checks unless you add tests for the work at hand.

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
| `audio_gateway` | audio | Continuous audio stream | `backend/app/services/gemini_live.py` | Silent Gemini Live listener for interim transcription |
| `consolidated_analyst` | text | Interval, default 15s | `backend/app/services/agents/consolidated_analyst.py` | Single Gemini call that can produce questions, observations, opportunities, and action items |
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
- `SPEAKER_SIMILARITY_THRESHOLD`: 0.72

ONNX models are expected at `backend/models/silero_vad.onnx` and `backend/models/ecapa_tdnn.onnx`; use `backend/scripts/download_models.py` to fetch them.

## WebSocket Protocol

Endpoint: `/ws/{session_id}`

Client sends:

- Binary frames: PCM16 16 kHz mono audio chunks
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
| Synthesizer | `backend/app/services/agents/synthesizer.py` |
| Opportunity specialist | `backend/app/services/agents/opportunity_specialist.py` |
| Default agent seed data | `backend/app/services/seed_agents.py` |

## Environment

Required:

- `GEMINI_API_KEY`

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

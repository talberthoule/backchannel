# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Coordination Record

The durable record for this repository is Linear: team `Alpha`, project `Backchannel`, issue IDs `ALP-NNN`. Findings, verdicts, decisions and their rationale, blockers, and declined alternatives go there; Herdr `agent send` carries only the issue ID and one line of what changed. Because the Linear MCP server writes with a single shared credential, every agent's issue and comment is authored by the human who owns the token, so record `Requested by` / `Performed by` / `Date` / `Scope` in the body. Branches are `agent/alp-NNN-slug`; design docs live in `docs/superpowers/specs/` and plans in `docs/superpowers/plans/`. See the Routing Substance and Pointers section of the `coordinating-herdr-agents` skill.

Git worktrees live **outside** this checkout, at `C:/work/backchannel/<lane>`: `git worktree add C:/work/backchannel/<lane> -b agent/alp-NNN-slug master`. This repository sits in a OneDrive-synced folder, and sync repeatedly stripped the `.git` file out of worktrees created under `.worktrees/`, orphaning them from `git worktree list` while leaving the directories behind (ALP-139). Do not recreate `.worktrees/` here. Note also that the Docker Compose stack binds the main checkout, so a worktree suits docs, review, and analysis rather than work needing integration testing.

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
clean synchronized `master`. The coordinator builds Windows and Linux locally,
dispatches macOS, and publishes each smoke-tested platform independently using
immutable progressive R2 metadata. Historical aggregate manifests remain
supported, but mixed progressive and aggregate metadata for one version is
invalid. A `master` push does not update existing desktop downloads. GitHub
releases keep source tags and notes only.

The checked-in `scripts/r2-object.mjs` client is the sole release object
transport. Do not publish release objects with Amazon Web Services command-line
tools or SDKs.

New desktop platform manifests include a canonical Ed25519-signed public update
descriptor. Keep private signing material outside the repository, deploy D1
migration `0004_release_update_grants.sql` before enabling update grants, and
run the native archive smoke before publication. Windows and Linux run locally;
macOS runs against the real `.app` archive in the credential-free build before
protected publication.

### Desktop bundle (Linux/macOS/Windows)

`desktop/` contains a PyInstaller launcher that runs the backend with an
embedded zonky.io PostgreSQL and serves the built frontend via
`FRONTEND_DIST`. Desktop tests: run `python -m unittest discover -s tests`
from `desktop/`. Local build: `pyinstaller desktop/backchannel.spec`. The
release coordinator creates the Windows x64 zip natively and the Linux x64
tarball through Docker; `.github/workflows/desktop-release.yml` builds only the
macOS arm64 zip (unsigned; Sortformer and ffmpeg are not bundled).

### Docs Site

`docs-site/` is an Astro Starlight project deployed as a Cloudflare Worker
(`backchannel-site`, same pattern as the quartermaster repo) by
`.github/workflows/deploy-site.yml`: the `site/` landing page at
https://backchannel.page/ and the docs at `/docs/`.
The same Worker serves the D1 operator console only on
`https://admin.backchannel.page/` and the authenticated recipient portal on
`https://downloads.backchannel.page/`. Cloudflare Access protects the complete
admin hostname, and the Worker independently verifies the Access JWT issuer,
audience, and exact `ADMIN_EMAIL`; those values are encrypted Worker secrets.
Early access owns request and consent review plus approve/reject only. Users
owns recipient identity state, password reset, session sign-out, and revoke.
Authorization owns Latest and explicit-version grants only, stored in
`release_access_policies` and `release_account_versions`; the old
`/api/admin/access/*` routes are removed. D1 owns recipient accounts, grants,
sessions, and access events; recipient identity is not the local application's
PostgreSQL identity. Never log subscriber, credential, session, Access, or R2
data. Run the six focused `docs-site` suites, aggregate suite, and build before
release changes.

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

Audio file import uses `soundfile` first and falls back to `ffmpeg` for formats such as MP3, M4A, and WebM (which also covers browser-recorded voice-profile and mic-benchmark audio). The backend resolves ffmpeg via `BACKCHANNEL_FFMPEG` (set by the desktop launcher to the bundled copy) and then `PATH`; Windows and Linux desktop bundles ship an LGPL ffmpeg fetched by `desktop/scripts/download_ffmpeg.py`, while macOS bundles and local dev still need a system `ffmpeg` on `PATH`.

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

The seeded default live model is currently `gemini-3.1-flash-live-preview`. Setting the `audio_gateway` model to `local-parakeet-live` instead routes interim captions to `backend/app/services/local_live_captioner.py`, an on-device captioner (no cloud; works under Privacy First) that transcribes short non-overlapping audio chunks with local Parakeet ONNX. It is experimental and CPU-heavy; the fit test projects whether the machine can sustain it.

## Agent System

Agents are coordinated by `AgentOrchestrator` and configured by `agent_configs` plus optional per-session rows in `session_agent_overrides`.

| Agent slug | Type | Trigger | Code | Purpose |
| --- | --- | --- | --- | --- |
| `audio_gateway` | audio | Continuous audio stream | `backend/app/services/gemini_live.py` / `backend/app/services/openai_realtime.py` / `backend/app/services/local_live_captioner.py` | Silent live listener for interim transcription: Gemini Live, OpenAI Realtime, or the on-device local captioner (`local-parakeet-live`), chosen by the agent's model |
| `consolidated_analyst` | text | Interval, default 40s, plus a final pass | `backend/app/services/agents/consolidated_analyst.py` | Single Gemini call that can produce questions, observations, opportunities, and action items |
| `objection_handler` | text | Interval, default 10s, over only the last ~90s of transcript | `backend/app/services/agents/objection_handler.py` | Low-latency objection scan; each `objection` insight pairs an immediate suggested response (micro) with the underlying concern and strategic angle (macro). Skips the LLM call when the window is unchanged |
| `synthesizer` | meta | `new_insight` / `insight_updated` events, 75s cooldown, 120s fallback | `backend/app/services/agents/synthesizer.py` | Reconciles and enriches saved insights, detects answered questions, may elevate item type |
| `opportunity_specialist` | db | `new_opportunity` events, 55s cooldown, plus final matching | `backend/app/services/agents/opportunity_specialist.py` | Matches opportunity insights against the configured knowledge sources (offerings catalog by default) |
| `strategic_signals` | text | Interval, default 45s during the call | `backend/app/services/agents/strategic_signals.py` | Standalone live strategic-signal scan surfaced as signal cards during the call |
| `brief_meeting_lens` | text | At call end or on demand | `backend/app/services/briefing_synthesis.py` | Briefing lens over the finished transcript |
| `brief_discovery_lens` | text | At call end or on demand | `backend/app/services/briefing_synthesis.py` | Discovery-focused briefing lens |
| `brief_arbiter` | meta | At call end or on demand | `backend/app/services/briefing_synthesis.py` | Reconciles the briefing lenses into the final conversation briefing |

Interval defaults above are the seeded values in `backend/app/services/seed_agents.py`, which is authoritative; `docs/agents.md` and `site/index.html` mirror them and `docs-site/site.test.js` asserts the site copy against the seed data.

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
- Credentials: `GET/PUT/DELETE /api/credentials[/{provider}]` and `POST /api/credentials/{provider}/test` for encrypted workspace API keys (providers: `google`, `openai`)
- Endpoints: `GET/POST /api/endpoints`, `PUT/DELETE /api/endpoints/{id}`, `POST /api/endpoints/{id}/test`, and `POST /api/endpoints/probe` for self-hosted OpenAI-compatible servers (LM Studio, Ollama, vLLM, LiteLLM). Each model listed on an endpoint becomes a registry entry with the id `endpoint:<slug>:<served model name>`, so it appears by name in every model picker; `runs_locally` on those entries drives Privacy First, which admits endpoints on loopback, a private network, or a LAN hostname
- Re-transcription: `POST /api/sessions/{id}/retranscribe` replays stored segment audio through any batch-capable model (destructive to existing transcript entries); `GET /api/sessions/{id}/segments/{n}/audio` serves the recorded WAV
- Token usage: `GET /api/sessions/{id}/token-usage` returns session totals with per-source and per-model input/output breakdowns; the post-call Tokens tab renders this persisted data and shows zero cleanly for sessions without captured usage
- Chat: `POST /api/chat` answers questions over selected sessions' transcripts via the provider-routed text LLM
- Meta: `GET /api/meta` (current app version) and `GET /api/meta/release-notes` (in-app release notes); both read `backend/app/release_notes.py`, the version's single source of truth, which every release must update

## Frontend Structure

Main state lives in `frontend/src/App.tsx`.

- `PreCallView`: session setup, speaker setup, directives, document upload, transcript/audio import, per-session agent selection
- `ActiveCallView`: live call controls, transcript/interim transcript display, insight list, audio indicator, mid-call directive bar
- `PostCallView`: review tabs for insights, transcript, speakers, documents, directives, and token usage; supports resume, export, delete, and speaker rename
- Admin surfaces: `AdminPanel` (tabs: Agents, Transcription & Audio, Connections, About with version + release notes) and `OfferingsManager` for catalog management. The Connections tab holds `ApiKeysCard` (cloud provider keys) and `EndpointsCard` (self-hosted servers: presets, connect-and-list-models, per-endpoint test/enable/remove). Every model `<select>` renders through `frontend/src/lib/modelOptions.ts`, which groups options by provider and owns the Privacy First lock rule
- `WelcomeView`: shown when no session is selected; with zero sessions it becomes a first-run checklist (connect a provider or Privacy First, create a session, start/import a call) driven by live credential and privacy state
- What's-new banner: `useWhatsNew` keeps `backchannel.last_seen_version` in localStorage; when the served version differs, App shows a dismissible toast linking to Admin -> About, where releases since that version are badged "New" (first launch baselines silently)

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
| Self-hosted endpoint storage and model projection | `backend/app/services/custom_endpoints.py` |
| OpenAI-shaped base URL / wire model / key resolution | `backend/app/services/llm_endpoint.py` |
| Gemini Live gateway | `backend/app/services/gemini_live.py` |
| Gemini Files upload/summarization | `backend/app/services/gemini_files.py` |
| Agent orchestrator | `backend/app/services/agents/orchestrator.py` |
| Consolidated text analyst | `backend/app/services/agents/consolidated_analyst.py` |
| Objection handler | `backend/app/services/agents/objection_handler.py` |
| Synthesizer | `backend/app/services/agents/synthesizer.py` |
| Opportunity specialist | `backend/app/services/agents/opportunity_specialist.py` |
| Default agent seed data | `backend/app/services/seed_agents.py` |

## Environment

API keys can be set per provider in Admin -> Connections (encrypted with Fernet; master key auto-generated at `DATA_DIR/master.key`, overridable via `CREDENTIALS_MASTER_KEY`). Env vars remain fallbacks:

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

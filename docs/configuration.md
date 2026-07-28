# Configuration

Configuration comes from three layers, lowest precedence first:

1. Defaults in `backend/app/config.py` (`Settings`, loaded via
   pydantic-settings from the environment and `.env`)
2. Persisted app settings and database rows (agent configs, diarization and
   transcription runtime config) edited through the Admin panel
3. Per-session agent overrides

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | empty | Google API key fallback when no encrypted credential is stored |
| `OPENAI_API_KEY` | empty | OpenAI API key fallback |
| `DATABASE_URL` | `postgresql+asyncpg://callhelper:changeme@db:5432/callhelper` | Async SQLAlchemy connection string; set by Docker Compose for the backend container |
| `DATA_DIR` | `/app/data` | Root for recorded audio, downloaded ASR models, and the credentials master key; a named Docker volume (`backend_data`) in Compose |
| `BACKCHANNEL_FFMPEG` | empty | Explicit path to the ffmpeg executable used for compressed-audio decoding; the desktop launcher sets it to the bundled copy on Windows and Linux, and `PATH` lookup is the fallback |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `callhelper` / `changeme` / `callhelper` | Consumed by the db container and interpolated into `DATABASE_URL` in Compose |
| `CREDENTIALS_MASTER_KEY` | auto-generated | Overrides the Fernet master key used for encrypted credentials |

Copy `.env.example` to `.env` as a starting point.

## API credentials

Provider keys (`google`, `openai`) should be set in Admin -> Connections, which
stores them encrypted with Fernet (`backend/app/routers/credentials.py`).
The master key is auto-generated at `DATA_DIR/master.key` on first use, or
supplied via `CREDENTIALS_MASTER_KEY`. Environment variables remain
fallbacks when no credential row exists for a provider.
`POST /api/credentials/{provider}/test` validates a stored key with a real
provider call.

## Transcription and audio

Transcription model, batch behavior, and audio handling are set in
Admin -> Transcription & Audio.

<picture>
  <source srcset="/assets/shots/admin-transcription-dark.webp" media="(prefers-color-scheme: dark)" />
  <img src="/assets/shots/admin-transcription.webp" width="1185" height="900" alt="Admin Transcription and Audio tab: batch transcription model selection and audio handling settings." />
</picture>

## Privacy First (local-only) mode

The Admin panel has a "Privacy First" switch (`GET/PUT /api/privacy`,
persisted as the `privacy.local_only` app setting). While it is on, no call
audio or transcript text leaves the machine:

- Batch transcription is coerced to a local ONNX model
  (`local-whisper-base` by default) for live segments, audio imports, and
  re-transcription; selecting a cloud transcriber is rejected.
- The audio gateway (interim captions) is skipped unless it is set to the
  on-device captioner (`local-parakeet-live`), which transcribes short chunks
  with local Parakeet ONNX and needs no cloud call. The cloud gateways
  (Gemini Live, OpenAI Realtime) are always skipped.
- Analysis agents are skipped **unless** they are pointed at a model served by
  a self-hosted endpoint on your own machine or network (see below). The gate
  is `allows_local_only()` in `backend/app/services/privacy.py`: it admits the
  bundled ONNX models and any endpoint model whose base URL resolves to
  loopback, a private network, a single-label LAN hostname, a `.local` /
  `.internal` / `.lan` / `.home.arpa` name, or `host.docker.internal`. An
  endpoint reachable only over the public internet is treated as cloud even
  though it speaks the same protocol, because it may be a hosted inference
  provider.
- `generate_text` raises `LocalOnlyModeError` for any model that fails that
  test, so post-import analysis, meeting chat, insight enhancement, and
  document summarization return HTTP 409/400 with an explanatory message.
- Startup provider key verification is skipped.

With an on-prem text endpoint configured, Privacy First and the analysis
agents are no longer mutually exclusive: the agents keep working and no call
data leaves your perimeter. An agent left on a cloud model while the mode is
on does not run; the Admin panel badges it and names the fix, and the live
call status says which agents are paused, so a quiet call is never the first
sign of it.

## Self-hosted endpoints

Any number of OpenAI-shaped chat servers can be registered in
Admin -> Connections -> Self-Hosted Models: LM Studio
(`http://localhost:1234/v1`), Ollama (`http://localhost:11434/v1`), vLLM,
LiteLLM, or a shared GPU box on the LAN. Each endpoint is a row in the
`custom_endpoints` table holding a name, base URL, optional Fernet-encrypted
API key, and the list of models it serves.

Every listed model becomes a first-class registry entry with the id
`endpoint:<endpoint slug>:<served model name>` (for example
`endpoint:lm-studio:antares-1b`), so it appears **by name** in the agent,
transcription, and meeting-chat pickers, grouped under the endpoint's name.
`llm.provider_for()` recognizes the `endpoint:` prefix and routes the call to
the OpenAI dialect without a database read; `resolve_endpoint()` then loads
that endpoint's base URL, wire model name, and key.

REST surface (`backend/app/routers/endpoints.py`):

| Route | Purpose |
| --- | --- |
| `GET /api/endpoints` | List endpoints, their models, and last test result |
| `POST /api/endpoints` | Add an endpoint |
| `PUT /api/endpoints/{id}` | Patch it; an empty `api_key` clears the stored key |
| `DELETE /api/endpoints/{id}` | Remove it |
| `POST /api/endpoints/{id}/test` | Probe `{base_url}/models` and record the outcome |
| `POST /api/endpoints/probe` | Probe an unsaved URL and list what it serves |

No API key is required: `requires_key` is `None` for these models and no
`Authorization` header is sent at all when the endpoint has no key, since an
empty bearer token breaks some servers rather than being ignored.

Running Backchannel in Docker? Inside the container `localhost` is the
container, not your machine. Use `http://host.docker.internal:1234/v1` to
reach a server running on the host.

### Legacy single-endpoint settings

Before named endpoints, one OpenAI-compatible server was configured through
the `llm.openai_compatible.base_url` and `llm.openai_compatible.model_id` app
settings, with `OPENAI_BASE_URL` and `OPENAI_COMPATIBLE_MODEL_ID` as
environment fallbacks, and surfaced as a single `openai-compatible` registry
entry. That configuration is migrated to a named endpoint on first startup
(`migrate_legacy_endpoint()`), agents using the placeholder are repointed at
the migrated model, and the placeholder is then hidden. Installs configured
purely through the environment variables keep the placeholder and keep
working.

Speaker diarization, session recording, file imports, and exports already run
locally and are unaffected. Turning the switch off restores the previously
selected cloud models. The enable flow in the UI shows the full list of
features that stop working before the mode is applied
(`privacy_impact()` in `backend/app/services/privacy.py`).

## Settings reference (`backend/app/config.py`)

### Models

| Setting | Default | Meaning |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-3.1-flash-live-preview` | Seeded default for the live audio gateway |
| `BATCH_TRANSCRIBER_MODEL` | `gemini-3.5-flash-lite` | Fallback batch transcription model; the persisted `transcription.batch.model_id` app setting takes precedence |
| `REFINEMENT_MODEL` | `gemini-3.5-flash` | Fallback text model, used only when the owning agent row has no model set. Post-import Analyze takes its model from the Consolidated Analyst row and Enhance Insights takes its from the Principal Agent row, so on a seeded install this default is not reached |
| `REFINEMENT_INTERVAL_SECONDS` | 45 | Refinement cadence |

### Agent timing

| Setting | Default | Meaning |
| --- | --- | --- |
| `TEXT_AGENT_INTERVAL_SECONDS` | 40 | Consolidated analyst cycle |
| `OBJECTION_HANDLER_INTERVAL_SECONDS` | 10 | Objection handler fast scan cycle |
| `OBJECTION_WINDOW_SECONDS` | 90 | Transcript window for objection scans |
| `SYNTHESIZER_COOLDOWN_SECONDS` | 75 | Minimum time between synthesizer runs |
| `SYNTHESIZER_MAX_INTERVAL_SECONDS` | 120 | Fallback max gap for the synthesizer |
| `OPPORTUNITY_SPECIALIST_COOLDOWN_SECONDS` | 55 | Batch window for the opportunity specialist |
| `KNOWLEDGE_CONTEXT_CHAR_BUDGET` | 60000 | Max characters of knowledge context per prompt |

Per-agent interval values stored in `agent_configs` rows override these
defaults (see [Agent System](agents.md)).

### Diarization

| Setting | Default | Meaning |
| --- | --- | --- |
| `LIVE_DIARIZER` | `lightweight` | Diarizer implementation (`lightweight` VAD+embeddings, or Sortformer on GPU) |
| `VAD_THRESHOLD` | 0.6 | Silero speech probability threshold |
| `MIN_SEGMENT_MS` | 750 | Minimum speech segment length |
| `MAX_SEGMENT_MS` | 15000 | Maximum segment length before a forced cut |
| `SILENCE_GAP_MS` | 600 | Silence gap that closes a segment |
| `SPEAKER_SIMILARITY_THRESHOLD` | 0.68 | Embedding similarity to match an existing speaker |
| `MIN_NEW_SPEAKER_MS` | 4000 | Minimum speech needed to enroll a new speaker profile |
| `MAX_SPEAKER_PROFILES_PER_TRACK` | 4 | Maximum auto-enrolled speaker profiles per audio track |
| `SORTFORMER_WINDOW_MS` | 15000 | Sortformer processing window |

Diarization values can be changed at runtime through
`PATCH /api/diagnostics/diarization/config`; the database-persisted runtime
config wins over these defaults.

### Legacy agent toggles

`AGENT_QUESTION_HUNTER_ENABLED`, `AGENT_CONSOLIDATED_ENABLED`,
`AGENT_OBSERVER_ENABLED`, `AGENT_OPPORTUNITY_SCOUT_ENABLED`,
`AGENT_ACTION_TRACKER_ENABLED`, `AGENT_SYNTHESIZER_ENABLED`, and
`AGENT_OPPORTUNITY_SPECIALIST_ENABLED` predate database agent configuration.
The orchestrator primarily uses `agent_configs` rows; only some subtype
flags are still consulted as fallbacks. Prefer the Admin panel over these
env vars.

## Model registry

`MODEL_REGISTRY` in `backend/app/config.py` is the central catalog the app
selects models from (`GET /api/models`). Each entry declares its provider,
required key, and capabilities:

| Capability | Meaning |
| --- | --- |
| `supports_text` | Usable by text agents (analyst, objection handler, synthesizer, chat) |
| `supports_batch_audio` | Usable for batch/segment transcription and re-transcription |
| `supports_live_audio` | Usable as the live audio gateway |

Current entries include Google Gemini text/audio models
(`gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3-flash-preview`, `gemini-3.1-pro-preview`,
`gemini-3.1-flash-lite`, the `gemini-2.5` family), the live gateway model
`gemini-3.1-flash-live-preview`, OpenAI text models (the GPT-5.6 family
`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, plus `gpt-5.5`, `gpt-5.4`,
`gpt-5.4-mini`, `gpt-5.4-nano`), OpenAI speech-to-text models
(`gpt-realtime-whisper` as a realtime-only gateway; `gpt-4o-transcribe` and
`gpt-4o-mini-transcribe` usable both as realtime gateways and as batch
transcription models), and key-free local ASR models
(`local-whisper-base`, `local-parakeet-tdt-0.6b`, both
`supports_batch_audio` only -- no local entry sets `supports_text`, so no
agent can run without a provider key). Add new models by appending to the
registry.

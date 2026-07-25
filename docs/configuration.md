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

Provider keys (`google`, `openai`) should be set in Admin -> API Keys, which
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
- The audio gateway (interim captions) and every analysis agent
  (consolidated analyst, objection handler, synthesizer, opportunity
  specialist, strategic signals, and the three briefing lenses) are skipped.
  The gate is `provider != "local"` in `backend/app/services/llm.py`, and only
  `local-whisper-base` and `local-parakeet-tdt-0.6b` carry that provider --
  both `supports_text: False`. The `openai-compatible` provider is **not**
  exempt even when its base URL points at your own machine, because the
  setting accepts any URL and the gate cannot tell loopback from a remote
  host. So Privacy First and the live agents remain mutually exclusive.

  If you want local analysis, configure the OpenAI-compatible endpoint below
  and leave Privacy First off. That path runs end to end on your hardware; it
  simply is not enforced by the switch.

## OpenAI-compatible endpoint

The `openai-compatible` model in `MODEL_REGISTRY` targets any OpenAI-shaped
chat server -- Ollama (`http://localhost:11434/v1`), LM Studio
(`http://localhost:1234/v1`), vLLM, or LiteLLM. Set its base URL and model id
in Admin -> API Keys, then select it per agent like any other model.

Resolution is layered, highest precedence first:

1. The `llm.openai_compatible.base_url` app setting (Admin)
2. The `OPENAI_BASE_URL` environment variable
3. `https://api.openai.com/v1`

The model id resolves the same way through `llm.openai_compatible.model_id`
and `OPENAI_COMPATIBLE_MODEL_ID`. The app setting applies only to this
provider, so a saved Ollama URL never redirects a genuine OpenAI model.

No API key is required: `requires_key` is `None` for this provider and no
`Authorization` header is sent at all, since an empty bearer token breaks
some servers rather than being ignored. Set `OPENAI_COMPATIBLE_API_KEY` if
your endpoint does expect one.
- `generate_text` raises `LocalOnlyModeError` for any non-local model, so
  post-import analysis, meeting chat, insight enhancement, and document
  summarization return HTTP 409/400 with an explanatory message.
- Startup provider key verification is skipped.

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
| `REFINEMENT_MODEL` | `gemini-3.5-flash` | Model for refinement passes |
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

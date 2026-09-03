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
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for every OpenAI-shaped chat call; the persisted `llm.openai_compatible.base_url` app setting overrides it for the `openai-compatible` provider only |
| `OPENAI_COMPATIBLE_API_KEY` | empty | Optional key for the legacy `openai-compatible` provider; local servers need none |
| `OPENAI_COMPATIBLE_MODEL_ID` | empty | Wire model name for the legacy `openai-compatible` provider; the `llm.openai_compatible.model_id` app setting takes precedence |
| `LLM_TIMEOUT_SECONDS` | 120 | Ceiling for a hosted chat-completions reply |
| `LLM_SELF_HOSTED_TIMEOUT_SECONDS` | 900 | Ceiling for a self-hosted reply, which can take minutes on CPU |
| `LLM_SELF_HOSTED_MAX_TOKENS` | 8192 | Completion budget sent to self-hosted servers, so long replies are not truncated at the server's own default |
| `DATABASE_URL` | `postgresql+asyncpg://callhelper:changeme@db:5432/callhelper` | Async SQLAlchemy connection string; set by Docker Compose for the backend container |
| `FRONTEND_DIST` | empty | Path to a built frontend for the backend to serve directly (the desktop launcher sets it); empty means nginx serves the frontend (Docker) |
| `DATA_DIR` | `/app/data` | Root for recorded audio, downloaded ASR models, and the credentials master key; a named Docker volume (`backend_data`) in Compose |
| `BACKCHANNEL_FFMPEG` | empty | Explicit path to the ffmpeg executable used for compressed-audio decoding; the desktop launcher sets it to the bundled copy on Windows and Linux, and `PATH` lookup is the fallback |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `callhelper` / `changeme` / `callhelper` | Consumed by the db container and interpolated into `DATABASE_URL` in Compose |
| `CREDENTIALS_MASTER_KEY` | auto-generated | Overrides the Fernet master key used for encrypted credentials |
| `CREDENTIALS_MASTER_KEY_PROTECTION` | empty (`dpapi` on the Windows desktop build) | `dpapi` wraps `DATA_DIR/master.key` with Windows DPAPI so only the same Windows user on the same machine can read it; a plaintext file is upgraded in place on first read |
| `BACKCHANNEL_ALLOWED_HOSTS` | empty | Extra hostnames the API accepts in the `Host` header, comma-separated. Loopback names, any IP address, and the Compose service name are always accepted; a request for any other name is refused (DNS-rebinding defense). `*` disables the check |
| `BACKCHANNEL_ALLOWED_ORIGINS` | empty | Extra browser origins (`https://tools.example`) allowed to call the API cross-origin, also granted by CORS. Local origins are always allowed; a state-changing request from any other origin is refused. `*` disables the origin check |

`DATA_DIR`, `BACKCHANNEL_FFMPEG`, `CREDENTIALS_MASTER_KEY`,
`CREDENTIALS_MASTER_KEY_PROTECTION`, `BACKCHANNEL_ALLOWED_HOSTS`, and
`BACKCHANNEL_ALLOWED_ORIGINS` are read straight from the process
environment (`os.environ`), not through the pydantic `Settings` object, so
they must be set as real environment variables; in Compose the backend's
`env_file: .env` makes a `.env` entry reach them, but a bare local run needs
them exported.

Copy `.env.example` to `.env` as a starting point; it contains only
commented-out entries for `GEMINI_API_KEY`, the Sortformer
`PYTORCH_INDEX_URL`, and the database settings. Other variables, including
`OPENAI_API_KEY`, must be added by hand.

## API credentials

Provider keys (`google`, `openai`) should be set in Admin -> Connections, which
stores them encrypted with Fernet (`backend/app/routers/credentials.py`).
The master key is auto-generated at `DATA_DIR/master.key` on first use, or
supplied via `CREDENTIALS_MASTER_KEY`. Environment variables remain
fallbacks when no credential row exists for a provider.
`POST /api/credentials/{provider}/test` validates a stored key with a real
provider call.

What the app does to keep a stored key from getting out:

- No API response ever carries a key or its ciphertext. The credentials and
  endpoints listings report only whether a key exists plus the last four
  characters; endpoint rows carry `has_api_key`, never the value.
- Keys travel to providers in request headers, never in URLs, and every log
  record in the process is scrubbed of registered key values and key-shaped
  text (bearer tokens, `x-goog-api-key`, `?key=` parameters, URL userinfo,
  `AIza...` / `sk-...` prefixes) before any handler writes it. Provider error
  text shown in Admin or stored on an endpoint row is scrubbed the same way.
- The API has no login, so the server refuses requests whose `Host` is not a
  local name or address and state-changing requests from a foreign browser
  `Origin`; see `BACKCHANNEL_ALLOWED_HOSTS` and `BACKCHANNEL_ALLOWED_ORIGINS`
  above for deployments reached by another name.
- The Docker stack publishes the backend and database ports on loopback
  only; the frontend on `:3000` is the only LAN-reachable surface.

## Transcription and audio

Transcription model, batch behavior, and audio handling are set in
Admin -> Transcription & Audio. The live-caption model on this tab is the
audio gateway agent's model: `PATCH /api/diagnostics/transcription/config`
with `live_preview_model_id` writes the same `audio_gateway` `AgentConfig`
row that Admin -> Agents edits
(`backend/app/services/transcription_runtime.py`).

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

Speaker diarization, session recording, file imports, and exports already run
locally and are unaffected. Turning the switch off restores the previously
selected cloud models. The enable flow in the UI shows the full list of
features that stop working before the mode is applied
(`privacy_impact()` in `backend/app/services/privacy.py`).

## PII Shield (tokenized personal data)

Privacy First decides *where* processing happens; the PII Shield decides
*what* any model, local or cloud, gets to read. It lives in Admin -> Privacy
(`GET/PUT /api/pii-shield`, persisted as the `pii.shield` app setting, off by
default) and is implemented in `backend/app/services/pii/`.

Encode at ingress. Every path that writes human text passes it through
`shield.protect_text` before the row exists: live transcript segments
(`ws/audio_handler.py`), transcript and audio imports and re-transcription
(`routers/imports.py`), manual entries, directives (REST and the mid-call
WebSocket message), session name, notes and meeting context, speaker names
(`shield.protect_name`: a speaker's name is a person's name by definition),
the local document excerpt, the typed question in Ask and the user turns in
Chat. Because the stored text is already tokenized, every prompt builder
(the analyst, objection handler, synthesizer, strategic signals, briefing,
chat, ask, speaker-context enhancement) is clean by construction and needed
no change.

Tokens are `[CATEGORY_n]` (`[PERSON_1]`, `[EMAIL_2]`, `[ORG_1]`) and are
numbered per session: the same value gets the same token within a session, so
a model can follow referents across a call, while nothing links a person
across sessions. Categories: PERSON, ORG, LOCATION (off by default), EMAIL,
PHONE, SSN, CARD (Luhn-checked), IP, ADDRESS.

Detection is layered and entirely on-device:

- pattern recognizers for the structured categories
  (`services/pii/recognizers.py`);
- the session's roster matched as whole words: its speakers, the workspace
  protected-terms list (client companies, code names), and every person,
  organization and place the session's vault already holds, so a name
  caught once is caught on every later line even without the model; each
  capitalized part of a multi-word name maps to the same token;
- introductions ("my name is", "this is") for people;
- optionally `Xenova/bert-base-NER` (the CoNLL-2003 BERT NER model as a
  quantized ONNX file, about 110 MB) with a WordPiece tokenizer implemented
  in `services/pii/ner.py`, downloaded once into `DATA_DIR/pii-models/` and
  run with the onnxruntime already shipped for diarization. When it cannot
  be fetched the shield keeps working with the other layers and the status
  says so.

The download is visible while it happens: the Privacy tab shows its progress
and `/api/model-downloads` reports it to any client, so a slow first fetch
reads as a download rather than a stall. Nothing on the ingest path waits for
it. If the weights are absent, still arriving, or known to have failed, text
is protected by the pattern and roster layers and detection carries on; the
model joins in once it has loaded. Before v0.6.2 the loader held one lock
across the fetch and a wedged download blocked every protected write in the
app, session creation included (ALP-373).

The vault (`services/pii/vault.py`, table `pii_vault_entries`) stores each
value Fernet-encrypted under a key derived with HKDF from the credentials
master key (`secrets.derive_subkey`), with a keyed HMAC of the normalized
value for lookup, so the table reveals neither values nor whether two
sessions share one.

Decode only at the edge, from exactly three surfaces:
`PiiRevealMiddleware` (every session-scoped JSON response and the session
list, through `shield.reveal_payload`), `RevealingWebSocket` (every live
message, through `vault.reveal_map` and `shield._walk`), and the exports
and `/api/chat`, which are not session-scoped in the path and so call
`shield.reveal_text` directly. Nothing under `services/agents` or
`services/llm.py` decodes at all, which is the invariant worth grepping for
before a release. Exports carry tokens
unless `?reveal=1` is passed (the Export menu's "Include personal data"
box). Every reveal appends a row to `pii_reveal_events` (session, route,
token count); the Privacy tab shows the last 24 hours.

Audio is enforced, not advised. Audio cannot be tokenized, so while the
shield is on `transcription_runtime.audio_lock_reason` locks audio to local
models the way Privacy First does, but for audio alone: the batch
transcriber is coerced to `local-whisper-base` when a cloud one is
configured and the setters reject a cloud choice; the orchestrator skips a
cloud live-caption gateway (blocked reason `pii_shield`, shown as "Live
captions off: PII Shield" in the live activity panel) and admits only the
on-device captioner. Cloud text models stay allowed because they receive
tokens only. With the shield on, document upload takes the local extraction
path and never sends the file. `shield.status` reports each row honestly,
including a cloud gateway that is configured but paused.

Transcript refinement closes the quality gap that local-only audio opens.
The `transcript_refiner` agent (off by default; Admin -> Agents, any text
model, local or cloud, interval default 45s) sends the tokenized text of
recent entries to its model to fix punctuation, casing, sentence boundaries
and obvious mishearings, and writes the result back to `transcript_entries`
with the transcriber's text kept in `raw_text` and `refined_at` set. A
rewrite is accepted only when it carries exactly the same multiset of
tokens as the original and stays within a length band
(`services/transcript_refiner.py`, `accept_refinement`), so a model can
never drop, invent or renumber a token. It runs as a live interval agent
(browser gets `transcript_updated` messages), as the first drain stage at
call end, and before post-import analysis.

Two ways to see that it works. The prompt log (`prompt_log` in the shield
settings, "Record outbound prompts" on the Privacy tab) appends every prompt
to `DATA_DIR/prompt-log/outbound.jsonl` exactly as it leaves for a model,
with source, model and session; `GET /api/pii-shield/egress` lists the
newest entries and the Privacy tab shows them with a "tokens only" or
"blocked" badge. It is written raw, bypassing the log scrubber, because a
scrubbed record could not show a leak; it never leaves the machine and
`DELETE /api/pii-shield/egress` removes it. Independently of the log, while
the shield is on every text prompt passes an egress tripwire
(`services/pii/egress.py`, called from `generate_text` and `generate_json`):
a prompt still carrying a value the vault has seen in plaintext is refused
before it is sent (HTTP 409 `PiiEgressBlocked`, an audit row with route
`egress-blocked:<source>`), so a gap upstream costs one model call rather
than one disclosure. The transcribers log segment lengths, never words,
because the shield has not seen a segment when it is transcribed.

Per-session endpoints: `GET /api/sessions/{id}/pii/summary` (counts, no
reveal), `GET /api/sessions/{id}/pii` (the ledger with values; audited), and
`POST /api/sessions/{id}/pii/protect` to run the encode path over a session
recorded before the shield was on. `POST /api/pii-shield/preview` shows what
a sentence turns into without touching the vault.

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
| `DELETE /api/endpoints/{id}` | Soft delete: the row is tombstoned (`deleted_at` set, stored key cleared), not removed |
| `POST /api/endpoints/{id}/test` | Probe `{base_url}/models` and record the outcome |
| `POST /api/endpoints/probe` | Probe an unsaved URL and list what it serves |

No API key is required: `requires_key` is `None` for these models and no
`Authorization` header is sent at all when the endpoint has no key, since an
empty bearer token breaks some servers rather than being ignored.

`PUT /api/endpoints/{id}` guards the privacy boundary: moving an endpoint
from an on-prem base URL to an off-prem one is refused outright while
Privacy First is on, and without Privacy First it requires
`confirm_off_prem=true`, because the change can send call data outside the
machine or network (`update_endpoint()` in
`backend/app/services/custom_endpoints.py`).

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
| `SPEAKER_COHERENCE_WINDOW_MS` | 3000 | Window size for within-segment coherence embeddings |
| `SPEAKER_COHERENCE_THRESHOLD` | 0.40 | Adjacent-window similarity below which a segment is split at a speaker change |
| `MIN_NEW_SPEAKER_MS` | 4000 | Minimum speech needed to enroll a new speaker profile |
| `MAX_SPEAKER_PROFILES_PER_TRACK` | 4 | Maximum auto-enrolled speaker profiles per audio track |
| `SORTFORMER_WINDOW_MS` | 15000 | Sortformer processing window |

Diarization values can be changed at runtime through
`PATCH /api/diagnostics/diarization/config`; the database-persisted runtime
config wins over these defaults.

#### ONNX Runtime threading

The lightweight diarizer runs two ONNX models on CPU, and ONNX Runtime sizes
its thread pool from the host core count unless told otherwise. Left at that
default both models spend most of their CPU on pool overhead rather than
arithmetic, and ORT does not see container CPU quotas, so a big host or a
small quota both go badly. These settings bound it.

| Setting | Default | Meaning |
| --- | --- | --- |
| `DIARIZER_VAD_ONNX_THREADS` | 1 | Intra-op threads for Silero VAD. It is an LSTM over one 512-sample frame with nothing to parallelize; the ORT default cost 5x the CPU for about 9% of wall time |
| `DIARIZER_EMBED_ONNX_THREADS` | `min(4, cores / 2)` | Intra-op threads for the WeSpeaker embedding model. Bounding the pool cuts CPU roughly 4x and costs some wall time |
| `DIARIZER_EMBED_ONNX_SPIN` | `false` | Let ORT spin-wait between embedding calls. Segments arrive seconds apart, so that spin is charged to the VAD; leaving this off measured no downside |

Both thread counts are clamped to at least 1: ORT reads 0 as "use every core",
which is the default these settings exist to avoid. Raising
`DIARIZER_EMBED_ONNX_THREADS` trades CPU for latency on the foreground
transcript-import path; the live path has ample headroom either way.

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

`GET /api/models` also returns `runs_locally` and `endpoint_id` on every
entry (`backend/app/routers/models.py`): `runs_locally` covers the bundled
ONNX models and models served by an on-prem endpoint, and is the flag the
Privacy First UI admission keys off; `endpoint_id` is set for models served
by a saved custom endpoint.

Current entries include Google Gemini text/audio models
(`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3-flash-preview`, `gemini-3.1-pro-preview`,
`gemini-3.1-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`,
`gemini-2.5-pro`), the live gateway model
`gemini-3.1-flash-live-preview`, OpenAI text models (the GPT-5.6 family
`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, plus `gpt-5.5`, `gpt-5.4`,
`gpt-5.4-mini`, `gpt-5.4-nano`), OpenAI speech-to-text models
(`gpt-live-transcribe` as a realtime-only gateway; `gpt-4o-transcribe` and
`gpt-4o-mini-transcribe` usable both as realtime gateways and as batch
transcription models; `gpt-audio-1.5` and `gpt-audio-mini` as batch-only
audio chat models), the `openai-compatible` placeholder for the legacy
single self-hosted endpoint (text-capable, keyless, listed only while that
legacy configuration is active), and key-free local models
(`local-whisper-base` and `local-parakeet-tdt-0.6b`,
`supports_batch_audio` only; `local-parakeet-live`, the experimental
on-device live captioner, `supports_live_audio` only). No `Local` entry sets
`supports_text`, so text agents need a provider key, the legacy
placeholder, or a self-hosted endpoint model. Add new models by appending to
the registry.

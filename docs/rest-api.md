# REST API Reference

All routes are served by FastAPI under `/api` (`backend/app/main.py`
registers one router per resource from `backend/app/routers/`). Interactive
OpenAPI documentation with request/response schemas is available from a
running backend at `http://localhost:8001/docs`; the Pydantic models behind
every payload are in `backend/app/schemas.py`.

In Docker Compose the frontend nginx proxies `/api` from port 3000, so the
same paths work against `http://localhost:3000`.

## Health

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness check |

## App metadata (`routers/meta.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/meta` | Current application version (`{"version": "X.Y.Z"}`) |
| GET | `/api/meta/release-notes` | In-app release notes, newest first (`version`, `date`, `title`, markdown `body`) |

Both are backed by `backend/app/release_notes.py`, the version's single
source of truth, which is updated as part of every release.

## Sessions (`routers/sessions.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions` | Create a session |
| GET | `/api/sessions` | List sessions |
| GET | `/api/sessions/{id}` | Get one session |
| PATCH | `/api/sessions/{id}` | Update name, notes, meeting type/context, group, state |
| DELETE | `/api/sessions/{id}` | Delete a session and its children |
| GET | `/api/sessions/{id}/segments` | List call segments |
| GET | `/api/sessions/{id}/segments/{n}/audio` | Download a segment's recorded WAV |
| GET | `/api/sessions/{id}/token-usage` | Usage totals with per-source and per-model breakdowns |
| POST | `/api/sessions/{id}/enhance-insights` | Re-run insight enrichment after speaker changes; started in the background, returns the run summary |
| GET | `/api/sessions/{id}/enhance-insights/{run_id}` | Poll a started enhance run: status, dirty flag, and whether the briefing was updated |
| GET | `/api/sessions/{id}/agents` | Effective per-session agent list |
| PUT | `/api/sessions/{id}/agents` | Set per-session agent enable/disable overrides |

Usage is persisted per provider response and shown in the post-call
**Tokens** tab, which reports estimated cost rather than raw counts. Sessions
without recorded LLM activity return zero totals and empty `by_source` /
`by_model` lists; historical sessions are not backfilled.

Not every model bills per token. OpenAI Realtime transcription
(`gpt-live-transcribe`) publishes a per-minute rate and reports audio duration
instead of token counts, so each row also carries `audio_seconds`, which is
zero for every token-billed model. `GET /api/models/pricing` exposes the
matching `per_minute` rate alongside the per-million token rates; a model
priced one way has `null` for the other. Cost estimates sum both, so a row can
show zero tokens and a non-zero cost.

Not every token bills at the same rate either. Each row also carries
`cached_input_tokens` and `audio_input_tokens` (slices of `input_tokens`) and
`audio_output_tokens` (a slice of `output_tokens`), taken from the provider's
usage breakdown: Gemini `cached_content_token_count` and the per-modality
`prompt_tokens_details`, OpenAI `prompt_tokens_details.cached_tokens` and
`audio_tokens`. They are subsets already counted in the totals, never added to
them. The pricing endpoint publishes `cached_input_per_million`,
`audio_input_per_million`, and `audio_output_per_million` where the provider
does; the cost estimate prices each slice at its own rate and falls back to
the plain input or output rate when a slice's rate is unpublished. The Gemini
Live gateway is the case that matters: its input is almost entirely audio,
billed at four times the text rate, and each turn is one billed generation
whose prompt is the whole session so far. The gateway keeps one pending
`usage_metadata` per turn (each new one replaces it) and records it once when
the turn ends (`turn_complete` or `interrupted`), when the stream ends, or
when the session closes, so it counts correctly whether the API reports usage
once per turn or on every chunk with growing counts. Earlier versions stored
only the increase between messages, which under-reported live calls.

## Session groups (`routers/groups.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/groups` | List groups |
| POST | `/api/groups` | Create a group |
| PATCH | `/api/groups/{id}` | Rename/update a group |
| DELETE | `/api/groups/{id}` | Delete a group |

## Per-session resources

### Directives (`routers/directives.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/directives` | Add a directive |
| GET | `/api/sessions/{id}/directives` | List directives |
| PATCH | `/api/sessions/{id}/directives/{directive_id}` | Edit or (de)activate |
| DELETE | `/api/sessions/{id}/directives/{directive_id}` | Remove |

### Documents (`routers/documents.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/documents` | Upload a document (summarized for agent context) |
| GET | `/api/sessions/{id}/documents` | List documents |
| DELETE | `/api/sessions/{id}/documents/{document_id}` | Remove |

### Speakers (`routers/speakers.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/speakers` | Register a speaker |
| GET | `/api/sessions/{id}/speakers` | List speakers |
| PATCH | `/api/sessions/{id}/speakers/{speaker_id}` | Rename, set role/type/display name |
| POST | `/api/sessions/{id}/speakers/{speaker_id}/merge` | Merge into another speaker |
| DELETE | `/api/sessions/{id}/speakers/{speaker_id}` | Remove |

### Transcripts (`routers/transcripts.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/transcripts` | Append a transcript entry manually |
| GET | `/api/sessions/{id}/transcripts` | List transcript entries |
| PATCH | `/api/sessions/{id}/transcripts/{transcript_id}` | Edit text or speaker attribution |

### Insights (`routers/questions.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/sessions/{id}/questions` | List insights (all item types) |
| PATCH | `/api/sessions/{id}/questions/{question_id}` | Mark answered/dismissed, edit |

### Ask (`routers/ask.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/ask` | Answer one question against the running call and save the answer |

The body is `{"model_id": "...", "question": "..."}`. Context is assembled
recency-first from the session's transcript, live insights, strategic signals,
directives, and the persisted `documents.summary` values -- never a fresh
summarization call. The answer is persisted as an `asked` insight
(`agent_source` `live_chat`, `starred`, `answered`), with the answering model
and elapsed time in `rationale`; answers over 4000 characters are truncated
with a marker. Separate from `/api/chat`, which is cross-session and
briefing-led.

### Synthesis (`routers/synthesis.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/sessions/{id}/synthesis` | Get the saved session synthesis (or null) |
| POST | `/api/sessions/{id}/synthesis/refresh` | Regenerate the synthesis |

Both take `mode` (`live` or `post_call`, default `post_call`): `live` is the
strategic-signal cycle, `post_call` the briefing. `GET` also takes
`include_history`; without it the response carries only
`signal_history_count`, so the caller can render the History control without
paying for the rows. Signals accumulate in `signal_history` with a per-signal
`count`, `first_seen`, and `last_seen` rather than being replaced each cycle.

### Imports (`routers/imports.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/import/transcript` | Import `.txt`, `.md`, or `.docx` transcript |
| POST | `/api/sessions/{id}/import/audio` | Import `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac` audio through the live pipeline |

### Analysis and re-transcription

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/analyze` | Run post-import analysis over the transcript (`routers/analyze.py`) |
| POST | `/api/sessions/{id}/retranscribe` | Replay stored segment audio through a batch-capable model; replaces existing transcript entries (`routers/retranscribe.py`) |

### Artifacts (`routers/artifacts.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/sessions/{id}/artifacts/transcript-export` | Transcript as TXT |
| GET | `/api/sessions/{id}/artifacts/questions-export` | Insights as one XLSX, enriched columns folded in |
| GET | `/api/sessions/{id}/artifacts/summary-export` | Summary as HTML |

## Global configuration

### Agents (`routers/agents.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/agents` | List agent configs |
| GET | `/api/agents/{slug}` | Get one agent config |
| PATCH | `/api/agents/{slug}` | Update enabled, model, interval, prompt |
| POST | `/api/agents/reset/{slug}` | Restore the seeded prompt |

### Models (`routers/models.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/models` | Model registry with capabilities and key requirements |
| GET | `/api/models/pricing` | Published USD-per-1M-token rates keyed by model id, plus the as-of date (standard paid-tier text, cached-input, audio-input and audio-output rates, and per-minute rates for duration-billed models; `null` = no published rate) |

### Privacy First (`routers/privacy.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/privacy` | Current Privacy First state: `local_only`, the effective batch transcription model, and an `impact` summary of what enabling it keeps and disables |
| PUT | `/api/privacy` | Set `{"local_only": true\|false}`; returns the same payload |
| GET | `/api/pii-shield` | PII Shield status: `settings` (enabled, categories, ner, protected_terms), the category list, the on-device NER model state, an honest `coverage` report (text, transcription audio, live gateway, documents), vault size, and reveals in the last 24 hours |
| PUT | `/api/pii-shield` | Partial update of `enabled`, `categories`, `ner`, `protected_terms` (`[{"value","category"}]`); returns the status payload. Enabling with NER on starts the one-time model download |
| POST | `/api/pii-shield/preview` | `{"text", "session_id"?}` -> what a model would receive (`protected`) and each finding; numbers tokens from 1 and touches no vault |
| POST | `/api/pii-shield/ner/install` | Download and load the on-device NER model now; 503 with the reason when it cannot |
| GET | `/api/sessions/{id}/pii/summary` | Protected value counts by category for one session; decrypts nothing |
| GET | `/api/sessions/{id}/pii` | The session's ledger: `{category, ordinal, value}` per protected value; recorded as one reveal |
| POST | `/api/sessions/{id}/pii/protect` | Run the encode path over a session's stored transcript, insights, directives, document excerpts, session fields and speakers (for sessions recorded before the shield was on); returns what changed |

### Credentials (`routers/credentials.py`)

Providers: `google`, `openai`, `openai-compatible` (the legacy single
self-hosted server; its key is optional). Keys are stored encrypted (see
[Configuration](configuration.md)).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/credentials` | List configured providers (masked) |
| PUT | `/api/credentials/{provider}` | Save/replace a key |
| DELETE | `/api/credentials/{provider}` | Remove a key |
| POST | `/api/credentials/{provider}/test` | Validate the stored key against the provider |
| GET | `/api/credentials/openai-compatible/endpoint` | Legacy single-endpoint base URL and wire model id |
| PUT | `/api/credentials/openai-compatible/endpoint` | Update them; omitted fields are untouched, empty strings clear back to env/default |

The `openai-compatible/endpoint` routes predate named endpoints and are
superseded by `/api/endpoints`; existing legacy configurations are migrated
to a named endpoint on startup.

### Self-hosted endpoints (`routers/endpoints.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/endpoints` | List endpoints, their models, and last test result |
| POST | `/api/endpoints` | Register an endpoint (name, base URL, optional API key, served models) |
| PUT | `/api/endpoints/{id}` | Patch it; omitted fields keep their value, an empty `api_key` clears the stored key |
| DELETE | `/api/endpoints/{id}` | Retire an endpoint; agents still pointing at its models report it as missing until repointed |
| POST | `/api/endpoints/{id}/test` | Probe `{base_url}/models` and record the outcome for the status badge |
| POST | `/api/endpoints/probe` | Probe an unsaved base URL and list the models it serves |

Each model listed on an endpoint becomes a registry entry with the id
`endpoint:<slug>:<served model name>` (see [Configuration](configuration.md)).
DELETE is a soft delete: the row is tombstoned (`deleted_at` set, stored key
cleared) rather than removed
(`delete_endpoint()` in `backend/app/services/custom_endpoints.py`).

### Offerings (`routers/offerings.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/offerings` | List/filter the offerings catalog |
| GET | `/api/offerings/vendors` | Distinct vendors |
| GET | `/api/offerings/categories` | Distinct categories |
| GET | `/api/offerings/tags` | Distinct tags in use |
| POST | `/api/offerings` | Create an offering |
| PATCH | `/api/offerings/{offering_id}` | Update an offering |
| DELETE | `/api/offerings/{offering_id}` | Remove an offering |
| POST | `/api/offerings/import` | Bulk import from CSV/XLSX |
| POST | `/api/offerings/seed` | Load the seed catalog (`?replace=true` to overwrite) |

### Knowledge sources (`routers/knowledge.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/knowledge` | List knowledge sources |
| POST | `/api/knowledge` | Create a source |
| GET | `/api/knowledge/{source_id}` | Get a source |
| PATCH | `/api/knowledge/{source_id}` | Update a source |
| DELETE | `/api/knowledge/{source_id}` | Remove a source and its records |
| GET | `/api/knowledge/{source_id}/records` | List records |
| POST | `/api/knowledge/{source_id}/records` | Add a record |
| PATCH | `/api/knowledge/records/{record_id}` | Update a record |
| DELETE | `/api/knowledge/records/{record_id}` | Remove a record |
| POST | `/api/knowledge/{source_id}/records/import` | Bulk import records from CSV/XLSX |
| POST | `/api/knowledge/{source_id}/files` | Upload a file, converted to Markdown records |

### Chat (`routers/chat.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/chat` | Ask questions over selected sessions' settled briefings, non-dismissed insights, and speaker-attributed transcripts; briefings guide interpretation while transcripts ground facts and quotations |

### Diagnostics (`routers/diagnostics.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/diagnostics/diarization` | Diarizer capability and runtime config |
| PATCH | `/api/diagnostics/diarization/config` | Update diarizer runtime config |
| GET | `/api/diagnostics/diarization/voice-profile` | Whether a local voice profile is enrolled |
| PUT | `/api/diagnostics/diarization/voice-profile` | Replace the voice profile from an uploaded clip (audio discarded, only the embedding is kept) |
| DELETE | `/api/diagnostics/diarization/voice-profile` | Delete the enrolled voice profile |
| GET | `/api/diagnostics/transcription` | Batch transcription config |
| GET | `/api/diagnostics/transcription/readiness` | Whether the selected transcription models have usable credentials |
| GET | `/api/diagnostics/capacity` | Call-start capacity admission verdict: measured headroom for the selected config (`?track_count=1\|2`, default 2) |
| PATCH | `/api/diagnostics/transcription/config` | Update the batch transcription model and/or the live-caption (audio gateway) model |
| POST | `/api/diagnostics/diarization/sortformer/benchmark` | Benchmark Sortformer on an uploaded file (needs at least 15 seconds of audio) |
| GET | `/api/diagnostics/local-fit` | On-prem text models available to test plus each scored agent's current cycle interval |
| POST | `/api/diagnostics/local-fit/run` | Time a role-sized call on each on-prem text model and score keep-up per live agent role |
| POST | `/api/diagnostics/local-fit/apply` | Apply recommended cycle intervals to the scored agents (speed tuning) |
| POST | `/api/diagnostics/local-fit/asr` | Measure real-time factor for the local ONNX ASR models on an uploaded speech clip |

### Desktop updates (`routers/updates.py`)

Desktop auto-update routes. Every route except the status read requires the
`X-Backchannel-Instance` header to match the launcher-issued instance token
(403 otherwise), so they are effectively available only under the desktop
launcher (`BACKCHANNEL_DESKTOP=1`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/updates` | Update status; a ready update also reports `blocked_reason` when active work defers install |
| POST | `/api/updates/check` | Force an update check |
| POST | `/api/updates/grant` | Submit a signed update grant and start the download |
| DELETE | `/api/updates/download` | Cancel an in-progress download |
| POST | `/api/updates/apply` | Install the downloaded update; 409 while a call or other active work is running |

## WebSocket

The live-call WebSocket endpoint `/ws/{session_id}` is documented separately
in [WebSocket Protocol](websocket-protocol.md).

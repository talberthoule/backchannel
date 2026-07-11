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
| POST | `/api/sessions/{id}/enhance-insights` | Re-run insight enrichment after speaker changes |
| GET | `/api/sessions/{id}/agents` | Effective per-session agent list |
| PUT | `/api/sessions/{id}/agents` | Set per-session agent enable/disable overrides |

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

### Synthesis (`routers/synthesis.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/sessions/{id}/synthesis` | Get the saved session synthesis (or null) |
| POST | `/api/sessions/{id}/synthesis/refresh` | Regenerate the synthesis |

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
| GET | `/api/sessions/{id}/artifacts/questions-export` | Insights as XLSX |
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

### Credentials (`routers/credentials.py`)

Providers: `google`, `openai`. Keys are stored encrypted (see
[Configuration](configuration.md)).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/credentials` | List configured providers (masked) |
| PUT | `/api/credentials/{provider}` | Save/replace a key |
| DELETE | `/api/credentials/{provider}` | Remove a key |
| POST | `/api/credentials/{provider}/test` | Validate the stored key against the provider |

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
| GET | `/api/diagnostics/transcription` | Batch transcription config |
| PATCH | `/api/diagnostics/transcription/config` | Update batch transcription config |
| POST | `/api/diagnostics/diarization/sortformer/benchmark` | Benchmark Sortformer on an uploaded file |

## WebSocket

The live-call WebSocket endpoint `/ws/{session_id}` is documented separately
in [WebSocket Protocol](websocket-protocol.md).

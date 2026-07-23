# ALP-115 Token Usage Design

## Goal

Capture token usage for every session-scoped backend LLM call and show the post-call total with source/model breakdowns. Historical sessions have no backfill and render an empty state.

## Data model

Add a `token_usage` table with one row per provider response:

- `id`
- `session_id` foreign key with cascade delete
- `source`
- `model_id`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `created_at`

An Alembic migration creates/drops the table and indexes `session_id`. `Base.metadata.create_all()` remains the startup compatibility path for databases that launch without first running Alembic; no column patch is needed for a new table.

## Capture

A single small recorder normalizes provider usage fields and commits a row in its own database session. Recording is best-effort: telemetry failures are logged and never fail the user-facing LLM operation.

Every call site supplies the session id, model id, and a stable source label. Shared text generation accepts these optional attribution fields and records both Gemini and OpenAI responses. Direct Gemini callers record their response through the same recorder. Realtime gateways receive the session id when they connect: Gemini cumulative counters are stored as positive deltas and reset per connection; OpenAI records completed transcription-event usage. Multi-session chat is attributed only when exactly one session is in scope so a single provider response is never duplicated across sessions.

No pricing map, historical backfill, new dependency, or speculative telemetry abstraction is included.

## API

`GET /api/sessions/{session_id}/token-usage` verifies the session exists and returns:

- aggregate input, output, and total tokens
- breakdown by source
- breakdown by model

An empty session returns zero totals and empty breakdown lists.

## UI

Post-call review gains a `Tokens` tab using existing tab and table styles. It fetches the endpoint only for the post-call session and renders loading, empty, error, and populated states. The populated view shows the total plus source and model breakdown tables with input/output/total columns. Existing teal semantic tokens and dark-mode styles are reused.

## Tests

Backend tests cover normalization/recording failure isolation, aggregation including empty sessions, shared Gemini/OpenAI attribution, direct call attribution, and realtime delta/event handling. Frontend behavior is protected by the existing build gate plus a small pure rendering/data-shape test where practical.

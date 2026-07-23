# Speaker Revalidation Batching Design

## Scope

ALP-118 completes the deferred ALP-116 machinery only: bounded asynchronous
revalidation batches, observable progress, persisted metrics, failed-batch-only
retry, and the mapping/content revision state required for idempotency. It
continues to use the existing speaker-context enhancer, Insight operation
application, Briefing synthesis, and token-usage records.

## Selected approach

Persist one mapping snapshot, one run, and ordered batch rows in PostgreSQL.
The POST endpoint creates or resumes the idempotent run and returns immediately;
a FastAPI background task processes its queued batches. A GET endpoint exposes
the run and per-batch state for frontend polling.

Alternatives rejected:

- A new Celery/worker deployment adds infrastructure that this desktop-first
  application does not otherwise require.
- Synchronous chunking cannot return observable progress or survive a request
  ending.

## Persistence and idempotency

- `SpeakerMappingRevision` stores the complete canonical speaker mapping and
  the session speaker-context version that produced it.
- `SpeakerRevalidationRun` is unique by session, mapping revision, and a
  deterministic content hash.
- `SpeakerRevalidationBatch` stores ordered Insight ID chunks plus one final
  Briefing batch, status, attempts, latency, token counts, and the last error.
- Context-changing speaker edits increment `Session.speaker_context_version`.
- Completed Insight rows and the post-call synthesis record the mapping revision
  used. Existing stable IDs are retained.
- Repeated starts return the existing run. A partial run resets only failed
  batches; completed batches are never submitted again.

## Processing

Insight IDs are chunked into bounded groups. Each batch uses the existing full
transcript and corrected roster but only its assigned Insights. Model output,
Insight mutations, mapping-revision stamps, and batch completion are committed
atomically so retry cannot duplicate a partially committed batch. The final
Briefing batch runs only after all Insight batches complete.

When every batch completes, the session dirty flag is cleared only if no newer
speaker-context version exists. A newer edit remains dirty and requires a new
run.

## Metrics and UI

The API returns total/completed/failed batches, processed entries, attempts,
duration, input/output/total tokens, and per-batch errors. Existing token usage
rows are aggregated over each sequential batch attempt; no duplicate pricing
catalog is introduced.

The Speaker mapper starts a run, polls while it is running, renders batch
progress, refreshes visible content at terminal state, and preserves the
existing warning/retry behavior for partial or failed runs.

## Verification

Focused checks cover bounded partitioning, revision hashing/snapshotting,
atomic batch completion, failed-only retry, metrics aggregation, stale mapping
completion, API observability, frontend polling/progress copy, Alembic upgrade
and downgrade, and startup schema patching. Full backend tests, frontend tests,
frontend build, and Sentrux run before handoff.

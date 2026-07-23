# Speaker Revalidation Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ALP-116 revalidation asynchronous, observable, measurable, revision-aware, and safe to retry one failed batch at a time.

**Architecture:** Add a database-backed run/batch ledger around the existing
speaker enhancer and Briefing synthesis. The POST endpoint schedules the
in-process worker, the GET endpoint exposes persisted progress, and the
frontend polls until the run reaches a terminal state.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL, React,
TypeScript, stdlib `unittest`.

## Global Constraints

- Branch `agent/alp-118-revalidation` remains local and based on `aaee3f8`.
- Reuse existing enhancer, synthesis, and token accounting; add no dependency,
  external queue, new analysis agent, or pricing catalog.
- Retry only failed batches and preserve completed batch results and stable
  Insight IDs.
- Do not touch shared master, push, or merge.

---

### Task 1: Persist revisions, runs, and batches

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Create: `backend/alembic/versions/018_add_speaker_revalidation.py`
- Test: `backend/tests/test_main_schema.py`
- Test: `backend/tests/test_speaker_revalidation.py`

**Interfaces:**
- Produces: `SpeakerMappingRevision`, `SpeakerRevalidationRun`,
  `SpeakerRevalidationBatch`, and API response schemas.

- [ ] Write failing model, migration upgrade/downgrade, and startup-patch tests.
- [ ] Run the focused tests and confirm failures name the absent revision state.
- [ ] Add only the columns/tables/constraints in the design.
- [ ] Re-run focused tests to green.
- [ ] Commit the schema slice.

### Task 2: Create and resume idempotent bounded runs

**Files:**
- Create: `backend/app/services/speaker_revalidation.py`
- Modify: `backend/app/services/speaker_context_enhancer.py`
- Modify: `backend/app/services/insight_refiner.py`
- Modify: `backend/app/routers/speakers.py`
- Test: `backend/tests/test_speaker_revalidation.py`

**Interfaces:**
- Produces: `start_or_resume_revalidation(session_id, db)`,
  `process_revalidation_run(run_id)`, and `serialize_revalidation_run(run, db)`.
- Consumes: existing `build_enhancement_prompt`, `_apply_operations`,
  `rewrite_session_insight_speaker_labels`, and `run_session_synthesis`.

- [ ] Write failing checks for deterministic mapping/content revisions and
  bounded Insight ID batches followed by one Briefing batch.
- [ ] Write a failing check proving repeated starts reuse the same run.
- [ ] Write a failing check proving retry requeues failed batches only.
- [ ] Implement canonical snapshots, hashes, unique run reuse, and batch creation.
- [ ] Refactor `_apply_operations` only enough to share the worker transaction.
- [ ] Implement sequential processing with atomic mutation/batch completion.
- [ ] Add stale-context completion and metrics aggregation checks.
- [ ] Re-run the focused backend tests to green.
- [ ] Commit the service slice.

### Task 3: Expose asynchronous progress

**Files:**
- Modify: `backend/app/routers/sessions.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_speaker_revalidation.py`
- Test: `backend/tests/test_speaker_context_enhancer.py`

**Interfaces:**
- Produces: `POST /api/sessions/{id}/enhance-insights` and
  `GET /api/sessions/{id}/enhance-insights/{run_id}` returning the same
  observable run shape.

- [ ] Write failing route checks for immediate running state, progress reads,
  completed reuse, and failed-only retry.
- [ ] Replace the blocking route orchestration with background scheduling and
  persisted status serialization.
- [ ] Keep the completed-session and clean-context guards.
- [ ] Re-run route and service tests to green.
- [ ] Commit the API slice.

### Task 4: Poll and render progress

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/components/SpeakerNameMapper.tsx`
- Modify: `frontend/src/components/SpeakerNameMapper.test.mjs`

**Interfaces:**
- Produces: `waitForEnhancement(id, initial)` and progress/result copy from the
  persisted backend shape.

- [ ] Add a failing frontend check for running batch progress and terminal
  partial retry copy.
- [ ] Add typed start/status API calls and bounded polling.
- [ ] Render `Revalidating X/Y` while running and include duration/token/failure
  metrics in terminal feedback.
- [ ] Run frontend tests and build to green.
- [ ] Commit the frontend slice.

### Task 5: Full verification and handoff

**Files:**
- Modify: `backend/tests/test_main_schema.py`
- Modify: `backend/tests/test_speaker_revalidation.py`
- Modify: `frontend/src/components/SpeakerNameMapper.test.mjs`

**Interfaces:**
- Produces: a clean local branch ready for independent review.

- [ ] Run focused backend and frontend checks.
- [ ] Run full backend Docker discovery, frontend `npm test`, and
  `npm run build`.
- [ ] Run `python -m compileall`, `git diff --check`, and `sentrux gate .`.
- [ ] Review the final diff against every ALP-118 bullet and commit.
- [ ] Comment on ALP-118 with branch, SHA, behavior, and gate evidence.
- [ ] Report branch and SHA to w2:p9 through the audited wrapper.

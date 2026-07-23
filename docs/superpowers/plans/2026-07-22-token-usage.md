# ALP-115 Token Usage Implementation Plan

**Goal:** Persist per-response token counts for session-scoped LLM calls and display post-call totals and breakdowns.

**Architecture:** Add one SQLAlchemy row per provider response, recorded through a shared best-effort helper. Pass optional attribution through the existing LLM entry point and use the same helper at direct/realtime provider boundaries. Aggregate with SQL in a session endpoint and render it in the existing post-call tab shell.

**Tech stack:** FastAPI, SQLAlchemy async, Alembic, unittest, React, TypeScript, Tailwind.

---

### Task 1: Persistence and aggregation API

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/sessions.py`
- Create: `backend/app/services/token_usage.py`
- Create: `backend/alembic/versions/*_add_token_usage.py`
- Create/modify tests under `backend/tests/`

1. Write failing tests for normalization, best-effort writes, zero totals, and source/model aggregation.
2. Add the minimal model, schemas, recorder, migration, and route.
3. Run the focused backend tests.

### Task 2: Shared and direct LLM capture

**Files:**
- Modify: `backend/app/services/llm.py`
- Modify callers under `backend/app/routers/` and `backend/app/services/`
- Modify/create focused backend tests

1. Write failing tests proving Gemini and OpenAI usage reaches the recorder with explicit attribution.
2. Add optional `session_id` and `source` to `generate_text`, then pass them from active call sites.
3. Record direct Gemini briefing, document-summary, and batch-transcription responses through the same helper.
4. Run the focused tests.

### Task 3: Realtime capture

**Files:**
- Modify: `backend/app/services/gemini_live.py`
- Modify: `backend/app/services/openai_realtime.py`
- Modify: `backend/app/services/agents/orchestrator.py`
- Modify/create focused backend tests

1. Write failing tests for Gemini cumulative positive deltas/reset and OpenAI completed-event usage.
2. Thread the session id into gateways and record normalized usage.
3. Run the focused tests.

### Task 4: Post-call Tokens tab

**Files:**
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/PostCall/PostCallView.tsx`
- Modify/create a focused frontend behavior test if an existing harness fits

1. Add the response type and API function.
2. Add the accessible Tokens tab and loading, empty, error, and breakdown states using existing styles.
3. Run the focused check and `npm run build`.

### Task 5: Verification and handoff

1. Run the full Docker backend gate with `r2-master-rollout-backend:latest`.
2. Run frontend install/build gates.
3. Run `git diff --check`, inspect the final diff, and commit only ALP-115 files.
4. Update Linear ALP-115 and report the branch ready for review to w2:p9.

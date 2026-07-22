# Gemini Default Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gemini 3.6 Flash and Gemini 3.5 Flash-Lite as selectable models, force the requested v0.2.5 defaults once on existing installations, and preserve normal selection afterward.

**Architecture:** `MODEL_REGISTRY` remains the single selector source. Fresh installs use updated settings and seed rows; the existing startup seed path performs the one-time existing-install update behind a `v0.2.5` marker. No frontend, schema, provider-client, or Live API changes are needed.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, PostgreSQL, `unittest`, Google Gen AI SDK.

## Global Constraints

- `gemini-3.6-flash`: Consolidated Analyst, Opportunity Specialist, Briefing Meeting Lens, Briefing Discovery Lens, Briefing Arbiter.
- `gemini-3.5-flash-lite`: Objection Handler and Batch Transcription.
- Audio Bridge remains `gemini-3.1-flash-live-preview`; Principal Agent remains unchanged.
- The v0.2.5 migration intentionally replaces existing selections once; subsequent user selections persist.
- Do not remove older models or add dependencies.

---

### Task 1: Registry and fresh-install defaults

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/services/seed_agents.py`
- Test: `backend/tests/test_llm_router.py`
- Test: `backend/tests/test_seed_agents.py`
- Test: `backend/tests/test_transcription_runtime.py`

**Interfaces:**
- Produces registry IDs `gemini-3.6-flash` and `gemini-3.5-flash-lite`.
- Produces `Settings.BATCH_TRANSCRIBER_MODEL == "gemini-3.5-flash-lite"`.
- Produces the six requested `SEED_CONFIGS[*]["model_id"]` assignments.

- [ ] **Step 1: Write failing registry/default tests**

Add assertions equivalent to:

```python
expected = {
    "gemini-3.6-flash": (True, True, False),
    "gemini-3.5-flash-lite": (True, True, False),
}
for model_id, capabilities in expected.items():
    entry = next(model for model in MODEL_REGISTRY if model["id"] == model_id)
    self.assertEqual("Google", entry["provider"])
    self.assertEqual("stable", entry["tier"])
    self.assertEqual("google", entry["requires_key"])
    self.assertEqual(capabilities, (
        entry["supports_text"],
        entry["supports_batch_audio"],
        entry["supports_live_audio"],
    ))
```

Assert the six seed mappings and the new batch default. Assert both new IDs are valid batch models and invalid live models.

- [ ] **Step 2: Run the focused tests and observe RED**

Run from `backend/`:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m unittest tests.test_llm_router tests.test_seed_agents tests.test_transcription_runtime -v
```

Expected: failures because the registry entries/default assignments do not exist yet.

- [ ] **Step 3: Implement the minimum registry and seed changes**

Add two stable Google entries after `gemini-3.5-flash`, each with:

```python
"requires_key": "google",
"supports_text": True,
"supports_batch_audio": True,
"supports_live_audio": False,
```

Set `BATCH_TRANSCRIBER_MODEL = "gemini-3.5-flash-lite"` and update only the six named `SEED_CONFIGS` rows.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run the Step 2 command. Expected: all focused tests pass.

### Task 2: One-time existing-install update

**Files:**
- Modify: `backend/app/services/seed_agents.py`
- Test: `backend/tests/test_seed_agents.py`

**Interfaces:**
- Marker: `defaults.models.version == "v0.2.5"`.
- Missing marker sets six agent rows plus `transcription.batch.model_id`.
- Current marker performs no writes, preserving later selections.

- [ ] **Step 1: Write the failing versioned-seed contract test**

Use a fake async session, call `apply_default_model_version(db)`, and assert the agent assignments contain exactly:

```python
{
    "consolidated_analyst": "gemini-3.6-flash",
    "opportunity_specialist": "gemini-3.6-flash",
    "brief_meeting_lens": "gemini-3.6-flash",
    "brief_discovery_lens": "gemini-3.6-flash",
    "brief_arbiter": "gemini-3.6-flash",
    "objection_handler": "gemini-3.5-flash-lite",
}
```

Also assert the step writes `transcription.batch.model_id = gemini-3.5-flash-lite` and `defaults.models.version = v0.2.5`. A second test supplies the current marker and asserts there are no writes.

- [ ] **Step 2: Run the seed test and observe RED**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m unittest tests.test_seed_agents -v
```

Expected: failure because the versioned seed helper is absent.

- [ ] **Step 3: Implement the versioned seed step**

Use these constants and call the helper after normal seeding commits:

```python
DEFAULT_MODEL_VERSION_KEY = "defaults.models.version"
DEFAULT_MODEL_VERSION = "v0.2.5"
FORCED_DEFAULT_MODELS = {
    "consolidated_analyst": "gemini-3.6-flash",
    "opportunity_specialist": "gemini-3.6-flash",
    "brief_meeting_lens": "gemini-3.6-flash",
    "brief_discovery_lens": "gemini-3.6-flash",
    "brief_arbiter": "gemini-3.6-flash",
    "objection_handler": "gemini-3.5-flash-lite",
}
```

`apply_default_model_version(db)` returns immediately when the marker matches.
Otherwise it updates the six rows, inserts or updates the batch setting and
marker, commits, and returns `True`.

- [ ] **Step 4: Run the migration and focused model tests**

Run both Task 1 and Task 2 commands. Expected: all pass.

### Task 3: Operator documentation and full verification

**Files:**
- Modify: `docs/configuration.md`

**Interfaces:**
- Documents the new batch fallback and both selectable stable IDs.

- [ ] **Step 1: Update configuration documentation**

Change the `BATCH_TRANSCRIBER_MODEL` default to `gemini-3.5-flash-lite` and include both new IDs in the supported Google model list.

- [ ] **Step 2: Run complete verification**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m unittest discover -s backend/tests -t backend -v
& 'C:\Program Files\nodejs\npm.cmd' test --prefix frontend
& 'C:\Program Files\nodejs\npm.cmd' run build --prefix frontend
& 'C:\Program Files\nodejs\npm.cmd' run test:pwa --prefix frontend -- --dist
```

Expected: backend and frontend tests pass; frontend builds; dist PWA checks pass.

- [ ] **Step 3: Verify the startup update against Docker PostgreSQL**

Rebuild and restart the Backchannel backend from the clean worktree, then query `agent_configs` plus `app_settings` to confirm all seven assignments and `defaults.models.version = v0.2.5`. Expected: exact values from Tasks 1 and 2.

- [ ] **Step 4: Commit and push the implementation**

```powershell
git add -- backend/app/config.py backend/app/services/seed_agents.py backend/tests/test_llm_router.py backend/tests/test_seed_agents.py backend/tests/test_transcription_runtime.py docs/configuration.md docs/superpowers/plans/2026-07-22-gemini-default-models.md docs/superpowers/specs/2026-07-22-gemini-default-models-design.md
git diff --cached --check
git commit -m "feat: add latest Gemini model defaults"
git push origin master
```

Expected: clean `master` synchronized with `origin/master`; v0.2.5 remains untagged until release metadata and release contracts pass.

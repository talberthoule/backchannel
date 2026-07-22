# Gemini Default Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gemini 3.6 Flash and Gemini 3.5 Flash-Lite as selectable models, force the requested v0.2.5 defaults once on existing installations, and preserve normal selection afterward.

**Architecture:** `MODEL_REGISTRY` remains the single selector source. Fresh installs use updated settings and seed rows; Alembic revision 016 performs the one-time existing-install update. No frontend, schema, provider-client, or Live API changes are needed.

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

### Task 2: One-time existing-install migration

**Files:**
- Create: `backend/alembic/versions/016_default_gemini_models.py`
- Create: `backend/tests/test_default_model_migration.py`

**Interfaces:**
- Alembic revision: `016`, down revision: `015`.
- Upgrade sets six agent rows plus `transcription.batch.model_id`.
- Downgrade reverts only values still equal to the v0.2.5 assignments.

- [ ] **Step 1: Write the failing migration contract test**

Load revision 016 with `importlib.util.spec_from_file_location`, patch `migration.op.execute`, call `upgrade()`, and assert the bound statement parameters contain exactly:

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

Also assert the final upgrade statement upserts key `transcription.batch.model_id` with value `gemini-3.5-flash-lite`.

- [ ] **Step 2: Run the migration test and observe RED**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m unittest tests.test_default_model_migration -v
```

Expected: failure because revision 016 is absent.

- [ ] **Step 3: Implement revision 016**

Use these mappings and parameter-bound statements:

```python
AGENT_DEFAULTS = {
    "consolidated_analyst": ("gemini-3.6-flash", "gemini-3.5-flash"),
    "opportunity_specialist": ("gemini-3.6-flash", "gemini-3.5-flash"),
    "brief_meeting_lens": ("gemini-3.6-flash", "gemini-3.5-flash"),
    "brief_discovery_lens": ("gemini-3.6-flash", "gemini-3.5-flash"),
    "brief_arbiter": ("gemini-3.6-flash", "gemini-3.1-pro-preview"),
    "objection_handler": ("gemini-3.5-flash-lite", "gemini-3.5-flash"),
}
BATCH_KEY = "transcription.batch.model_id"
BATCH_DEFAULT = "gemini-3.5-flash-lite"
PREVIOUS_BATCH_DEFAULT = "gemini-3.5-flash"


def upgrade():
    for slug, (model_id, _) in AGENT_DEFAULTS.items():
        op.execute(
            sa.text(
                "UPDATE agent_configs SET model_id = :model_id WHERE slug = :slug"
            ).bindparams(model_id=model_id, slug=slug)
        )
    op.execute(
        sa.text(
            "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ).bindparams(key=BATCH_KEY, value=BATCH_DEFAULT)
    )


def downgrade():
    for slug, (new_model_id, old_model_id) in AGENT_DEFAULTS.items():
        op.execute(
            sa.text(
                "UPDATE agent_configs SET model_id = :old_model_id "
                "WHERE slug = :slug AND model_id = :new_model_id"
            ).bindparams(
                old_model_id=old_model_id,
                slug=slug,
                new_model_id=new_model_id,
            )
        )
    op.execute(
        sa.text(
            "UPDATE app_settings SET value = :old_value "
            "WHERE key = :key AND value = :new_value"
        ).bindparams(
            old_value=PREVIOUS_BATCH_DEFAULT,
            key=BATCH_KEY,
            new_value=BATCH_DEFAULT,
        )
    )
```

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

- [ ] **Step 3: Verify the migration against Docker PostgreSQL**

Rebuild the Backchannel stack from the clean worktree, run `alembic upgrade head`, and query `agent_configs` plus `app_settings` to confirm all seven assignments. Expected: exact values from Tasks 1 and 2.

- [ ] **Step 4: Commit and push the implementation**

```powershell
git add -- backend/app/config.py backend/app/services/seed_agents.py backend/alembic/versions/016_default_gemini_models.py backend/tests/test_llm_router.py backend/tests/test_seed_agents.py backend/tests/test_transcription_runtime.py backend/tests/test_default_model_migration.py docs/configuration.md docs/superpowers/plans/2026-07-22-gemini-default-models.md
git diff --cached --check
git commit -m "feat: add latest Gemini model defaults"
git push origin master
```

Expected: clean `master` synchronized with `origin/master`; v0.2.5 remains untagged until release metadata and release contracts pass.

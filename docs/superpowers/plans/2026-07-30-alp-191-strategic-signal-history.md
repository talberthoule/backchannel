# ALP-191 Durable Strategic-Signal History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist bounded live strategic-signal history and give both briefing lenses complete, bounded insight and signal context without exposing history through the API.

**Architecture:** Reuse the advisory-locked live `SessionSynthesis` row by adding a server-only JSON history column. Merge successful live cards into that bounded history at write time, then compactly admit the newest saved insights and signal entries into the lenses' existing `{insights_text}` prompt value. Keep the arbiter's current source-isolated contract unchanged.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL JSON, Alembic, Pydantic, stdlib `unittest`.

## Global Constraints

- Work only in `C:/work/backchannel/alp-191` on `talberthoule/alp-191-durable-strategic-signals-history-with-deduplicated-briefing`.
- Do not touch the shared checkout, the orchestrator constructor/activity roster, ALP-188 provider onboarding, or frontend files.
- Do not push. Commit the lane and merge it into local `master` only after coordination shows the shared checkout is clean.
- `signal_history` stays server-only and must not appear in `SessionSynthesisOut`.
- Only successful `mode="live"` persistence may change history.
- Use whole-list JSON reassignment, a 200-entry storage cap, a 12,000-character insight prompt budget, and a 6,000-character signal-history prompt budget.
- Preserve blank/unselected model behavior; never infer or replace a model assignment.

---

### Task 1: Add the server-only history column

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Create: `backend/alembic/versions/021_add_signal_history.py`
- Modify: `backend/tests/test_main_schema.py`

**Interfaces:**
- Produces: `SessionSynthesis.signal_history: list`, defaulting to `[]`.
- Produces: Alembic revision `021`, down revision `020`.
- Preserves: `SessionSynthesisOut` has no `signal_history` field.

- [ ] **Step 1: Write failing schema and migration tests**

Add assertions that the ORM model has `signal_history`, the API schema does not,
startup patching emits `ADD COLUMN signal_history JSON NOT NULL DEFAULT '[]'`,
and revision 021 adds/drops that exact column.

```python
def test_signal_history_is_server_only(self):
    self.assertIn("signal_history", SessionSynthesis.__table__.columns)
    self.assertNotIn("signal_history", SessionSynthesisOut.model_fields)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest tests.test_main_schema
```

Expected: failure because the model, startup patch, and revision do not exist.

- [ ] **Step 3: Implement the minimal schema change**

Add:

```python
signal_history: Mapped[list] = mapped_column(JSON, default=list)
```

Create revision 021 with a non-null JSON empty-list server default, and add the
equivalent guarded startup `ALTER TABLE` statement. Do not change
`SessionSynthesisOut`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2. Expected: all `test_main_schema` tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/models.py backend/app/main.py backend/alembic/versions/021_add_signal_history.py backend/tests/test_main_schema.py
git commit -m "feat: add durable strategic signal history storage (ALP-191)"
```

### Task 2: Merge successful live cycles into bounded history

**Files:**
- Modify: `backend/app/services/briefing_synthesis.py`
- Modify: `backend/tests/test_strategic_signals.py`

**Interfaces:**
- Produces: `_merge_signal_history(existing, output, captured_at, model_id) -> list[dict]`.
- Consumes: the five live `BriefArbiterOutput` sections named in the design.
- Updates: `_persist_synthesis` assigns the returned list only for completed live mode.

- [ ] **Step 1: Write failing merge tests**

Cover normalized-title identity, latest-body replacement, occurrence count,
first/last timestamps, changed-title preservation, latest-only evidence refs,
empty-title summary fallback, and 200-entry oldest eviction.

```python
first = _merge_signal_history([], output("Budget Risk", "First"), t1, "m1")
second = _merge_signal_history(
    json.loads(json.dumps(first)),
    output(" budget risk. ", "Latest"),
    t2,
    "m2",
)
self.assertEqual(1, len(second))
self.assertEqual(2, second[0]["count"])
self.assertEqual("Latest", second[0]["summary"])
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest tests.test_strategic_signals
```

Expected: import failure because `_merge_signal_history` does not exist.

- [ ] **Step 3: Implement the pure merge helper**

Use only stdlib string normalization and list operations. Reassign a new list;
never mutate `existing` in place. Add a `ponytail:` comment documenting that
the 200-entry JSON cap is the ceiling and a snapshot table is the upgrade path.

- [ ] **Step 4: Verify the merge tests pass**

Run the command from Step 2. Expected: all strategic-signals tests pass.

- [ ] **Step 5: Write failing persistence guard tests**

Patch the persistence session with an instrumented `SessionSynthesis` and prove:

- completed live persistence assigns a new list;
- a JSON round-trip between two calls preserves and increments history;
- post-call, partial, and error persistence do not change history.

- [ ] **Step 6: Run the guard tests and verify RED**

Run the command from Step 2. Expected: guard assertions fail because
`_persist_synthesis` does not update history.

- [ ] **Step 7: Add the guarded assignment inside the locked scope**

After the synthesis row is locked/created and before commit:

```python
if mode == "live" and status == "completed":
    synthesis.signal_history = _merge_signal_history(
        synthesis.signal_history or [],
        arbiter_output,
        now,
        model_ids.get("strategic_signals", ""),
    )
```

- [ ] **Step 8: Run the focused tests and verify GREEN**

Run the command from Step 2. Expected: all strategic-signals tests pass.

- [ ] **Step 9: Commit**

```powershell
git add backend/app/services/briefing_synthesis.py backend/tests/test_strategic_signals.py
git commit -m "feat: retain bounded live signal history (ALP-191)"
```

### Task 3: Supply rich bounded insight and signal context to both lenses

**Files:**
- Modify: `backend/app/services/briefing_synthesis.py`
- Modify: `backend/tests/test_briefing_synthesis.py`
- Modify: `backend/tests/test_briefing_provider_routing.py`

**Interfaces:**
- Updates: `_question_dict` includes `answer_summary`, `followup_question`, and `agent_source`.
- Produces: compact bounded insight JSON and compact bounded signal-history JSON.
- Updates: `_build_context` appends the history block to `insights_text`.
- Preserves: arbiter receives meeting context and two lens outputs only.

- [ ] **Step 1: Write failing rich-insight tests**

Assert that one non-dismissed `asked` item renders its query in `question`, its
response in `answer_summary`, and includes source, answer/follow-up state,
follow-up question, vote, offering match, and agent source.

- [ ] **Step 2: Write failing budget tests**

Create oversized ordered insight/history inputs and assert compact valid JSON,
newest-first admission, chronological rendering, explicit truncation metadata,
and survival of the newest fitting entry.

- [ ] **Step 3: Run focused context tests and verify RED**

Run:

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest tests.test_briefing_synthesis
```

Expected: failures because the fields, budgets, and history formatter are absent.

- [ ] **Step 4: Implement the minimum bounded formatters**

Follow `live_chat_context.format_live_insights`: compact separators, reverse
admission, chronological output, and a truncation flag. Keep insight and
history budgets separate. Query the server-only live synthesis history in
`_build_context` and append it under a clear label within `insights_text`.

- [ ] **Step 5: Run focused context tests and verify GREEN**

Run the command from Step 3. Expected: all briefing synthesis tests pass.

- [ ] **Step 6: Write the failing lens/arbiter boundary test**

Capture all three prompts. Assert both lens prompts contain the rich asked row
and history marker. Assert the arbiter prompt contains meeting context and both
lens JSON outputs but no transcript id, insight id, directive, document, speaker,
or history marker.

- [ ] **Step 7: Run provider-routing tests and verify RED**

Run:

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest tests.test_briefing_provider_routing
```

Expected: the new boundary assertions fail until context assembly is wired.

- [ ] **Step 8: Wire context into the existing lens placeholder only**

Do not add raw context arguments to the arbiter call. Both default and custom
lens prompts that retain `{insights_text}` receive the combined context.

- [ ] **Step 9: Run focused suites and verify GREEN**

Run:

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest tests.test_briefing_synthesis tests.test_strategic_signals tests.test_briefing_provider_routing tests.test_main_schema
```

Expected: all focused tests pass.

- [ ] **Step 10: Commit**

```powershell
git add backend/app/services/briefing_synthesis.py backend/tests/test_briefing_synthesis.py backend/tests/test_briefing_provider_routing.py
git commit -m "feat: enrich briefing context with signal history (ALP-191)"
```

### Task 4: Verify, document delivery, and merge locally

**Files:**
- Modify: `docs/superpowers/plans/2026-07-30-alp-191-strategic-signal-history.md` only if execution exposed a plan correction.
- No production file changes are expected in this task.

**Interfaces:**
- Produces: a verified ALP-191 branch commit.
- Produces: a Linear results comment and local `master` merge.

- [ ] **Step 1: Run diff and structural checks**

```powershell
git diff --check master...HEAD
C:\Users\thoule\.local\bin\sentrux.exe check .
C:\Users\thoule\.local\bin\sentrux.exe gate .
```

- [ ] **Step 2: Run the full backend suite**

```powershell
cd backend
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest discover -s tests
```

Expected: all tests pass except the documented Windows key-file mode mismatch
if it remains the sole failure.

- [ ] **Step 3: Confirm scope**

```powershell
git status --short
git diff --stat master...HEAD
git log --oneline master..HEAD
```

Verify there are no frontend, orchestrator constructor, activity roster,
provider-onboarding, or unrelated files.

- [ ] **Step 4: Post ALP-191 verification evidence**

Add a Linear comment with focused/full suite counts, the known environmental
failure if present, Sentrux results, branch, and commit ids. Move ALP-191 to
In Review before integration and Done only after the local merge is verified.

- [ ] **Step 5: Coordinate the merge**

Snapshot/read the Backchannel Herdr panes. Confirm the shared checkout is clean
and no lane is mutating local `master`. Rebase the ALP-191 branch if `master`
moved, rerun focused tests, then merge with `git merge --ff-only` from the
shared checkout.

- [ ] **Step 6: Verify the local merge**

```powershell
git status --short
git log -5 --oneline --decorate
git merge-base --is-ancestor <ALP-191-final-sha> master
```

Do not push.

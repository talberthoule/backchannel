# ALP-188 First-Run Model Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fresh installs explicitly unselected, prevent silent cloud fallbacks, and guide users to provider-aware cloud or fit-tested local model choices without changing saved selections when credentials change.

**Architecture:** Keep the existing non-null empty `model_id` as the unselected state. Centralize recommendation data in the existing model registry response, reuse Local Fit measurements for local recommendations, and let existing model-option/onboarding presentation helpers render the resulting state. Runtime services block enabled unselected roles before constructing clients or starting work.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, React, TypeScript, Node test runner, stdlib `unittest`.

## Global Constraints

- Work only in `C:/work/backchannel/alp-188` on `agent/alp-188-first-run-model-setup`, based on `8a9f692`.
- Do not push or merge; coordinator `w1:pW` owns review and merge.
- Do not add a migration. Revisions 021 and 022 belong to ALP-191 and ALP-181.
- Preserve every nonempty agent selection, prompt, interval, budget, app setting, and session enable override.
- Never auto-assign an agent model when a key, endpoint, or fit result changes.
- Keep batch transcription separate from analysis agents and keep Live Ask optional for first-run completion.
- Reuse `modelOptions.ts`, `providerOnboarding.ts`, and the existing Local Fit apply endpoint; do not add a second model renderer, readiness system, or bulk-apply endpoint.
- Coordinate `site/index.html` edits with ALP-185 before touching contended copy.
- Add behavioral tests before each production change and observe the focused failure before implementation.

---

### Task 1: Seed explicit unselected defaults

**Files:**
- Modify: `backend/app/services/seed_agents.py`
- Modify: `backend/tests/test_seed_agents.py`
- Modify: `backend/tests/test_transcription_runtime.py`

**Interfaces:**
- Fresh agent rows, including `audio_gateway`, receive `model_id=""`.
- Existing nonempty rows are never rewritten by a default-version migrator.
- An absent batch transcription setting receives `local-whisper-base`; an explicit persisted value is preserved.

- [ ] **Step 1: Add failing seed tests**

Cover fresh blank rows, missing-row insertion, preservation of existing rows, retirement of the force-default version writer, and keyless batch default behavior.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest tests.test_seed_agents
```

- [ ] **Step 3: Make seed data blank and delete the force-default refresh path**

Use the existing seed loop and setting helpers. Do not add first-run flags or schema.

- [ ] **Step 4: Run focused tests and verify GREEN**

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/seed_agents.py backend/tests
git commit -m "fix: seed explicit unselected model defaults (ALP-188)"
```

### Task 2: Block unselected runtime work

**Files:**
- Modify: `backend/app/services/llm.py`
- Modify: `backend/app/services/transcription_runtime.py`
- Modify: `backend/app/services/agents/orchestrator.py`
- Modify: agent constructors and shared model lookup callers that currently coerce `""` to a cloud fallback
- Modify: `backend/app/services/briefing_synthesis.py`
- Modify: focused backend tests for LLM routing, orchestration, transcription, briefing, analyze, and speaker enhancement

**Interfaces:**
- Empty model calls fail at the shared LLM boundary with an actionable no-model error.
- An enabled unselected agent reports `state="blocked"` and `blocked_reason="no_model"` before privacy or meeting-type checks.
- Unselected audio does not construct/connect a gateway; unselected text/meta roles do not start loops or invoke providers.
- End Call completes while unselected briefing roles persist an actionable blocked result.
- Explicit `""` remains blank; constructor defaults may apply only when the caller passes `None`.

- [ ] **Step 1: Add failing shared-boundary and explicit-empty tests**

Test `provider_for`/call preparation, transcription runtime, agent constructors, borrowed-model helpers, analyze/speaker helpers, and briefing model resolution.

- [ ] **Step 2: Run the focused modules and verify RED**

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest tests.test_llm_router tests.test_transcription_runtime tests.test_runtime_activity tests.test_briefing_provider_routing
```

- [ ] **Step 3: Add the minimum shared guard and remove empty-string fallbacks**

Use `is None` where a true optional override needs a default. Keep empty strings intact everywhere else.

- [ ] **Step 4: Add failing activity and lifecycle tests**

Cover no-model precedence, gateway non-construction, guarded close/reconnect paths, no loop startup, and blocked briefing persistence.

- [ ] **Step 5: Implement the orchestrator and briefing blocked states**

Extend existing activity records; do not create a parallel readiness object.

- [ ] **Step 6: Run all focused runtime tests and verify GREEN**

- [ ] **Step 7: Commit**

```powershell
git add backend/app backend/tests
git commit -m "fix: block unselected agents before provider routing (ALP-188)"
```

### Task 3: Publish structured provider recommendations

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/models.py`
- Modify: `backend/app/services/local_fit.py`
- Modify: focused model-registry and Local Fit tests

**Interfaces:**
- `GET /api/models` returns structured recommendation metadata for agent role, provider category, recommendation state, and optional optimized interval/reasoning effort.
- Static cloud recommendations use the approved OpenAI/Google role matrix.
- Only `brief_arbiter` recommends `gpt-5.6-sol` with `reasoning_effort="high"`.
- Local recommendations require a current compatible green fit and choose lowest effective latency, breaking ties by model id.
- Live local roles may include an optimized interval; post-call roles do not.

- [ ] **Step 1: Add failing cloud recommendation response tests**

Assert the role/provider matrix, one recommendation per provider/role where applicable, and the Arbiter-only Sol/high-effort rule.

- [ ] **Step 2: Run focused registry tests and verify RED**

- [ ] **Step 3: Add the smallest static metadata mapping beside the existing registry**

Return structured fields through the current response schema; do not suffix display labels.

- [ ] **Step 4: Add failing Local Fit recommendation tests**

Cover current green admission, stale/fingerprint/config/model incompatibility rejection, contention-adjusted role verdicts, latency/tie ordering, interval inclusion, and ASR live feasibility.

- [ ] **Step 5: Reuse existing Local Fit scoring to annotate eligible local models**

Keep the current apply endpoint interval-only. Selecting a model remains a separate explicit agent update.

- [ ] **Step 6: Run focused recommendation tests and verify GREEN**

- [ ] **Step 7: Commit**

```powershell
git add backend/app/config.py backend/app/schemas.py backend/app/routers/models.py backend/app/services/local_fit.py backend/tests
git commit -m "feat: expose provider-aware model recommendations (ALP-188)"
```

### Task 4: Render explicit selection, readiness, and activity

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/modelOptions.ts`
- Modify: `frontend/src/lib/providerOnboarding.ts`
- Modify: `frontend/src/components/AdminPanel.tsx`
- Modify: `frontend/src/components/BatchTranscriptionCard.tsx`
- Modify: `frontend/src/components/ModelChip.tsx`
- Modify: `frontend/src/components/AgentActivityPanel.tsx`
- Modify: existing frontend Node tests and `frontend/package.json` only if a new test file must be registered

**Interfaces:**
- Every agent picker begins with `Not selected`.
- Models remain grouped as OpenAI, Google, and Local; on-prem compatible endpoints remain Local and retain endpoint identity in labels.
- Recommended badges/text come from structured metadata in both native selects and `ModelChip`.
- Blank enabled agents make provider onboarding incomplete; local-only no longer bypasses readiness.
- Credential/endpoint refresh updates available models and guidance without changing any saved model id.
- Collapsed activity adds `N need setup` while retaining ALP-189 summary counts.

- [ ] **Step 1: Add failing model-option and readiness tests**

Cover Not selected, structured badges, provider grouping, endpoint labels, blank-agent readiness, privacy impact, and credential refresh preservation.

- [ ] **Step 2: Run Node tests and verify RED**

```powershell
node --test src/lib/modelOptions.test.ts src/lib/providerOnboarding.test.ts
```

- [ ] **Step 3: Extend the existing presentation/readiness owners**

Keep native controls and the existing popover; do not introduce a new picker abstraction.

- [ ] **Step 4: Add failing activity-panel behavior coverage**

Assert the collapsed no-model count and expanded actionable reason.

- [ ] **Step 5: Render the setup count and actionable copy**

- [ ] **Step 6: Run focused Node tests and `npm run build`**

- [ ] **Step 7: Commit**

```powershell
git add frontend
git commit -m "feat: guide explicit agent model selection (ALP-188)"
```

### Task 5: Make Live Ask explicitly selectable

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/DirectiveBar.tsx`
- Modify: focused frontend behavior tests

**Interfaces:**
- Preserve a valid stored Live Ask model; otherwise keep it `""`.
- Never borrow from Objection Handler, Consolidated Analyst, or the first available text model.
- Show the existing model picker in the Ask surface.
- Submitting without a model keeps draft text and shows an actionable error.
- Live Ask does not count toward first-run completion.

- [ ] **Step 1: Add failing stored-selection and empty-submit tests**

- [ ] **Step 2: Run focused tests and verify RED**

- [ ] **Step 3: Remove fallback selection and expose explicit picker/error state**

- [ ] **Step 4: Run focused tests and build, then verify GREEN**

- [ ] **Step 5: Commit**

```powershell
git add frontend/src
git commit -m "fix: require explicit Live Ask model selection (ALP-188)"
```

### Task 6: Align setup guidance and coupled documentation

**Files:**
- Modify: `frontend/src/components/ProviderOnboardingCard.tsx`
- Modify: `frontend/src/components/WelcomeView.tsx`
- Modify: `docs/agents.md`
- Modify: `site/index.html`
- Modify: `docs-site/site.test.js`
- Modify: relevant frontend copy tests

**Interfaces:**
- Setup copy describes currently available capabilities and directs users to Agents and Transcription.
- Copy does not demand Gemini or imply credentials automatically configure agents.
- Public docs match blank seed defaults, provider recommendations, Local Fit gating, and explicit selection.

- [ ] **Step 1: Re-check ALP-185 ownership before editing `site/index.html`**

Use the Herdr audited wrapper. If ALP-185 still owns a line, coordinate the exact edit rather than overwriting it.

- [ ] **Step 2: Add failing copy/docs assertions**

- [ ] **Step 3: Update the minimum coupled copy**

- [ ] **Step 4: Run frontend copy tests and docs-site site tests**

```powershell
node --test site.test.js
```

- [ ] **Step 5: Commit**

```powershell
git add frontend docs site docs-site
git commit -m "docs: explain explicit provider model setup (ALP-188)"
```

### Task 7: Verify, report, and request coordinator review

**Files:**
- Modify only test fixes required by observed ALP-188 regressions
- Update: `docs/superpowers/plans/2026-07-30-alp-188-first-run-model-setup.md`

- [ ] **Step 1: Run the complete backend suite**

```powershell
C:\Users\Houle\.venvs\backchannel312\Scripts\python.exe -m unittest discover -s tests
```

The known Windows-only `test_master_key_file_created_private` `0o600`/`0o666` mismatch may remain only if it is the sole failure.

- [ ] **Step 2: Run frontend tests and build**

```powershell
npm test
npm run build
```

- [ ] **Step 3: Run coupled docs-site tests**

```powershell
npm run test:site
node --test *.test.js
npm run build
```

- [ ] **Step 4: Run structural checks**

```powershell
C:\Users\thoule\.local\bin\sentrux.exe check .
C:\Users\thoule\.local\bin\sentrux.exe gate .
```

- [ ] **Step 5: Review the diff and confirm clean worktree**

Check that no existing nonempty choice is rewritten, no credential change saves agent ids, no implicit cloud fallback remains, and no migration was added.

- [ ] **Step 6: Commit final test/plan evidence**

- [ ] **Step 7: Post Linear verification evidence and set ALP-188 to In Review**

Include commit SHA, exact test counts, known environmental exception if present, and scope preserved.

- [ ] **Step 8: Send the coordinator the branch SHA and Linear comment id**

Use the Herdr audited wrapper and request review. Do not merge or push.

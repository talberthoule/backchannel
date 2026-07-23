# Standalone Live Strategic Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the briefing trio's 45-second live loop with one configurable `strategic_signals` agent while preserving live cards, evidence linkage, automatic insight upvotes, and post-call briefing behavior.

**Architecture:** A new seeded meta-agent performs one structured live synthesis call and persists the existing `SessionSynthesis(mode="live")` payload. The orchestrator and live refresh route call that agent; `run_session_synthesis` becomes post-call-only and remains the sole path through the two briefing lenses and arbiter.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy async, Google GenAI structured output, React 19, TypeScript, Node test runner, static HTML.

## Global Constraints

- `strategic_signals` defaults to enabled, `gemini-3.6-flash`, and a 45-second cycle.
- It produces live cards only and never inserts durable insight rows.
- Every card must retain evidence references to existing insight IDs so the current frontend linkage and automatic `vote: 1` behavior remains unchanged.
- `brief_meeting_lens`, `brief_discovery_lens`, and `brief_arbiter` run only at full End Call or explicit post-call refresh.
- `End without briefing` continues to skip the briefing trio.
- Preserve all held landing-page polish and accessibility changes.
- Add no dependency or schema migration.

---

### Task 1: Seed and configure the standalone agent

**Files:**
- Modify: `backend/app/services/agents/prompts.py`
- Modify: `backend/app/services/seed_agents.py`
- Modify: `backend/tests/test_seed_agents.py`

**Interfaces:**
- Produces: `STRATEGIC_SIGNALS_PROMPT: str`
- Produces: seeded slug `strategic_signals` with `interval_seconds=45`

- [ ] **Step 1: Write the failing seed test**

```python
def test_strategic_signals_is_a_configurable_live_agent(self):
    cfg = _seed_config("strategic_signals")
    self.assertEqual("Strategic Signals", cfg["name"])
    self.assertEqual("meta", cfg["agent_type"])
    self.assertEqual("gemini-3.6-flash", cfg["model_id"])
    self.assertEqual(45, cfg["interval_seconds"])
    self.assertTrue(cfg["enabled"])
    self.assertIn("{insights_text}", cfg["prompt"])
    self.assertIn("evidence_refs", cfg["prompt"])
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m unittest tests.test_seed_agents.SeedAgentConfigTests.test_strategic_signals_is_a_configurable_live_agent`

Expected: FAIL because `_seed_config("strategic_signals")` raises `StopIteration`.

- [ ] **Step 3: Add the minimal prompt and seed row**

Add `STRATEGIC_SIGNALS_PROMPT` with the existing context placeholders:

```python
STRATEGIC_SIGNALS_PROMPT = """You are the live strategic-signals agent for a conversation assistant.

Return one compact structured view for action during the active call.
Populate Signal, Risk, Next Question, Opportunity, and Action Cue through the
provided synthesis schema. Link every supported card directly to existing
insight IDs in evidence_refs. Do not create new insights or invent evidence.

## Meeting Context
{meeting_context_text}
## Participants
{speakers_text}
## Call Directives
{directives_text}
## Pre-Call Context
{document_summaries}
## Existing Insights
{insights_text}
## Transcript
{transcript_text}
"""
```

Import it in `seed_agents.py`, add it to `DEFAULT_PROMPTS`, and add:

```python
{
    "slug": "strategic_signals",
    "name": "Strategic Signals",
    "description": "Single-pass live synthesis that surfaces the signal, risk, next question, opportunity, and action cue while linking supported cards to saved insights.",
    "agent_type": "meta",
    "model_id": "gemini-3.6-flash",
    "prompt": STRATEGIC_SIGNALS_PROMPT,
    "enabled": True,
    "sub_types": "",
    "interval_seconds": 45,
    "display_order": 9,
},
```

Remove live-mode responsibilities from the three briefing prompts by telling
them to leave `strategic_signals` empty.

- [ ] **Step 4: Run seed tests and confirm GREEN**

Run: `python -m unittest tests.test_seed_agents`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/agents/prompts.py backend/app/services/seed_agents.py backend/tests/test_seed_agents.py
git commit -m "feat: seed standalone strategic signals agent"
```

---

### Task 2: Run live strategic signals in one structured call

**Files:**
- Create: `backend/app/services/agents/strategic_signals.py`
- Create: `backend/tests/test_strategic_signals.py`
- Modify: `backend/app/services/briefing_synthesis.py`

**Interfaces:**
- Produces: `STRATEGIC_SIGNALS_SLUG = "strategic_signals"`
- Produces: `run_strategic_signals_cycle(session_id, agent_configs=None, transcript_window=None, directives=None, doc_summaries=None, speakers=None, active_questions=None) -> SessionSynthesis | None`
- Consumes: existing `BriefArbiterOutput`, synthesis context builder, structured generator, and persistence path

- [ ] **Step 1: Write failing runner tests**

Use fake config and patch the context/generator/persistence boundaries:

```python
class StrategicSignalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_uses_one_model_call_and_preserves_evidence_refs(self):
        output = BriefArbiterOutput(
            strategic_signals=[
                BriefItem(
                    title="Budget is the gating signal",
                    evidence_refs=[EvidenceRef(insight_id="insight-1", type="insight")],
                )
            ]
        )
        configs = {
            "strategic_signals": SimpleNamespace(
                enabled=True,
                model_id="test-model",
                prompt=STRATEGIC_SIGNALS_PROMPT,
            )
        }
        context = SimpleNamespace(
            meeting_context_text="ctx",
            transcript_text="transcript",
            directives_text="none",
            document_summaries="none",
            speakers_text="Speaker 1",
            insights_text="- insight_id=insight-1",
        )
        persisted = SimpleNamespace(strategic_signals=[output.strategic_signals[0].model_dump()])
        with (
            patch("app.services.agents.strategic_signals.is_local_only", new=AsyncMock(return_value=False)),
            patch("app.services.agents.strategic_signals._build_context", new=AsyncMock(return_value=context)),
            patch("app.services.agents.strategic_signals.resolve_provider_key", new=AsyncMock(return_value="test")),
            patch("app.services.agents.strategic_signals.genai.Client"),
            patch("app.services.agents.strategic_signals._generate_structured", new=AsyncMock(return_value=output)) as generate,
            patch("app.services.agents.strategic_signals._persist_synthesis", new=AsyncMock(return_value=persisted)),
        ):
            result = await run_strategic_signals_cycle(uuid4(), agent_configs=configs)
        generate.assert_awaited_once()
        self.assertEqual("insight-1", result.strategic_signals[0]["evidence_refs"][0]["insight_id"])

    async def test_cycle_skips_when_agent_is_disabled(self):
        result = await run_strategic_signals_cycle(
            uuid4(),
            agent_configs={"strategic_signals": SimpleNamespace(enabled=False)},
        )
        self.assertIsNone(result)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m unittest tests.test_strategic_signals`

Expected: FAIL because `app.services.agents.strategic_signals` does not exist.

- [ ] **Step 3: Implement one-call live synthesis**

Create the module with this flow:

```python
STRATEGIC_SIGNALS_SLUG = "strategic_signals"

async def run_strategic_signals_cycle(...):
    if await is_local_only():
        raise LocalOnlyModeError("live strategic signals")
    configs = agent_configs or await load_agent_configs(session_id)
    cfg = configs.get(STRATEGIC_SIGNALS_SLUG)
    if not cfg or not cfg.enabled:
        return None
    context = await _build_context(
        session_id,
        mode="live",
        transcript_window=transcript_window,
        directives=directives,
        doc_summaries=doc_summaries,
        speakers=speakers,
        active_questions=active_questions,
    )
    if not context.transcript_text or context.transcript_text == "(No transcript yet)":
        return None
    prompt = format_prompt_with_meeting_context(
        cfg.prompt or STRATEGIC_SIGNALS_PROMPT,
        context.meeting_context_text,
        mode="live",
        speakers_text=context.speakers_text,
        directives_text=context.directives_text,
        document_summaries=context.document_summaries,
        insights_text=context.insights_text,
        transcript_text=context.transcript_text,
    )
    client = genai.Client(api_key=await resolve_provider_key("google"))
    output = await _generate_structured(
        client, cfg.model_id, prompt, BriefArbiterOutput,
        session_id=session_id, source=STRATEGIC_SIGNALS_SLUG,
    )
    return await _persist_synthesis(
        session_id=session_id,
        mode="live",
        status="completed",
        meeting_output=None,
        discovery_output=None,
        arbiter_output=output,
        model_ids={STRATEGIC_SIGNALS_SLUG: cfg.model_id},
    )
```

Keep persistence in `briefing_synthesis.py`; import its internal helpers rather
than duplicating database locking, token accounting, or structured-call retry.
Update that module's docstring to describe shared live/post-call synthesis
storage.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run: `python -m unittest tests.test_strategic_signals tests.test_briefing_synthesis`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/agents/strategic_signals.py backend/app/services/briefing_synthesis.py backend/tests/test_strategic_signals.py
git commit -m "feat: generate live strategic signals in one call"
```

---

### Task 3: Separate live and post-call triggers

**Files:**
- Modify: `backend/app/services/agents/orchestrator.py`
- Modify: `backend/app/routers/synthesis.py`
- Modify: `backend/tests/test_orchestrator_graceful_drain.py`
- Create: `backend/tests/test_synthesis_router.py`

**Interfaces:**
- Consumes: `run_strategic_signals_cycle`
- Preserves: `run_session_synthesis(..., mode="post_call")`

- [ ] **Step 1: Write failing trigger tests**

Add tests proving:

```python
async def test_live_cycle_calls_only_strategic_signals(self):
    orchestrator = self._build_orchestrator(include_briefing=True)
    orchestrator._agent_configs["strategic_signals"] = MagicMock(
        enabled=True, model_id="signal-model", prompt="signal-prompt", interval_seconds=45
    )
    with (
        patch("app.services.agents.orchestrator.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError()])),
        patch("app.services.agents.orchestrator.run_strategic_signals_cycle", new=AsyncMock(return_value=None)) as signals,
        patch("app.services.agents.orchestrator.run_session_synthesis", new=AsyncMock()) as briefing,
    ):
        with self.assertRaises(asyncio.CancelledError):
            await orchestrator._strategic_signals_loop()
    signals.assert_awaited_once()
    briefing.assert_not_awaited()

async def test_live_refresh_dispatches_to_strategic_signals(self):
    session_id = uuid4()
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=session_id)
    expected = SimpleNamespace()
    with (
        patch("app.routers.synthesis.run_strategic_signals_cycle", new=AsyncMock(return_value=expected)) as signals,
        patch("app.routers.synthesis.run_session_synthesis", new=AsyncMock()) as briefing,
    ):
        result = await refresh_synthesis(session_id, mode="live", db=db)
    self.assertIs(expected, result)
    signals.assert_awaited_once_with(session_id)
    briefing.assert_not_awaited()

async def test_post_call_refresh_dispatches_to_briefing_trio(self):
    session_id = uuid4()
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=session_id)
    expected = SimpleNamespace()
    with (
        patch("app.routers.synthesis.run_strategic_signals_cycle", new=AsyncMock()) as signals,
        patch("app.routers.synthesis.run_session_synthesis", new=AsyncMock(return_value=expected)) as briefing,
    ):
        result = await refresh_synthesis(session_id, mode="post_call", db=db)
    self.assertIs(expected, result)
    briefing.assert_awaited_once_with(session_id, mode="post_call")
    signals.assert_not_awaited()
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m unittest tests.test_orchestrator_graceful_drain tests.test_synthesis_router`

Expected: FAIL because the live loop still calls `run_session_synthesis`.

- [ ] **Step 3: Replace the live briefing loop**

In `AgentOrchestrator`:

- replace `_briefing_task` with `_strategic_signals_task`;
- start it only when `_is_enabled("strategic_signals")`;
- use `_get_interval("strategic_signals", 45)`;
- call `run_strategic_signals_cycle` with model/prompt-containing agent configs
  and the current in-memory context;
- keep `_send_synthesis_update`;
- cancel the new task from shutdown and graceful drain;
- leave `briefing_enabled()` and the full drain's `run_session_synthesis`
  behavior unchanged.

In the REST route:

```python
synthesis = (
    await run_strategic_signals_cycle(session_id)
    if mode == "live"
    else await run_session_synthesis(session_id, mode="post_call")
)
```

Guard `run_session_synthesis` against `mode="live"` so no future caller can
silently reactivate the briefing trio during a call.

- [ ] **Step 4: Run trigger and drain tests and confirm GREEN**

Run: `python -m unittest tests.test_orchestrator_graceful_drain tests.test_synthesis_router tests.test_briefing_synthesis`

Expected: PASS, including full End Call and `skip_analysis` behavior.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/agents/orchestrator.py backend/app/routers/synthesis.py backend/tests/test_orchestrator_graceful_drain.py backend/tests/test_synthesis_router.py backend/app/services/briefing_synthesis.py
git commit -m "fix: keep briefing trio post-call only"
```

---

### Task 4: Expose Admin configuration and truthful public content

**Files:**
- Modify: `frontend/src/components/AdminPanel.tsx`
- Modify: `site/index.html`
- Modify: `docs-site/site.test.js`
- Modify: `docs/agents.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: seeded slug `strategic_signals`
- Preserves: existing `synthesis_updated` frontend payload and automatic vote effect

- [ ] **Step 1: Change the public contract test first**

Update the focused assertions to require:

```javascript
assert.match(section, /strategic_signals[\s\S]*Every 45s during the call/);
for (const slug of ['brief_meeting_lens', 'brief_discovery_lens', 'brief_arbiter']) {
  assert.match(section, new RegExp(`${slug}[\\\\s\\\\S]*At call end or on demand`));
}
```

Keep the seeded-slug equality assertion.

- [ ] **Step 2: Run the site test and confirm RED**

Run from `docs-site`: `node --test site.test.js`

Expected: FAIL because the seed and table triggers do not yet match the new
public contract.

- [ ] **Step 3: Update Admin and documentation**

In `AdminPanel.tsx`:

```typescript
const INTERVAL_DEFAULTS = {
  consolidated_analyst: 40,
  objection_handler: 10,
  synthesizer: 75,
  opportunity_specialist: 55,
  strategic_signals: 45,
};
```

Add `strategic_signals` to Live Analysis. Treat it as interval-driven for the
label and help text even though its internal type is `meta`; keep the briefing
trio without cadence controls.

In `site/index.html`, add the new agent row and change each briefing trigger to
`At call end or on demand`. Preserve the current table region semantics and
scoped header cells.

Update `docs/agents.md` and `AGENTS.md` with all nine agents and current
40/10/75/55/45 defaults. State explicitly that the briefing trio is post-call
or on-demand only.

- [ ] **Step 4: Run frontend and public-content checks**

Run:

```powershell
Set-Location frontend
npm run build
Set-Location ..\docs-site
node --test site.test.js
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/AdminPanel.tsx site/index.html docs-site/site.test.js docs/agents.md AGENTS.md
git commit -m "docs: publish current agent crew and triggers"
```

---

### Task 5: Verify the complete branch

**Files:**
- Modify only files required to fix failures caused by Tasks 1-4.

**Interfaces:**
- Produces: one frozen feature-branch SHA for the release integrator

- [ ] **Step 1: Run all backend tests**

Run from `backend`: `python -m unittest discover -s tests`

Expected: PASS except any already-documented Windows-only chmod failure must be
reported exactly and shown unrelated to this diff.

- [ ] **Step 2: Run frontend build**

Run from `frontend`: `npm run build`

Expected: PASS.

- [ ] **Step 3: Run required docs-site suites and build**

Run from `docs-site`:

```powershell
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
node --test *.test.js
npm run build
```

Expected: PASS.

- [ ] **Step 4: Run structural and diff gates**

Run:

```powershell
sentrux check .
sentrux gate .
git diff --check master...HEAD
git status --short --branch
```

Expected: no new structural findings, no whitespace errors, and only intended
files in the branch.

- [ ] **Step 5: Hand off the frozen SHA**

Send `claude-helper-6` the exact branch name, commit SHA, verification summary,
and reminder that it owns:

- merge/integration from a clean clone;
- version and release notes for `v0.3.3`;
- push to `master`;
- Windows, Linux, and macOS installer builds;
- manifest and download verification.

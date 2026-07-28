# ALP-157: model selection for the non-agent LLM call sites

Requested by: Talbert (operator), via the shepherd lane `w1:pP`
Performed by: Claude Opus 5, claude-1 Herdr lane (`w1:pR`), second machine
Date: 2026-07-27
Scope: analysis and design only. No code changes in this pass.

Anchored on the post-train semantics of ALP-152 (`privacy.admitted_model_ids`,
the three-argument `LocalOnlyModeError`) and ALP-154 (self-hosted request
limits), read from PR #27 rather than from the pre-train code in this checkout.
This checkout is at `3263b6e`, which does **not** yet contain that train.

---

## 1. Correction to the issue's premise, up front

The issue names four call sites. **Two of them are dead code.** Verified
repo-wide, not just in `backend/`:

- `services/insight_refiner.py:121` sits inside `run_refinement_cycle()`, which
  has **zero callers anywhere in the repository** - only its own definition
  matches. `synthesizer.py:3` says so in its own docstring: "Replaces the
  current insight_refiner.py refinement loop". What survives from that module is
  `_apply_operations` / `_apply_operations_in_db`, imported by `synthesizer.py`
  and `speaker_context_enhancer.py`. The function also carries a latent bug that
  proves nobody runs it: line 127 `return []` is followed by an unreachable
  `raw = raw.strip()` at line 129.
- `services/agents/base.py:98` sits in `TextAgent.run_cycle()`. No `TextAgent`
  subclass is ever instantiated. `orchestrator.py:25` imports only
  `TranscriptBuffer` from that module. The strings "observer",
  "opportunity_scout", and "action_tracker" survive only as `agent_source`
  labels (`consolidated_analyst.py:25`) and in `showcase/seed_demo.py`.

So ALP-129's real failure was **not** `insight_refiner`. "Enhance Insights"
routes `sessions.py:145` -> `speaker_revalidation.run_revalidation` ->
`_run_batch` (`speaker_revalidation.py:413`) -> `speaker_context_enhancer.py:162`.
The issue attributed the symptom to the wrong module. Only the call site changes;
the reported user-visible failure is real.

**Two live sites are actually broken**, and one additional site the issue
declared out of scope breaks acceptance 3. See section 3.

## 2. Authoritative inventory

### 2.1 Every `settings.REFINEMENT_MODEL` reference (10 total)

| # | Site | Verdict |
| --- | --- | --- |
| 1 | `services/agents/consolidated_analyst.py:119` | Correct. `model_override or settings.REFINEMENT_MODEL` |
| 2 | `services/agents/opportunity_specialist.py:146` | Correct. Same shape |
| 3 | `services/agents/synthesizer.py:109` | Correct. Same shape |
| 4 | `services/agents/orchestrator.py:234` | Correct. `_get_model("consolidated_analyst", settings.REFINEMENT_MODEL)` |
| 5 | `services/insight_refiner.py:121` | **Dead.** `run_refinement_cycle` has no callers |
| 6 | `services/agents/base.py:98` | **Dead.** `TextAgent` is never instantiated |
| 7 | `services/speaker_context_enhancer.py:162` | **Live and broken.** Speaker-context enhancement |
| 8 | `routers/analyze.py:90` | **Live and broken.** Post-import Analyze |
| 9 | `services/gemini_files.py:42` | Gemini Files API, genuinely pinned |
| 10 | `services/gemini_files.py:55` | Gemini Files API, genuinely pinned |

### 2.2 Adjacent hardcoded text-model references

| Site | What | Verdict |
| --- | --- | --- |
| `services/agents/objection_handler.py:23` | `DEFAULT_OBJECTION_MODEL = "gemini-3.1-flash-lite"` | Fallback literal rather than a settings constant. Cosmetic inconsistency only: the live value comes from the `objection_handler` agent row. Out of scope |
| `services/seed_agents.py:56-61, 97-191, 243` | Seed and forced-default model ids | Correct by design; seeds are the source of defaults |
| `routers/chat.py:57, 207` | `body.model_id` from the request | Already fully selectable, client-chosen, validated against the registry and endpoint models. Not affected |
| `services/local_fit.py:434, 442` | Function parameter | Correct |
| `services/batch_transcriber.py:112` | `model_id or settings.BATCH_TRANSCRIBER_MODEL`, overridden by app setting `transcription.batch.model_id` | Correct, and already Privacy First aware via `transcription_runtime.py:50` |

No other hardcoded text-model literal reaches an LLM call.

### 2.3 The gate already exists and is already correct

`llm.py:75-88` `_prepare_call()` is the single choke point for both
`generate_text` and `generate_json` (its only two callers, lines 134 and 312):

```python
if provider != "local" and await is_local_only() and not await allows_local_only(model_id):
    raise LocalOnlyModeError(f"{feature} with {model_id}")
```

This is **already judged by destination**, which is the ALP-152 rule. Nothing in
this issue needs a new Privacy First check. Acceptance 5 ("a cloud model is
still refused") holds today and keeps holding for free. The four sites do not
need a gate; they need a **model the user can choose**.

One gap remains: `_prepare_call` passes an interpolated string as `feature` and
leaves ALP-152's new `model_id` and `agent` arguments empty, so every refusal
raised from `llm.py` renders the generic "requires an outside API call" branch
instead of the actionable one that names what to change. See section 4.3.

## 3. The honesty gap (acceptance 3)

`privacy.py:83-175` `privacy_impact()` builds the disabled list **entirely
inside `if not local_text`** (line 148). Configure one on-prem text model and
five entries vanish at once. Two of those are lies today:

| Claim when an on-prem text model exists | Reality |
| --- | --- |
| "AI analysis agents" available | True after ALP-152 |
| "transcript analysis" available | **False.** `analyze.py:90` is pinned to Gemini |
| "meeting chat" available | True. `chat.py` takes the model from the request |
| "Insight enhancement" no longer disabled | **False.** `speaker_context_enhancer.py:162` is pinned to Gemini |
| "Document upload & summarization" no longer disabled | **False, and unfixable.** `gemini_files.py:17-18, 37-38` raises `LocalOnlyModeError` unconditionally, whatever models exist |

Sites 7 and 8 are fixed by this design. Document summarization is not: it uses
the Gemini Files API itself, not a swappable text model. Its disabled entry is
currently suppressed by exactly the condition that cannot help it, so it must
move **out** of the `if not local_text` block and become unconditional.

The sharpest illustration is inside one feature. A single Enhance Insights run
creates two batch kinds (`speaker_revalidation.py:352-358`): `insights` calls
`run_speaker_context_batch` (pinned, fails) and `briefing` calls
`run_session_synthesis` (agent-configured, fixed by ALP-152). Half of one
user-visible action already honors Privacy First and half does not.

## 4. Design

### 4.1 Chosen direction: reuse the existing agent row that already owns the work

Both live sites have a natural owner already configured in Admin -> Agents.
Take the **model** from that row. Do not take its `enabled` flag.

| Call site | Owning agent row | Why that row |
| --- | --- | --- |
| `speaker_context_enhancer.run_speaker_context_batch` | `synthesizer` ("Principal Agent") | Both reconcile and enrich already-saved insights, and both drive the same operation vocabulary through the same `_apply_operations_in_db` (answer / enrich / elevate / adjust / create / dismiss / merge) |
| `analyze.analyze_transcript` | `consolidated_analyst` | Both turn a transcript into the same four item types through the same lens set. Analyze is the post-import form of what the analyst does live |

Resolution order at each site: **agent row model -> `settings.REFINEMENT_MODEL`**,
matching the shape the already-correct sites use.

Sites 5 and 6 (`insight_refiner.run_refinement_cycle`, `agents/base.py`
`TextAgent` and its three subclasses) are **deleted**, not configured. They are
unreachable; giving unreachable code a model picker adds a config surface for
behavior that can never run. `TranscriptBuffer` stays in `base.py` - it is the
only live export.

**Borrow the model, not the enablement.** Both features are user-initiated
actions (a button in the post-call Speakers tab; the post-import Analyze
action), not interval agents. Reading the owning row's `enabled` flag would mean
that disabling the Principal Agent silently breaks the Enhance Insights button,
with no visible connection between the two. Only `model_id` is borrowed.

### 4.2 Why this is the right rung

- **No new configuration concept.** No table, no migration, no seed row, no
  Admin tab, no new admission plumbing. Both rows already render a model
  `<select>` at `AdminPanel.tsx:421` through `lib/modelOptions.ts`, which already
  owns the Privacy First lock rule. Acceptance 2 is satisfied by surfaces that
  already exist.
- **Admission is inherited, not rebuilt.** `llm.py:82` already judges by
  destination. A self-hosted model on either row admits the feature; a cloud one
  refuses it. Acceptance 1 and 5 both fall out.
- **ALP-156 gets these for free.** Its planner reasons over declared agent
  models. Once these two features draw from `synthesizer` and
  `consolidated_analyst`, their cost is already in the aggregate budget rather
  than being an invisible extra load.
- **Discoverability rides an existing channel.** `AgentConfig.description` is
  seed-owned and auto-synced on every startup (`seed_agents.py:213-215`), and
  the Admin card already renders it (`AdminPanel.tsx:384`). Extending the two
  descriptions to say the row's model also drives Enhance Insights / Analyze is
  a two-string change that reaches every existing install with no migration.

### 4.3 Make the refusal message name the fix, everywhere at once

ALP-152 gave `LocalOnlyModeError` a `model_id` and `agent` argument, but
`llm.py:83` still passes neither, so every refusal raised through `generate_text`
and `generate_json` renders the weaker message. Both callers already have
`source` in scope (`source="speaker_context_enhancer"`, `source="analyze"`,
`source="insight_refiner"`, and so on), and it is already threaded through to
`record_token_usage`.

Thread `model_id` and `source` into `_prepare_call` and construct the error with
all three arguments. This is a three-line change at the single choke point that
upgrades the message for **every** call site in the application, not just the two
this issue touches. Fixing it in the shared function is a smaller diff than
fixing it per feature, and it is the only version that catches the sites nobody
has filed an issue about yet.

### 4.4 Reading the model

Mirror the existing `agent_config_enabled` helper that already lives beside
`load_agent_configs` in `briefing_synthesis.py:91`:

```python
async def agent_model_id(slug: str, default: str, session_id=None) -> str:
    cfg = (await load_agent_configs(session_id)).get(slug)
    return (cfg.model_id if cfg else "") or default
```

Two callers justify it; a third would not have. `speaker_context_enhancer`
already opens its own `async_session` at line 131 and can resolve the model in
that same block. `analyze.py` holds a request-scoped `db`; the extra read is one
indexed lookup on a nine-row table, per user-initiated action.

This does re-read the config once per revalidation batch rather than once per
run. That is acceptable at this size and worth a `ponytail:` comment naming the
ceiling: hoist the lookup into `speaker_revalidation._run_batch`'s caller if a
run ever grows enough batches for it to matter.

### 4.5 Failure message when no admitted model exists

No new message is needed. With Privacy First on and a cloud model on the owning
row, `llm.py:82` refuses and - once 4.3 lands - the user sees ALP-152's wording
naming the agent and the model:

> Privacy First mode is on: text generation is unavailable, and 'synthesizer' is
> set to gemini-3.1-pro-preview, which sends data off this machine and its
> network. Assign a self-hosted model in Admin -> Agents (any endpoint on this
> machine or your LAN qualifies), or turn off Privacy First mode in
> Admin -> Transcription & Audio.

`main.py:296` already has the `LocalOnlyModeError` exception handler, so the
message reaches the HTTP surface for both features unchanged.

`admitted_model_ids` is **not** needed here. It exists to batch-resolve many
agents' models before a synchronous gate; these two sites resolve exactly one
model each on an async path, where `allows_local_only` via `_prepare_call` is
already the right call.

### 4.6 Fix `privacy_impact`

- Move the "Document upload & summarization" entry out of the `if not
  local_text` block so it is listed as disabled whenever Privacy First is on.
  It is the one feature with no local path.
- Leave "transcript analysis" and "Insight enhancement" as they are. Once 4.1
  lands, the existing claims become true instead of aspirational.
- `docs/configuration.md:135` describes `REFINEMENT_MODEL` as "Model for
  refinement passes". Reword to "Fallback text model when an agent row has no
  model set", which is what it actually becomes.

## 5. The one deviation from acceptance 4

Acceptance 4 asks that an install configuring nothing behave "exactly as it does
today". This design does not quite do that, and the difference should be an
operator decision rather than a silent one.

Today both sites run `gemini-3.5-flash`. After the change, a seeded install runs
the owning row's model: `gemini-3.6-flash` for Analyze
(`consolidated_analyst`) and **`gemini-3.1-pro-preview`** for Enhance Insights
(`synthesizer`, `seed_agents.py:133` - note it is absent from
`FORCED_DEFAULT_MODELS`, so it stays on pro). Only a bare install with no
`agent_configs` rows falls through to `settings.REFINEMENT_MODEL`.

The Analyze shift is immaterial, flash to flash. The Enhance Insights shift is
not: it moves a pass that sends the **full** transcript plus the insight set,
once per batch, from a flash model to a pro model. That is a real cost increase
for anyone who never opens Admin.

Two options, operator's call:

- **A (recommended).** Accept the shift. It is the honest consequence of "the
  synthesizer owns this work", the model is now visible and one dropdown away,
  and pro output on a full-transcript reconciliation pass is where the quality
  difference actually shows. Call it out in the release notes.
- **B.** Pin the fallback: resolve `synthesizer.model_id` only when the operator
  has changed it from the seeded value, otherwise keep `settings.REFINEMENT_MODEL`.
  Preserves acceptance 4 literally, at the cost of a rule that is hard to explain
  in the UI ("this picker applies to Enhance Insights, but only if you touch it").

Recommend A. B trades a visible cost change for an invisible coupling rule,
which is the same class of surprise this issue exists to remove.

## 6. Rejected alternatives

- **A new "roles" concept** (named refinement roles with their own configured
  model, surfaced in Admin). New table or settings keys, new API, new UI, new
  seed data, new admission wiring, plus a second model-configuration concept
  users must reconcile against Agents. All of it for two call sites that already
  have obvious owners. Rejected as machinery that earns nothing the agent rows
  do not already provide.
- **One workspace-level "refinement model" app setting** in Connections. Cheaper
  than roles, but it is a third place model choices live (registry defaults,
  agent rows, and now this), and it would collapse two features with genuinely
  different cost profiles onto one value. It also gives ALP-156 a model with no
  owning agent to attribute load to.
- **A quota/refusal fallback as the whole answer** (ALP-129's approach: catch
  the refusal, retry on an admitted self-hosted model). Worth landing on its own
  merits as runtime resilience, and orthogonal to this. As the answer to ALP-157
  it fails acceptance 2 and 3: the model stays invisible, unselectable, and
  unplannable, and the Admin panel keeps promising behavior the config cannot
  express.
- **Per-site `is_local_only()` gates** in the style of `strategic_signals.py:36`.
  Duplicates a check `llm.py:82` already performs centrally, and each copy is
  another place for the destination rule to drift. The agent sites need their own
  gate because they must decide whether to *schedule* an agent; these two sites
  are called on demand and can let the call raise.
- **Keeping sites 5 and 6 and giving them `model_override` parameters.** Adds a
  configuration surface to code with no callers.

## 7. Implementation checklist

1. `llm.py` - thread `model_id` and `source` into `_prepare_call`; raise
   `LocalOnlyModeError(feature, model_id, source)`.
2. `briefing_synthesis.py` - add `agent_model_id(slug, default, session_id=None)`
   beside `agent_config_enabled`.
3. `speaker_context_enhancer.py:161-166` - resolve from the `synthesizer` row.
4. `routers/analyze.py:89-91` - resolve from the `consolidated_analyst` row.
5. Delete `insight_refiner.run_refinement_cycle` (and its now-unused
   `REFINEMENT_PROMPT_TEMPLATE`, `_build_insights_json`, and `generate_text` /
   `settings` imports if nothing else in the module uses them).
6. Delete `TextAgent`, `ObserverAgent`, `OpportunityScoutAgent`,
   `ActionTrackerAgent` from `agents/base.py`. Keep `TranscriptBuffer`. Check
   whether `agents/prompts.py` `OBSERVER_PROMPT`, `OPPORTUNITY_SCOUT_PROMPT`,
   and `ACTION_TRACKER_PROMPT` become unused and drop them too.
7. `privacy.py` - move the document-summarization entry to unconditional
   disabled.
8. `seed_agents.py` - extend the `synthesizer` and `consolidated_analyst`
   descriptions to name the feature each row's model now also drives.
9. `docs/configuration.md:135` and `docs/agents.md` - reword `REFINEMENT_MODEL`
   and note the two borrowed models.
10. Run `sentrux check .` - deleting two dead classes and a dead function should
    move the complex-function count down, so refresh the baseline with
    `sentrux gate --save .` if it shifts.

## 8. Tests

Backend tests are stdlib `unittest` in `backend/tests/`; run with
`python -m unittest discover -s tests` from `backend/`.

1. `test_speaker_context_enhancer.py` - extend the existing suite: with a
   `synthesizer` row set to an endpoint model, assert `generate_text` is called
   with that id, not `settings.REFINEMENT_MODEL`; with no row present, assert it
   falls back to `settings.REFINEMENT_MODEL`.
2. New test for `analyze` - same two cases against the `consolidated_analyst`
   row.
3. Privacy admission - with Privacy First on and an on-prem endpoint model on
   both rows, assert neither site raises; with a Gemini model on the rows, assert
   `LocalOnlyModeError` is raised and its message names the agent and the model
   (covers acceptance 5 and section 4.3 together).
4. `privacy_impact` - assert "Document upload & summarization" appears in the
   disabled list even when `on_prem_text_models` is non-empty.
5. Import guard - assert `agents/base.py` still exports `TranscriptBuffer` after
   the deletion, so `orchestrator.py:25` and `test_speaker_attribution.py:4`
   keep working.

## 9. Acceptance mapping

| # | Acceptance | Met by |
| --- | --- | --- |
| 1 | Privacy First + self-hosted model: revalidation, speaker-context enhancement, and Analyze all run | 4.1. Note "insight revalidation" resolves to the Enhance Insights run's two batch kinds: `briefing` was fixed by ALP-152, `insights` is fixed here. `insight_refiner` is dead and runs nothing |
| 2 | The model each uses is visible and selectable | 4.1 plus the existing Admin -> Agents pickers; disclosed through the seed-owned descriptions (4.2) |
| 3 | The Admin panel's claim matches the runtime | 4.6, together with 4.1 making the two remaining claims true |
| 4 | An install that configures nothing behaves as today | Partially. See section 5 - one deliberate deviation, operator's call |
| 5 | A cloud model is still refused, with ALP-152's message | Already true via `llm.py:82`; the message is upgraded by 4.3 |

## 10. Sequencing

Independent of ALP-129 and ALP-156, but ordered against them:

- Land **after** the ALP-152 train is in `master`. Section 4.3 edits the
  three-argument `LocalOnlyModeError` the train introduces, and section 4.6
  edits `privacy_impact` in the same file the train touches.
- Land **before** ALP-156's planner ships, or it will plan a budget with two
  unattributed text loads.
- ALP-129's fallback is orthogonal and can land in either order. If it lands
  first, its fallback at `insight_refiner.py` should be re-pointed at
  `speaker_context_enhancer` - the module it patches is not the one ALP-129's
  reporter actually hit (section 1).

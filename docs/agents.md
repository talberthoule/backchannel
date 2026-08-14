# Agent System

Analysis is performed by a small crew of agents coordinated by
`AgentOrchestrator` (`backend/app/services/agents/orchestrator.py`). One
orchestrator instance is created per live call inside the WebSocket handler.
Text agents never see raw audio: they read recent transcript text from a
shared in-memory buffer that the orchestrator maintains as final transcript
entries are saved.

## The agents

Every agent below is configurable from Admin -> Agents: its model, its system
prompt, its trigger, and whether it runs at all.

On a fresh install every agent model starts as **Not selected**. Backchannel
does not silently assign a cloud provider or rewrite selections when a key or
self-hosted endpoint is added. The initial batch transcription model is the
built-in `local-whisper-base`, which needs no API key. Choose explicit models
for enabled agents before starting a call; **Recommended** marks a sensible
provider-specific starting point, not a forced choice.

<picture>
  <source srcset="/assets/shots/admin-agents-dark.webp" media="(prefers-color-scheme: dark)" />
  <img src="/assets/shots/admin-agents.webp" width="1185" height="900" alt="Admin Agents tab: the Privacy First toggle above the agent lineup, each agent showing its type, slug, model selector, and system prompt control." />
</picture>

| Agent slug | Type | Trigger | Code | Purpose |
| --- | --- | --- | --- | --- |
| `audio_gateway` | audio | Continuous audio stream | `backend/app/services/gemini_live.py` / `backend/app/services/openai_realtime.py` / `backend/app/services/local_live_captioner.py` | Silent live listener that produces interim transcription: a cloud streaming session (Gemini Live or OpenAI Realtime) or the on-device local captioner (`local-parakeet-live`), chosen by the agent's configured model |
| `consolidated_analyst` | text | Interval, default 40s, plus a final pass | `backend/app/services/agents/consolidated_analyst.py` | Single LLM call that can produce questions, observations, opportunities, and action items in one pass |
| `objection_handler` | text | Interval, default 10s, over only the last 90s of transcript | `backend/app/services/agents/objection_handler.py` | Low-latency objection scan; each `objection` insight pairs an immediate suggested response with the underlying concern and strategic angle |
| `synthesizer` | meta | `new_insight` / `insight_updated` events, 75s cooldown, 120s fallback | `backend/app/services/agents/synthesizer.py` | Reconciles and enriches saved insights, detects answered questions, may elevate an item's type |
| `opportunity_specialist` | db | `new_opportunity` events, 55s cooldown, plus final matching | `backend/app/services/agents/opportunity_specialist.py` | Matches opportunity insights against configured knowledge sources |
| `strategic_signals` | meta | Interval, default 45s during the call | `backend/app/services/agents/strategic_signals.py` | Produces the live Signal, Risk, Next Question, Opportunity, and Action Cue cards in one call; evidence-linked insights are automatically upvoted |
| `brief_meeting_lens` | meta | Full End Call or on demand | `backend/app/services/briefing_synthesis.py` | Drafts the factual meeting record |
| `brief_discovery_lens` | meta | Full End Call or on demand | `backend/app/services/briefing_synthesis.py` | Drafts the broader discovery and sensemaking view |
| `brief_arbiter` | meta | After the post-call lens drafts | `backend/app/services/briefing_synthesis.py` | Reconciles the two drafts into the settled briefing |

Default live-analysis intervals come from the seeded `agent_configs` rows,
with runtime fallbacks in `backend/app/config.py`
(`TEXT_AGENT_INTERVAL_SECONDS`, `OBJECTION_HANDLER_INTERVAL_SECONDS`,
`OBJECTION_WINDOW_SECONDS`, `SYNTHESIZER_COOLDOWN_SECONDS`,
`SYNTHESIZER_MAX_INTERVAL_SECONDS`,
`OPPORTUNITY_SPECIALIST_COOLDOWN_SECONDS`) but the per-agent values stored in
the database take precedence.

Cloud recommendations are grouped by role:

| Role | Google | OpenAI |
| --- | --- | --- |
| Audio gateway | `gemini-3.1-flash-live-preview` | `gpt-live-transcribe` |
| Consolidated Analyst, Principal Agent, Strategic Signals, meeting/discovery briefing lenses, Live Ask | `gemini-3.7-flash` | `gpt-5.6-terra` |
| Objection Handler | `gemini-3.5-flash-lite` | `gpt-5.6-luna` |
| Opportunity Specialist | `gemini-3.7-flash` | `gpt-5.6-luna` |
| Briefing Arbiter | `gemini-3.7-flash` | `gpt-5.6-sol` (high effort) |
| Batch transcription | `gemini-3.5-flash-lite` | `gpt-4o-mini-transcribe` |

`gpt-5.6-sol` high effort is reserved for the Briefing Arbiter. Self-hosted
recommendations come from the current Local Fit result instead of a static
model name.

The three briefing agents never run on the live interval. Normal **End Call**
runs them; **End without briefing** skips them; **Generate Briefing** runs them
on demand. Live Strategic Signals is separately enabled and configured.

Each Strategic Signals cycle replaces the five live cards, but the signals
themselves are kept. Every cycle folds its items into `signal_history` on the
`live` synthesis row, matched on section plus a normalized title, so a repeat
raises `count` and moves `last_seen` instead of appending a near-duplicate.
A theme that recurred is therefore visibly distinct from a one-off, and the
briefing context built from the history carries each observation once rather
than several times in different words. The History control renders the kept
signals during the call and again in the post-call briefing. The list is
capped at the newest `SIGNAL_HISTORY_MAX_ENTRIES` (200) entries.

The settled briefing leads with an at-a-glance summary strip (outcome, action,
risk, and open-question counts plus synthesis status) and a Top Outcomes hero,
followed by per-section cards that each carry their own icon and accent color.
Items show owner and status chips, with the supporting "Why this matters"
rationale collapsed behind a toggle, and strategic signals captured during the
call are folded into the briefing as their own section
(`backend/app/services/briefing_synthesis.py`, rendered by
`frontend/src/components/PostCall/BriefingView.tsx`).

There is no standalone question-hunter agent: question generation is one
enabled lens of `consolidated_analyst`. The `question_hunter` label only
survives as a backward-compatible `agent_source` value on exported/saved
question items.

## Asking during a call

The call's command bar opens in Chat mode. A question goes to
`POST /api/sessions/{id}/ask`, which answers from the session's current
transcript, live insights, strategic signals, directives, and attached document
filenames. The answer is saved as an `asked` insight, starred automatically so
it pins to the top of the live feed and stays findable afterwards, and it is
exported with every other insight.

This is not an agent: nothing schedules it, and asking never steers the running
agents. The card's `Make directive` action is the explicit way to turn a
question into agent guidance.

The answering model is chosen from the chip in the bar. A valid saved choice
is preserved; otherwise it stays **Not selected**. Asking without a selection
keeps the draft and points the user to the model chip.

## Configuration and overrides

Agent behavior is driven by database rows, not code constants:

- **`agent_configs`** -- one row per agent slug with `enabled`, `model_id`,
  `interval_seconds`, and the prompt. Seeded on startup by
  `backend/app/services/seed_agents.py` and editable in the Admin panel
  (`GET/PATCH /api/agents/{slug}`, `POST /api/agents/reset/{slug}` to restore
  the seeded prompt).
- **`session_agent_overrides`** -- optional per-session enable/disable rows
  (`GET/PUT /api/sessions/{id}/agents`), set from the pre-call view. A
  session override trumps the global flag for that call.

The WebSocket handler loads both tables when a call starts and hands the
merged result to the orchestrator, so mid-call edits to global config apply
to the next call, not the current one.

Model choice is per agent: each agent row references a model from the
registry in `backend/app/config.py`, and text calls are routed to the right
provider (Google, OpenAI, or a self-hosted OpenAI-compatible endpoint) by
`backend/app/services/llm.py`. An enabled row with a blank model is blocked as
`no_model`; runtime provider fallbacks do not override that explicit state.

**On-device live captions (experimental, ALP-147).** Setting the `audio_gateway`
model to `local-parakeet-live` routes interim captions to
`local_live_captioner.py` instead of a cloud gateway: it batches mic audio into
short, non-overlapping ~3 s chunks and transcribes each with local Parakeet
ONNX, so captions work with no cloud call (and under Privacy First). Latency is
about one chunk (~3 s), not the cloud gateways' sub-second partials, and it is
CPU-heavy - it shares the machine with diarization and batch transcription - so
run the fit test's live-caption feasibility first. The `supports_live_audio`
routing for the cloud gateways is unchanged.

Setting the
`audio_gateway` agent to an OpenAI realtime transcription model
(`gpt-live-transcribe`, `gpt-4o-transcribe`, or `gpt-4o-mini-transcribe`)
switches the interim gateway from Gemini Live to the OpenAI Realtime API.

`backend/app/config.py` still contains legacy toggles such as
`AGENT_QUESTION_HUNTER_ENABLED` and `AGENT_CONSOLIDATED_ENABLED`; the
orchestrator primarily uses the database rows and only falls back to some
subtype flags.

## Local Model Fit Test

Running analysis on a self-hosted model (an on-prem OpenAI-compatible endpoint)
only works if that model finishes each cycle before the next one is due. The
**Local Model Fit Test** (Admin -> Transcription & Audio, backed by
`backend/app/services/local_fit.py`) measures that keep-up speed -- not answer
quality.

For every on-prem, text-capable endpoint model it times one short-window and
one long-window `generate_text` call after a warmup. Each timed call carries a
representative agent's **real system prompt** (the `objection_handler` prompt
for the short window, the multi-lens `consolidated_analyst` prompt for the long
window, pulled live from `AgentConfig` with runtime placeholders filled) plus a
realistically sized transcript, so the measurement reflects production prefill
rather than a toy prompt. It then scores each interval-driven agent against its
cycle budget (`AgentConfig.interval_seconds`, or the seeded default):

- **Keeps up (green)** -- the call finishes within half the budget.
- **Tight (yellow)** -- it finishes within the budget but with little headroom.
- **Too slow (red)** -- the call is slower than the budget; the agent would fall
  behind.

The short-window roles are `objection_handler` and `opportunity_specialist`;
the long-window roles are `consolidated_analyst`, `strategic_signals`, and
`synthesizer`. The three **post-call briefing agents** (`brief_meeting_lens`,
`brief_discovery_lens`, `brief_arbiter`) are also scored, but they run once at
call end -- no live loop -- so they are judged on an acceptable end-of-call wait
(green <= 60 s, yellow <= 180 s) rather than a cycle budget, and are not editable.
The audio gateway is not a text model, so it gets no cycle-budget score here;
its on-device option (`local-parakeet-live`) is judged instead by the ASR
section's live-caption feasibility projection described below.

A local model is marked Recommended for a role only when the current endpoint
and machine fit result is complete, current, and green for both the whole call
and that role. When several pass, the lowest contention-adjusted latency wins
(then model id for a stable tie-break). Selecting that recommendation is still
an explicit user action; for live interval roles it also applies the fit
result's recommended interval through the existing Local Fit apply route.

**Per-model budgets.** A cycle budget is stored per agent *and per model* in
`AgentConfig.model_intervals` (JSON `{model_id: seconds}`), so the analyst can
run tighter on a fast model and looser on a slow one. The orchestrator's
`_get_interval` resolves the per-model budget for the agent's assigned model
first, then the global `interval_seconds`, then the seeded default. On the fit
screen each budget is editable inline and "Apply recommended budgets" writes the
per-model value via `POST /api/diagnostics/local-fit/apply` (`{model_id, updates}`).

**Contention headroom.** A real call is busier than the idle benchmark
(recording, diarization, other apps), so an **assumed-load slider** (1x-3x,
default 1.5x) scales measured latency before judging: effective latency =
measured x contention. Verdicts and recommended budgets recompute live as the
slider moves (recommended budget is about twice the *effective* latency).

The same card also measures **transcription keep-up** for the bundled local ONNX
ASR models (`local-whisper-base`, `local-parakeet-tdt-0.6b`). "Run fit test"
times them automatically on a synthetic speech-band clip (an estimate); upload or
record real speech via `POST /api/diagnostics/local-fit/asr` for a precise
number. It reports a real-time factor (processing / audio, green below half real
time) plus an **experimental live-caption feasibility** projection (short-window
RTF, very conservative) for the on-device captioner (`local-parakeet-live`,
ALP-147) described above -- check it before pointing the audio gateway at
Parakeet Live.

To answer "where can this model actually go?", the card shows, per model, the
services it can fill (a **Usable for** list) and a **What can run locally** map
of each AI service to its local option. Both are derived from the registry
capability flags (`supports_batch_audio`, `supports_text`, `supports_live_audio`)
by `build_local_capabilities`, so they never drift from how calls route: the
bundled ONNX ASR models fill batch transcription, a self-hosted chat endpoint
drives the analysis agents and meeting chat, and live interim captions list the
on-device `local-parakeet-live` captioner as their local option, which is how
captions keep running under Privacy First (the cloud streaming gateways remain
the default). Document upload and summarization is the one AI service with no
local option at all, because it calls the Gemini Files API rather than choosing
a text model; configuring a self-hosted endpoint does not enable it. The card
also auto-retries its summary fetch so it recovers on its own if the backend
was still starting or an endpoint was connected after the page loaded.

**Call-start capacity admission.** The fit test measures each component alone;
`backend/app/services/capacity_admission.py` (served at
`GET /api/diagnostics/capacity`) checks whether the configured combination fits
together. At call start it sums the measured demand of Sortformer diarization,
local batch transcription, the local live captioner, and every enabled agent on
a self-hosted model against the machine's usable CPU cores and memory limit.
Only persisted measurements count: any configured local component without one
is named under `not_modelled`, so partial coverage can never read as a complete
clean pass, and aged measurements annotate the verdict rather than blocking it.

Two features have no agent row of their own and borrow one instead. Post-import
Analyze runs the model set on **Consolidated Analyst**, and Enhance Insights
(the speaker-context pass after a speaker correction) runs the model set on
**Principal Agent**. Only the model is borrowed, never the enabled toggle: both
are buttons the user presses, so disabling either agent does not turn them off.
That also means Privacy First judges them by destination like any other agent
model. If the borrowed row is **Not selected**, the action reports that setup
is required instead of falling back to a configured environment default.

## Runtime activity and call health

When nothing is happening, the app says why. Each orchestrator keeps an
in-memory `ActivityRegistry` (`backend/app/services/agents/activity.py`) that
pushes `agent_activity` snapshots over the session WebSocket, coalesced to at
most one every ~2 seconds; errors, newly blocked agents, and degradation
changes emit immediately. A snapshot carries:

- **Per-agent status** -- the state (`waiting`, `running`, `failing`, or
  `blocked` with a reason and remedy), when the last run started and how long
  it took, when the next run is due, the last outcome (insights saved, all
  items deduplicated as near-repeats, or nothing found), the last error
  (classified as truncated, timeout, refusal, or API error, each with a
  suggested remedy), and cumulative counts of runs, insights, deduplicated
  items, and errors.
- **Setup visibility** -- enabled agents with no model report
  `blocked_reason=no_model`; the collapsed panel counts them as
  **N need setup**, and the expanded row points to Admin -> Agents.
- **Call health** -- the interim gateway state, transcription job and failure
  counts, the diarization queue depth and shed-frame count, and a `degraded`
  flag with plain-language `degraded_reasons` (failed transcription segments,
  shed diarization audio, or a reconnecting gateway).

The live agent activity panel
(`frontend/src/components/ActiveCall/AgentActivityPanel.tsx`) renders these
snapshots during the call.

## Insight lifecycle

1. A text agent proposes an item (question, observation, opportunity,
   objection, or action item) with a type and content.
2. The orchestrator deduplicates it against recent items using simple
   word-overlap similarity within a 300-second sliding window
   (`orchestrator.py`). Restatements cluster around a minute apart, so a
   shorter window let near-duplicates through and left the synthesizer to
   merge them afterwards at full corpus cost.
3. Surviving items are saved to the `questions` table (all item types share
   that table) and pushed to the browser as a `question` message.
3a. The synthesizer sees the session's insights ordered by creation, but not
   all in full. A **live** insight (starred, or unanswered and touched within
   `SYNTHESIZER_WORKING_SET_SECONDS`, default 600) carries its full record; a
   **settled** one collapses to a stub of id, type, shortened text, and
   `"settled": true`, which merge and answer can still target. Sending every
   insight in full made this agent 48 percent of a measured meeting's token
   bill and grew quadratically with call length. A cycle whose insights and
   transcript are byte-identical to the previous one skips the model call.
4. `new_insight` / `new_opportunity` events fan out to the meta agents: the
   synthesizer may update, answer, or elevate items (emitting
   `insight_updated`, `question_answered`, `insight_elevated`), and the
   opportunity specialist attaches offering matches to opportunities.
5. When the call stops, the orchestrator performs a graceful drain so
   in-flight agent work completes before the session is finalized.

## Context provided to agents

Beyond transcript text, the orchestrator passes agents the session's active
directives (including mid-call directives sent over the WebSocket), document
summaries produced at upload time, the speaker roster with roles and
team/external tags, the meeting type and meeting context, and currently
unanswered questions so agents can track what is already open. That open-question
list is capped at the 24 most recent and is pruned when a question is answered,
dismissed, or merged away -- it used to prune only on answer, so it grew for the
whole call and was billed to two agents on every cycle.

Each interval agent also skips its cycle outright when the transcript window is
byte-identical to the one it last read, so a quiet stretch of a meeting costs
nothing. The objection handler has always done this; the consolidated analyst
and strategic signals now do too.

Meeting type and context edits made during a live call (`PATCH
/api/sessions/{id}`) are pushed into the running agents immediately: the
route looks up the session's live orchestrator in an in-process registry
and rebuilds the meeting-context prompt block for the consolidated analyst
and objection handler, taking effect on their next cycle. A type change
that turns on offering matching (client/sales or customer delivery) also
wires the opportunity specialist mid-call. The registry is per-process, so
this requires the single-worker deployment the app uses today.

Offering matching also gates the analyst's opportunity lens. On a meeting
type where matching is off, that lens is dropped from the prompt rather than
filtered from the output, so it costs no tokens and produces no cards. A
measured internal check-in had been spending 29 percent of its insights on
opportunities that could never be enriched, because the specialist that
enriches them is disabled for that meeting type. Switching the type mid-call
recomposes the lens set on the analyst's next cycle.

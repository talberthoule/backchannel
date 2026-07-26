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

<picture>
  <source srcset="/assets/shots/admin-agents-dark.webp" media="(prefers-color-scheme: dark)" />
  <img src="/assets/shots/admin-agents.webp" width="1185" height="900" alt="Admin Agents tab: the Privacy First toggle above the agent lineup, each agent showing its type, slug, model selector, and system prompt control." />
</picture>

| Agent slug | Type | Trigger | Code | Purpose |
| --- | --- | --- | --- | --- |
| `audio_gateway` | audio | Continuous audio stream | `backend/app/services/gemini_live.py` / `backend/app/services/openai_realtime.py` | Silent live listener (Gemini Live or OpenAI Realtime, chosen by the agent's configured model) that produces interim transcription |
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

The three briefing agents never run on the live interval. Normal **End Call**
runs them; **End without briefing** skips them; **Generate Briefing** runs them
on demand. Live Strategic Signals is separately enabled and configured.

There is no standalone question-hunter agent: question generation is one
enabled lens of `consolidated_analyst`. The `question_hunter` label only
survives as a backward-compatible `agent_source` value on exported/saved
question items.

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
provider (Google or OpenAI) by `backend/app/services/llm.py`. Setting the
`audio_gateway` agent to an OpenAI realtime transcription model
(`gpt-realtime-whisper`, `gpt-4o-transcribe`, or `gpt-4o-mini-transcribe`)
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

For every on-prem, text-capable endpoint model it times one short-window
(~90 s of transcript) and one long-window (~300 s) `generate_text` call after a
warmup, then scores each interval-driven agent against its cycle budget
(`AgentConfig.interval_seconds`, or the seeded default):

- **Keeps up (green)** -- the call finishes within half the budget.
- **Tight (yellow)** -- it finishes within the budget but with little headroom.
- **Too slow (red)** -- the call is slower than the budget; the agent would fall
  behind.

The short-window roles are `objection_handler` and `opportunity_specialist`;
the long-window roles are `consolidated_analyst`, `strategic_signals`, and
`synthesizer`. Briefing lenses and the audio bridge are not scored (they have no
live cycle budget). When a model is tight or too slow, the test recommends a
longer interval (about twice the call latency, rounded to 5 s, clamped to
5-180 s) and offers one-click apply, which writes `interval_seconds` on the
matching agents via `POST /api/diagnostics/local-fit/apply`. Because
`interval_seconds` is global per agent, apply the intervals for the one model
you intend those agents to run on.

The same card also measures **transcription keep-up**: upload or record a short
speech clip and it times each bundled local ONNX ASR model
(`local-whisper-base`, `local-parakeet-tdt-0.6b`) via
`POST /api/diagnostics/local-fit/asr`, reporting a real-time factor
(processing / audio) with green below half real time, yellow up to real time,
and red slower than real time. Unlike the text test this needs a real clip
because `LocalTranscriber` gates on an energy floor and a speech check.

## Insight lifecycle

1. A text agent proposes an item (question, observation, opportunity,
   objection, or action item) with a type and content.
2. The orchestrator deduplicates it against recent items using simple
   word-overlap similarity within a 60-second sliding window
   (`orchestrator.py`).
3. Surviving items are saved to the `questions` table (all item types share
   that table) and pushed to the browser as a `question` message.
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
unanswered questions so agents can track what is already open.

Meeting type and context edits made during a live call (`PATCH
/api/sessions/{id}`) are pushed into the running agents immediately: the
route looks up the session's live orchestrator in an in-process registry
and rebuilds the meeting-context prompt block for the consolidated analyst
and objection handler, taking effect on their next cycle. A type change
that turns on offering matching (client/sales or customer delivery) also
wires the opportunity specialist mid-call. The registry is per-process, so
this requires the single-worker deployment the app uses today.

# Agent System

Analysis is performed by a small crew of agents coordinated by
`AgentOrchestrator` (`backend/app/services/agents/orchestrator.py`). One
orchestrator instance is created per live call inside the WebSocket handler.
Text agents never see raw audio: they read recent transcript text from a
shared in-memory buffer that the orchestrator maintains as final transcript
entries are saved.

## The agents

| Agent slug | Type | Trigger | Code | Purpose |
| --- | --- | --- | --- | --- |
| `audio_gateway` | audio | Continuous audio stream | `backend/app/services/gemini_live.py` / `backend/app/services/openai_realtime.py` | Silent live listener (Gemini Live or OpenAI Realtime, chosen by the agent's configured model) that produces interim transcription |
| `consolidated_analyst` | text | Interval, default 15s | `backend/app/services/agents/consolidated_analyst.py` | Single LLM call that can produce questions, observations, opportunities, and action items in one pass |
| `objection_handler` | text | Interval, default 5s, over only the last ~90s of transcript | `backend/app/services/agents/objection_handler.py` | Low-latency objection scan; each `objection` insight pairs an immediate suggested response (micro) with the underlying concern and strategic angle (macro). Skips the LLM call when the window is unchanged |
| `synthesizer` | meta | `new_insight` / `insight_updated` events, 30s cooldown, 120s max interval | `backend/app/services/agents/synthesizer.py` | Reconciles and enriches saved insights, detects answered questions, may elevate an item's type |
| `opportunity_specialist` | db | `new_opportunity` events, 5s batch window | `backend/app/services/agents/opportunity_specialist.py` | Matches opportunity insights against the offerings catalog via pluggable knowledge sources |

Default intervals come from `backend/app/config.py`
(`TEXT_AGENT_INTERVAL_SECONDS`, `OBJECTION_HANDLER_INTERVAL_SECONDS`,
`OBJECTION_WINDOW_SECONDS`, `SYNTHESIZER_COOLDOWN_SECONDS`,
`SYNTHESIZER_MAX_INTERVAL_SECONDS`,
`OPPORTUNITY_SPECIALIST_COOLDOWN_SECONDS`) but the per-agent values stored in
the database take precedence.

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

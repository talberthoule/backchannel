# Standalone Live Strategic Signals Design

## Goal

Keep the existing Live Strategic Signals cards and automatic insight upvotes,
but stop the three Post-Call Briefing agents from running during calls. Live
signals become one independently configurable agent; the briefing trio runs
only at normal call end or through an explicit on-demand briefing request.

## Agent boundaries

Add one seeded `AgentConfig` row:

- Slug: `strategic_signals`
- Name: `Strategic Signals`
- Type: `meta`
- Default model: `gemini-3.6-flash`
- Default interval: 45 seconds
- Default state: enabled
- Configurable fields: enabled, model, prompt, and interval

The agent performs one structured model call over the current transcript,
saved insights, meeting context, directives, documents, speakers, and open
questions. It returns the existing live-synthesis shape used by
`SynthesisSignals`: Signal, Risk, Next Question, Opportunity, and Action Cue
cards with evidence references to existing insight IDs.

It does not create durable insights. Existing frontend behavior resolves the
evidence references, marks those insights as strategic signals, and persists
an automatic upvote. The live payload remains stored as the session's
`SessionSynthesis(mode="live")` row so reconnects and current API consumers
retain their existing contract.

The existing agents keep these responsibilities:

- `brief_meeting_lens`: post-call meeting record draft.
- `brief_discovery_lens`: post-call discovery/sensemaking draft.
- `brief_arbiter`: post-call reconciliation into the settled briefing.

No briefing-trio agent may run from the live interval loop. The trio runs only:

- during the normal full End Call drain; or
- from the explicit Generate Briefing/on-demand endpoint.

`End without briefing` continues to skip the trio.

## Runtime flow

When a live orchestrator starts and `strategic_signals` is enabled, it starts a
cycle using that agent's persisted `interval_seconds`. Each cycle skips empty
transcript windows, runs one structured call, persists the live synthesis, and
broadcasts the existing `synthesis_updated` WebSocket message.

The post-call drain remains unchanged except that it is now the only
orchestrator path that calls the two briefing lenses and arbiter. An explicit
post-call refresh uses the same trio. The REST API's explicit live refresh is
retained and dispatches only the standalone `strategic_signals` agent.

Failures are isolated: a live strategic-signals failure is logged and the next
configured cycle may retry; it never stops transcription or other live agents.
Briefing failures retain the existing partial/error synthesis behavior.

## Administration and session configuration

Administration places `strategic_signals` in Live Analysis and exposes the
same model, prompt, enable, and interval controls as other configurable agents.
The three briefing agents remain grouped under Post-Call Briefing without a
cadence control.

The pre-call per-session agent selector automatically includes the new seeded
row. Disabling `strategic_signals` suppresses live cards for that call without
disabling the post-call briefing. Disabling the briefing arbiter suppresses
the final/on-demand briefing without affecting live strategic signals.

## Public content

The "A crew, not a monolith" table lists every seeded default agent in display
order. It describes `strategic_signals` as a configurable 45-second live cycle
and describes all three briefing agents as "At call end or on demand." The
table test derives the expected slugs from `SEED_CONFIGS` so newly seeded
agents cannot silently disappear from the public page.

## Verification

Focused tests must prove:

- the new seed row has the model, prompt, interval, type, and display order;
- existing installations receive the new row without changing user-edited
  settings on other agents;
- the live orchestrator schedules only `strategic_signals`, using its stored
  interval and model/prompt overrides;
- the live structured output preserves insight evidence references;
- the briefing trio is not called during live cycles;
- full End Call and on-demand generation still call the briefing trio;
- End without briefing still skips the trio;
- Admin groups and labels the new agent correctly;
- the public table contains every seeded agent and the shipped trigger copy;
- backend tests, frontend build, docs-site site test, aggregate docs-site test,
  docs-site build, and structural checks pass.

## Release coordination

After verification, hand the frozen commit to the existing
`claude-helper-6` Herdr tab. That tab owns integration, the `v0.3.3` version
and release-note update, push to `master`, installer builds, and publication
verification. It must preserve the existing uncommitted landing-page polish
and include both the agent/runtime update and public-page update.

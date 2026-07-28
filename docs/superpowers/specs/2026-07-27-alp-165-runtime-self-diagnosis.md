# ALP-165 Runtime Self-Diagnosis Design

Linear: ALP-165 (Urgent). Branch: `agent/alp-165-runtime-self-diagnosis`.

## Problem

Every failure observed across a day of real use presented as silence: Privacy
First silently disabled all text agents (ALP-152); an OOM-killed backend left
the UI timer counting while nothing recorded (ALP-153); a briefing died on a
JSON decode that was really a context limit (ALP-154); fit-test budgets
displayed a number not in effect (ALP-158); a 2316-char analyst reply was
discarded field-by-field leaving the panel empty with no error (ALP-164); and
a 180s cadence meant nothing could appear for three minutes and nothing said
so.

The key insight: silence is the NORMAL state of a healthy early call. Interval
agents have not fired yet; slow local models have long budgets. Users cannot
use emptiness as a signal, so real failure is indistinguishable from normal
operation. The backend already knows the difference -- which agents were
admitted vs dropped, when each last ran and is next due, why a reply produced
nothing, whether diarization is shedding and transcription keeping up -- but
none of it reaches the UI. Diagnosis requires container logs.

This spec adds a live agent-activity surface during a call that answers "is
this working, and if not, what should I do?"

## Foundation (arriving 29-commit train -- consume, do not duplicate)

An unpublished train already lands the raw signals this surface consumes:

- ALP-152: the orchestrator records `privacy_blocked_agents` and includes it
  in the WS `status` message, with a named-agents "Listening" message. This
  surface reads that list as the source of blocked-by-privacy state; the
  Listening message itself is unchanged.
- ALP-153: a bounded diarization queue that sheds oldest-first with counted
  sheds. This surface reads the shed counter into call-level health.
- ALP-154: model errors are named (`finish_reason: length` truncation,
  self-hosted timeouts) instead of surfacing as JSON decode noise. This
  surface displays those names verbatim as failure details.
- ALP-158: fit results persist and the displayed cadence is the true cadence.
  This surface shows the interval the orchestrator actually resolved via
  `_get_interval` (per-model budget, then `interval_seconds`, then seeded
  default), so the displayed cadence is by construction the one in effect.

## Design overview

Three pieces:

1. **Backend activity registry** (new `backend/app/services/agents/activity.py`):
   one in-memory record per agent for the life of a call, owned by the
   `AgentOrchestrator`, updated by the agent loops and the audio pipeline,
   plus a small call-level health block (gateway, transcription, diarization).
2. **One new WS message** `agent_activity` carrying the full snapshot (roster
   is ~9 records; no delta protocol). Emitted on change, coalesced to at most
   one per 2 seconds, immediate for transitions into `failing`/`blocked` or
   call degradation.
3. **Frontend surface in ActiveCallView**: an ambient per-agent strip under
   the header, an expandable Agent Activity panel with last run / next due /
   last outcome / failure + remedy per agent, a degraded-state banner, and an
   honest healthy-waiting empty state in Live Insights that names when the
   first output is expected.

Nothing is written to the database. The registry lives and dies with the
orchestrator; every emission is a full snapshot, so a reconnect (new socket,
new orchestrator on resume) self-heals with the next snapshot.

## Data model: per-agent activity record

Held in `ActivityRegistry` (module `backend/app/services/agents/activity.py`),
keyed by agent slug. Records are plain dicts/dataclasses; no ORM model, no
migration.

```json
{
  "slug": "consolidated_analyst",
  "name": "Consolidated Analyst",
  "trigger": "interval",
  "state": "waiting",
  "enabled": true,
  "blocked_reason": "",
  "remedy": "",
  "interval_seconds": 40,
  "last_run_started_at": null,
  "last_run_ms": null,
  "next_due_at": "2026-07-27T18:02:40Z",
  "last_outcome": null,
  "last_error": null,
  "counts": {"runs": 0, "insights": 0, "deduped": 0, "errors": 0}
}
```

Field semantics:

- `trigger`: `interval` (consolidated_analyst, objection_handler,
  strategic_signals), `event` (synthesizer, opportunity_specialist),
  `stream` (audio_gateway), `post_call` (brief_* trio).
- `state`: one of
  - `running` -- a cycle is executing right now (or, for `stream`, the
    gateway task is alive and healthy);
  - `waiting` -- enabled, between cycles (interval), or armed for its event
    (event), or deferred to call end (post_call);
  - `blocked` -- enabled in config but not admitted to this call;
  - `off` -- disabled by global config or session override;
  - `failing` -- the most recent cycle errored (cleared by the next
    successful cycle), or the gateway is down/reconnecting.
- `blocked_reason` / `remedy` (set only for `blocked` and `off`):
  - `privacy_first` -> "Assign a local model to this agent (Admin -> Agents)
    or turn off Privacy First (Admin -> Connections)." Sourced from ALP-152's
    `privacy_blocked_agents`.
  - `disabled` -> "Enable it in Admin -> Agents."
  - `session_override` -> "Enabled globally but turned off for this session
    in pre-call agent selection."
  - `meeting_type` (opportunity_specialist when offering matching is off for
    this meeting type) -> "Runs for client/sales and customer delivery
    conversations; change the conversation type to enable it."
- `interval_seconds`: the effective value from `_get_interval` (ALP-158
  guarantee). Null for `stream` and `post_call`; for `event` agents it is the
  cooldown.
- `next_due_at`: interval agents only -- end of last cycle (or orchestrator
  start) plus the effective interval. The frontend renders the countdown
  client-side; the backend never re-emits just to tick a clock. Null for
  other triggers (the synthesizer's max-interval fallback is not surfaced;
  its `trigger` copy covers it).
- `last_outcome`: `{"kind": ..., "detail": ..., "items": n, "at": iso}`.
  Kinds, in the order an implementing agent should classify them:
  - `insights` -- n items saved and pushed.
  - `no_findings` -- reply parsed cleanly to an empty list. Legitimate quiet.
  - `all_deduped` -- items parsed but every one dropped by the orchestrator's
    60s word-overlap dedup. Detail: "3 items were near-duplicates of recent
    insights".
  - `all_filtered` -- the ALP-164 case: items parsed but all discarded by
    validation or the type filter. Detail must carry the reply length and a
    drop tally, e.g. "reply (2316 chars) yielded 0 usable items: 4 missing
    required fields, 1 disabled type".
  - `parse_failed` -- no JSON array recoverable. Detail: "reply (2316 chars)
    was not valid JSON".
  - `skipped_no_transcript` -- nothing to analyze yet.
  - `skipped_unchanged` -- objection handler's unchanged-window skip.
- `last_error`: `{"kind": ..., "detail": ..., "remedy": ..., "at": iso}` where
  kind is `timeout` | `truncated` | `api_error` | `refusal`, classified from
  the exception (ALP-154's named errors pass through as `detail`). Remedy
  examples: truncated -> "The model's reply hit its output limit; try a model
  with a larger context or shorten the agent prompt."; timeout on an
  `endpoint:` model -> "The self-hosted endpoint did not answer in time;
  check the server or raise this agent's cycle budget (Admin fit test)."
  `last_error` persists until the next successful cycle so the panel can
  always answer "what went wrong last".

Lifecycle:

1. `AgentOrchestrator.__init__` creates the registry and a record for every
   agent slug it knows (the nine seeded slugs), deriving `enabled`, `state`,
   `blocked_reason`, and `interval_seconds` from `_is_enabled` /
   `_get_interval` and ALP-152's privacy admission result.
2. `start()` emits the initial snapshot right after the existing "Listening"
   status message.
3. Each loop iteration brackets its cycle: `registry.cycle_started(slug)`
   (state `running`), then `registry.cycle_finished(slug, outcome)` or
   `registry.cycle_error(slug, error)` (state back to `waiting` or `failing`,
   `next_due_at` advanced).
4. `graceful_drain` / `close_all` emit one final snapshot (post_call agents
   transition through `running` during the drain stages) and then the
   registry is discarded with the orchestrator.

### Call-level health block

Included in every snapshot:

```json
{
  "privacy_first": false,
  "degraded": false,
  "degraded_reasons": [],
  "gateway": {"state": "ok", "detail": ""},
  "transcription": {"jobs": 12, "failed": 0, "last_error": ""},
  "diarization": {"queued": 1, "shed": 0}
}
```

- `gateway.state`: `ok` | `reconnecting` | `off`, from
  `_maintain_audio_gateway` / `check_health`.
- `transcription`: mirror of `OrderedTranscriptionQueue.stats` failure counts
  plus the last failure message the existing handler produced.
- `diarization.shed`: the ALP-153 bounded-queue shed counter.
- `degraded` is true when any of: `transcription.failed > 0`,
  `diarization.shed > 0`, or `gateway.state == "reconnecting"` while the
  gateway agent is enabled. `degraded_reasons` carries one short user-facing
  sentence per active cause. (Loss of the WebSocket itself cannot be reported
  by a dead backend; the frontend derives that case locally -- see Frontend
  surface.)

## Transport

One new server-sent WS message type on the existing `/ws/{session_id}`
endpoint, extending the protocol list in CLAUDE.md:

```json
{
  "type": "agent_activity",
  "data": {
    "session_id": "<uuid>",
    "at": "<iso8601>",
    "agents": [ { ...AgentActivityRecord } ],
    "call": { ...CallHealth }
  }
}
```

Rules:

- Always a full snapshot. Nine small records; no delta protocol, no ordering
  concerns, missed frames self-heal on the next emission.
- Coalesced: at most one emission per 2 seconds, except transitions into
  `failing` or `blocked` and `degraded` flips, which emit immediately.
- No periodic heartbeat: countdowns are computed client-side from
  `next_due_at`, and every cycle boundary already emits.
- Existing message types are untouched. The `transcription_error` status
  toast path stays as-is (it additionally updates `call.transcription`).
  The ALP-152 "Listening" message stays the human-readable admission
  announcement; `agent_activity` is the machine-readable state behind it.

## Backend emission points (file-level)

| Signal | Originates in |
| --- | --- |
| Registry, snapshot serialization, coalesced emit | `backend/app/services/agents/activity.py` (new; sends via the orchestrator's websocket) |
| Roster, enabled/blocked/off + reasons, effective intervals | `backend/app/services/agents/orchestrator.py` `__init__`/`start()` (`_is_enabled`, `_get_interval`, ALP-152 `privacy_blocked_agents`) |
| Interval cycle start/end, next due | `orchestrator.py` `_consolidated_agent_loop`, `_objection_agent_loop`, `_strategic_signals_loop` |
| Event-agent runs (cooldown-triggered) | `orchestrator.py` `_run_synthesizer`, `_run_opportunity_specialist` |
| Per-cycle outcome classification (parse/filter/dedup tallies) | `backend/app/services/agents/consolidated_analyst.py` and `objection_handler.py` set `self.last_outcome` during `run_cycle` (parse-stage drop counters in `_parse_response` and the type filter); `orchestrator.py` merges its own dedup drops from `_save_and_send_insight` before recording |
| Model-call errors (timeout/truncated/refusal, ALP-154 names) | caught in each agent's `run_cycle` `except` today; re-raised classification recorded via the same `last_outcome` side channel |
| Gateway health | `backend/app/ws/audio_pipeline.py` `_maintain_audio_gateway` updates `call.gateway` through the orchestrator's registry reference |
| Transcription keep-up | `audio_pipeline.py` `_transcription_failure_handler` (existing) additionally updates `call.transcription` |
| Diarization shedding | the ALP-153 shed path in `backend/app/ws/audio_runtime.py` / `audio_pipeline.py` increments `call.diarization.shed` |
| Post-call trio state during drain | `orchestrator.py` `graceful_drain` stage brackets |

Implementation notes:

- The `self.last_outcome` side channel keeps `run_cycle` signatures unchanged
  (both live loops and the drain call them); the orchestrator reads the
  attribute immediately after each call. Ponytail: no reporter callback
  plumbing, no return-type change.
- The registry needs no lock: everything runs on the event loop, and the
  registry is per-orchestrator like `_live_orchestrators` (same single-worker
  ceiling, same upgrade path).
- `strategic_signals`, `synthesizer`, and `opportunity_specialist` cycles run
  through module functions rather than agent instances; the orchestrator
  brackets those calls itself and classifies from the returned ops/synthesis
  (`insights` when ops applied, `no_findings` when empty, `error` on
  exception). Fine-grained parse tallies for them are not required for
  acceptance; extend later if their silence proves ambiguous in practice.

## Frontend surface

New types in `frontend/src/types/index.ts`: `AgentActivityRecord`,
`CallHealth`, `AgentActivitySnapshot`, and a `WSMessage` variant
`{ type: "agent_activity"; data: AgentActivitySnapshot }`.

`frontend/src/App.tsx`: handle `agent_activity` in the existing message
switch; hold the latest snapshot in state keyed to the runtime session (same
`runtimeMatchesView` gating as questions/transcripts); pass it to
`ActiveCallView`.

`frontend/src/components/ActiveCall/AgentActivityPanel.tsx` (new), rendered
in `ActiveCallView` directly below the header, above `SynthesisSignals`:

- **Ambient strip (always visible):** one compact chip per agent that is part
  of this call's live story: live agents individually, post_call trio
  collapsed into one "Briefing: at call end" chip, `off` agents omitted.
  Chip = state dot + name (+ countdown for waiting interval agents). Dot
  colors: green pulse `running`, neutral `waiting`, amber `blocked` or
  running late, red `failing`. When Privacy First blocks agents, a single
  summary chip "N agents off: Privacy First" precedes the roster. The strip
  is one line tall and never grows; it is the glanceable answer to "is this
  working".
- **Expandable panel (click the strip):** a table, one row per agent (blocked
  and off agents included here): state, why (blocked/off reason + remedy),
  last run (relative time + duration), next due (countdown), last outcome
  (the classified sentence, e.g. the ALP-164 "reply (2316 chars) yielded 0
  usable items..." line), last failure + remedy. Plus a call-health footer
  row showing gateway, transcription, and diarization figures. This subsumes
  the current `backendAudioStatus` debug line's diagnostic role; the Debug
  toggle and its audio-send stats remain unchanged.
- **Running late (client-side):** a waiting interval agent whose
  `next_due_at` is more than one full interval in the past renders its chip
  amber with "running late". Pure client derivation from data already in the
  snapshot; deeper staleness semantics belong to ALP-160.

**Degraded-state banner** in `ActiveCallView`, full width above the two
columns:

- Red, frontend-derived: WebSocket not `connected` while the call view is
  active (the ALP-153 OOM shape -- a dead backend cannot report itself):
  "Connection to the backend was lost. Audio is not being recorded. Use
  Resume Audio to reconnect." While in this state the session timer dims and
  shows a "not recording" label so it stops asserting progress.
- Amber, backend-reported: `call.degraded` true -- renders
  `degraded_reasons` verbatim (e.g. "Falling behind: N seconds of audio were
  skipped for speaker processing", "Transcription failed for N segments").
- No banner when healthy; the banner is reserved for degradation so its
  appearance means something.

**Healthy-waiting empty state** in the Live Insights column (`QuestionList`
empty case): when the snapshot shows no failures and no insights exist yet,
render "Agents are listening. {analyst name} checks every {interval}s --
first insights expected in about {countdown}." driven by the earliest
`next_due_at` among enabled interval text agents. After the first cycle it
becomes "...next check in {countdown}." A 180s local-model cadence therefore
reads as a schedule, not a stall.

## Settled design decisions

**(a) Live call view, not a separate diagnostics panel.** The question "is
this working?" is asked mid-call, at a glance, usually while the user is also
talking to someone. Navigating away to a diagnostics page fails acceptance 1
and 6 in spirit and practice. But a full diagnostic table permanently on
screen would crowd the insight surface that is the product. So: split within
the view -- a one-line ambient strip always visible, full detail one click
away, degradation promoted to a banner that needs no click. Admin-level
diagnostics (fit test, diarization card) stay where they are; this surface is
strictly per-call runtime state.

**(b) Durable per-call health record, not transient toasts.** Every failure
in the issue list is a persistent *state* (blocked, falling behind, producing
nothing usable), not a momentary event. A toast fires once, vanishes, and
cannot be re-consulted when the user looks up two minutes later wondering why
the panel is empty -- which is exactly the observed failure mode. The record
form also makes reconnects and missed frames free (full snapshot replay) and
costs no schema: in-memory per orchestrator, no DB table, no migration.
Durable means "for the life of the call and always inspectable", not
persisted across restarts -- a backend restart drops the socket, which the
red banner already makes unmissable. The one existing toast-shaped path
(`transcription_error` -> `captureError`) is kept, now backed by the same
counters in `call.transcription` so its information survives the moment.

**(c) Cadence honesty = state the schedule, never just absence.** An empty
panel and a slow cadence are only alarming when the UI stays mute about
expectation. Rule: any healthy waiting state must carry a concrete "next
check in Ns" countdown, and the pre-first-cycle empty state must name when
the first output is expected. The countdown derives from the same
`_get_interval` resolution the loops sleep on (ALP-158), so it cannot show a
number not in effect. A healthy 3-minute cadence renders as "checks every 3m
-- next in 2:41", which reads as scheduled; only an agent overdue by more
than a full interval gets amber "running late". The line between honest
patience and alarm is therefore mechanical (overdue > 1 interval), not
tonal.

## Acceptance mapping

1. *Per-agent running/paused/failing + why, without leaving the app* -- the
   strip shows state per agent; the panel shows why (blocked/off reason,
   last failure); all inside ActiveCallView.
2. *An agent producing nothing usable reports the reason at that moment* --
   `last_outcome` classification (`parse_failed`, `all_filtered`,
   `all_deduped`, `no_findings`) is recorded at the end of the same cycle and
   emitted immediately on the failing transitions, with reply length and drop
   tallies in the detail (the ALP-164 case becomes one readable sentence).
3. *Blocked agents name the remedy* -- `blocked_reason` maps to a concrete
   `remedy` string (Privacy First -> assign a local model or turn Privacy
   First off; disabled -> where to enable; meeting type -> what to change),
   rendered in the panel and summarized on the strip.
4. *Degraded calls look degraded, not quiet* -- backend-reported degradation
   (shedding, transcription failures, gateway reconnecting) raises the amber
   banner with reasons; a lost backend raises the red banner and un-asserts
   the timer; failing/late agents turn their chips red/amber.
5. *A healthy pre-first-cycle call reads as healthy and says when to expect
   output* -- the healthy-waiting empty state names the analyst's cadence and
   a countdown to the first expected output; chips show neutral waiting dots
   with countdowns, not blanks.
6. *Nothing requires container logs* -- every signal listed in the emission
   table reaches the snapshot; the panel is the in-app equivalent of the log
   lines that diagnosed ALP-152/153/154/158/164.

## Verification

- Backend (`backend/tests/`, stdlib unittest): registry lifecycle (roster
  derivation incl. privacy-blocked and session-override records; cycle
  bracket transitions; next_due math; coalescing window; immediate emit on
  failing/blocked/degraded); outcome classification unit tests for
  `consolidated_analyst` and `objection_handler` `_parse_response`/type
  filter tallies (including a fixture reproducing the ALP-164
  discarded-reply shape); snapshot JSON shape.
- Frontend: `npm run build` (typecheck) over the new types, message handling,
  and components.
- Manual: one Privacy First call (blocked chips + remedies), one healthy call
  (waiting countdowns, first-cycle output), one pulled-backend call (red
  banner, timer un-asserts).

## Out of scope / follow-ups

- **ALP-156 pre-call admission story**: telling the user *before* starting a
  call which agents will run and which will be blocked. This spec surfaces it
  live once the call starts; the pre-call view is a separate issue.
- **ALP-160 staleness**: aging/expiring of the insights themselves and any
  richer overdue semantics beyond the mechanical "running late" chip.
- Persisting activity records to the DB / a post-call "call health" review
  tab. The in-memory record covers the live question; add persistence only
  if post-mortem demand materializes.
- Fine-grained parse tallies for `strategic_signals`/`synthesizer`/
  `opportunity_specialist` (bracketed coarsely here).
- Multi-worker registry sharing (same ceiling and upgrade path as the
  existing `_live_orchestrators` in-process dict).
- Any change to toasts, the Debug toggle's audio stats, or the ALP-152
  "Listening" status copy.

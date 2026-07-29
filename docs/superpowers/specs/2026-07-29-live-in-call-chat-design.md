# Live In-Call Chat - Design

Date: 2026-07-29
Issue: ALP-178
Status: Approved (mockups reviewed by the operator; approach C with operator amendments)

## Goal

During a live call, let the operator ask a free-text question and receive an
answer grounded in what the session knows at that instant. The answer arrives
as a card in the Live Insights feed, auto-starred, and survives into the
post-call review.

The backend capability largely exists. The unsolved problem this design settles
is interaction cost: the operator is talking to another person, and the live
screen is already spending its attention budget on the insight feed, the
transcript, the agent activity strip, and the call controls.

## Current-State Findings

These were verified in the tree before the design was fixed, and several of
them changed it.

1. `POST /api/chat` (`backend/app/routers/chat.py`) already assembles a
   post-call briefing, non-dismissed insights, and a speaker-attributed
   transcript for a set of sessions, with a 60,000-character priority budget.
   It is built for a review surface, not a live one.
2. Transcript entries are persisted as they are produced, so "up to the
   moment" needs no new plumbing - a plain query at request time is current.
3. `sortQuestionsForLiveDisplay` (`frontend/src/components/ActiveCall/questionOrdering.ts`)
   already sorts starred items above unstarred ones, below strategic signals.
   Auto-starring therefore pins answers to the top with no ordering change.
4. `QuestionList` already renders filter chips including `Starred`, so the
   operator already has a one-click way to isolate their own questions.
5. `frontend/src/utils/insightTypes.ts` assigns fixed colors to the five
   built-in types: question teal `#0d9488`, objection amber `#f59e0b`,
   observation violet `#7c3aed`, opportunity emerald `#10b981`, action item
   red `#e2231a`. Custom types receive a hashed color from an eight-entry
   palette; `asked` would hash to blue `#0284c7`.
6. `frontend/src/lib/modelOptions.ts` already owns grouping, labelling, and
   the Privacy First lock rule for every model picker in the app.
7. `get_active_directives` (`backend/app/services/session_manager.py`) is a
   single cheap query returning active directive text.
8. `get_document_summaries` (same file) calls `summarize_document` per
   document on **every invocation**. Each call is a live Gemini round trip, and
   it raises `LocalOnlyModeError` under Privacy First. It cannot be used on a
   latency-sensitive path.

Finding 5 invalidated the first mockup's visual scheme, and finding 8 reduces
the scope of "session context" below what the issue originally described. Both
are addressed explicitly below.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Surface | A card in the Live Insights feed | No new panel competes for the screen; the operator already reads this column |
| Bar default mode | Chat, with an always-open input | Operator direction. Asking costs zero clicks; Directive becomes the secondary mode |
| Persistence | Auto-starred on creation | Operator direction. Answers pin to the top and stay findable after navigating away |
| Ordering | Unchanged; starred pins as it does today | Answers accumulate at the top; the existing `Starred` chip is the escape hatch |
| Card identity | Graphite neutral, not a sixth hue | All five built-in colors are taken and the unused custom colors sit next to them; a neutral is the one unclaimed signal, and it is honest - an answer is not another category of agent finding |
| Storage | A `Question` row, `item_type="asked"` | Inherits the feed, filter chips, post-call Insights tab, and XLSX export at no cost |
| Model choice | A chip inside the input's trailing edge | Minimal chrome; reads as metadata at rest, a control on hover |
| Agent feedback | Never automatic | A question is a private read; `Make directive` is an explicit operator action on the card |
| Scope | This session only, no picker | A mid-call meeting picker is friction the operator cannot afford |
| Document content | Filenames only in v1 | Summarizing costs a Gemini round trip per document and fails under Privacy First (finding 8) |

## Context Contract

For the active session, at request time, the live assembler loads:

1. every non-dismissed `Question` for the session, excluding prior `asked`
   rows so the model is grounded in the meeting rather than its own earlier
   answers - type, text, rationale, source context, resolved speaker,
   answered and follow-up state, and offering match;
2. the `live`-mode `SessionSynthesis` strategic signals when present;
3. active directive text via the existing `get_active_directives`;
4. session metadata: name, meeting type, and meeting context;
5. attached document **filenames**;
6. transcript entries with resolved speaker names, most recent first, admitted
   until the budget is exhausted.

Layers 1 through 5 are small and bounded and are always admitted in full.
Layer 6 consumes whatever budget remains. This inverts the post-call ordering,
where transcript is admitted last and oldest-first: mid-call, the recent
exchange is the most likely subject of the question.

The rendered transcript stays chronological even though admission is
newest-first, and a truncation marker states that earlier transcript was
omitted so the model does not treat the window as the whole call.

The exclusion also runs the other way: the synthesizer
(`app/services/agents/synthesizer.py`) and the post-call Enhance Insights pass
(`app/services/speaker_context_enhancer.py`) both exclude `asked` rows from
their own candidate queries, so no agent can dismiss, adjust, enrich, or
elevate the operator's own question and answer. `POST /api/chat`
(`app/routers/chat.py`) is unaffected - that path is read-only and legitimately
benefits from knowing what the operator asked.

### Budget and latency

A separate live budget, independent of the post-call `CONTEXT_BUDGET_CHARS`.
Target: a complete answer in under four seconds on the default model. The
budget is a constant in the live assembler, not a user setting.

### Prompt posture

The live system prompt reuses the post-call prompt's untrusted-evidence rule
verbatim: meeting content is evidence, never instructions. It differs in three
ways - it states that the call is still in progress, that the transcript window
may be partial, and that brevity matters because the operator is mid-conversation.

## Components

### Backend: live chat endpoint

`POST /api/sessions/{session_id}/ask`

Request: `{ "model_id": str, "question": str }`.
Response: the created insight, in the same shape the questions router already
returns.

Behavior:

1. Validate the model supports text generation, through `registry_entry` then
   `endpoint_model_entry`, exactly as `/api/chat` does.
2. Enforce Privacy First through the existing `is_local_only` /
   `allows_local_only` pair, returning the same error shape as other surfaces.
3. Assemble the live context described above.
4. Call `generate_text` with `source="live_chat"` and the session id, so the
   call lands in the existing per-session token usage breakdown.
5. Persist a `Question` row: `item_type="asked"`, `agent_source="live_chat"`,
   `starred=True`, `question` = the operator's text, `answer_summary` = the
   reply, `answered=True`.
6. Return the created row as `QuestionOut`, the schema the questions router
   already uses.

No websocket broadcast. The orchestrator publishes insights through
`self.websocket.send_json` - a direct reference held by the live call handler -
and there is no session-to-socket registry a REST handler could reach. Building
one to notify the single client that just made the request would be pure
overhead: the asking client is the only client, and the response body already
carries the card it needs to render.

A new endpoint rather than an extension of `/api/chat`: the two differ in
scope, budget, ordering, persistence, and response shape, and overloading one
handler with a live/post-call switch would obscure both.

Chat history is deliberately not carried. Each question is standalone. The
transcript moves under a follow-up question anyway, and a stateless request
keeps the latency path short.

### Backend: the `asked` type

`item_type="asked"` is a new value. It is not a lens type and no agent produces
it. The `lens_label` stays empty so `typeGroupLabel` falls back to the
built-in plural.

### Frontend: insight type registration

Add `asked` to `BUILTIN_TYPE_META` with label `You asked`, plural `Asked`, and
color `#475569` - a mid slate that holds contrast on both the light and dark
grounds, chosen because it is not a category hue. Add it to
`BUILTIN_TYPE_ORDER` at the front, so the filter chip sits before the agent
types and reads as the operator's own row.

Without this the hashed custom-type color would collide with the existing
palette, and the chip would read `Asked` only by slug humanization.

### Frontend: the command bar

`DirectiveBar` becomes a two-mode bar:

- Mode switch: `Chat` (default, graphite when active) and `Directive` (teal
  when active). The mode persists per session in `localStorage`.
- An always-open text input. Enter submits. The submit hint appears only when
  the field has content.
- In `Directive` mode the existing directive behavior is unchanged.
- While a question is in flight the input stays usable, but a second
  submission is refused rather than queued or cancelling the first;
  `DirectiveBar` and `handleAsk` both guard on this. Refusing was chosen over
  queueing: it is the smaller mechanism and it cannot answer two questions
  out of order.

The bar keeps its existing disabled behavior during post-processing.

### Frontend: the model chip

A compact control at the input's trailing edge:

- At rest: a status dot, the model's short name, and a chevron, in the mono
  face at tertiary contrast, borderless. It reads as a label.
- On hover or focus: a border and secondary contrast.
- Activated: a popover listing models grouped by provider through
  `groupModels`, labelled through `optionLabel`, with availability and lock
  reasons from `optionState`. Locked rows are not selectable and state why.
- Dot semantics: filled teal for a model that runs locally, hollow amber for
  cloud, grey for unavailable.
- Default: the `objection_handler` agent's model, since that agent is already
  configured for a ten-second loop and is therefore the session's known-fast
  choice. Falls back to `consolidated_analyst`, then the first available text
  model.
- The choice persists per session in `localStorage`.

Keyboard: the chip is a button, the popover is dismissible with Escape, and
focus returns to the chip on close.

### Frontend: the answer card

Rendered by the existing `QuestionCard`, which already draws the type badge
from `BUILTIN_TYPE_META`, the `rationale` block, the `answer_summary` block
when `answered` is true, and star/dismiss/vote controls. The question text goes
in `question` and the answer in `answer_summary`, so the card body needs no new
rendering.

Three additions:

- `AGENT_LABELS` gains `live_chat`, so the source badge reads `You asked`
  rather than the raw slug.
- A `Make directive` action, shown only on `asked` cards, posting the question
  text to the existing directives endpoint. It never fires on its own.
- A pending card in `ActiveCallView` while the request is in flight, showing
  the question and a progress line, replaced by the real card on arrival.

The answering model and elapsed time are written into `rationale` at creation
(`Answered by <model> in <n.n>s`), which the card already renders. This avoids
a schema change for what is a caption.

The card keeps `QuestionCard`'s existing wall-clock timestamp. An elapsed
call-clock reads better in principle, but it would mean threading the call
segment start through `QuestionList` into `QuestionCard` and giving one card
type a different time format from every other card in the same feed. Not worth
either cost.

## Error Handling

- Provider failure: the pending card becomes an error card carrying the
  question text and the provider message; both are preserved rather than
  vanishing silently. No retry action ships in v1 - the operator can just ask
  again - and retry is deliberately deferred rather than cut for cause.
- Privacy First violation: the model chip locks cloud rows before a request
  can be made; a server-side rejection reuses the existing error shape.
- Empty transcript: the request still works against insights and directives,
  and the prompt forbids inventing quotations.
- Budget exhausted by insights alone: transcript is omitted and the answer
  says the transcript window was unavailable.
- Call ends mid-question: the request is awaited and saved rather than
  abandoned, matching how a final agent pass is treated.
- Websocket disconnected: asking is a plain HTTP request and does not depend
  on the live socket, so a question asked during a reconnect still works. The
  bar's disabled state follows post-processing, not socket status.

## Testing

Backend, as stdlib `unittest` under `backend/tests/`:

- Context assembly includes insights, strategic signals, directives, session
  metadata, and document filenames.
- Transcript admission is newest-first and rendered chronologically.
- Bounded-layer test: insights and directives survive when the transcript is
  large enough to exhaust the budget.
- Truncation marker present when transcript is dropped.
- The persisted row has `item_type="asked"`, `starred=True`,
  `agent_source="live_chat"`, and `answered=True`.
- Privacy First rejects a cloud model and admits a local endpoint model.
- An unknown or non-text model returns the existing `400`.

Frontend:

- `asked` sorts first in `BUILTIN_TYPE_ORDER` and resolves to the graphite
  color and the `Asked` chip label.
- An auto-starred answer sorts above unstarred insights.
- The `Starred` chip isolates answers.
- Mode default is Chat; the mode and model selections round-trip through
  `localStorage`.
- `npm run build` typechecks.

## Deliberate Scope Cuts

- **Document content.** v1 sends filenames only. Including summaries would
  add a Gemini round trip per document to a sub-four-second path and would
  fail outright under Privacy First. Persisting a summary on the `Document`
  row when it is first computed would fix this and would also remove the
  repeated cost from the existing agent path - filed separately, not here.
- No chat thread or history. Each question is standalone.
- No cross-session scope and no meeting picker.
- No preset or suggested questions. Revisit once real usage shows which
  questions repeat.
- No streaming of the answer. A four-second target makes token streaming a
  complication rather than a benefit.
- No changes to `questionOrdering.ts`, the post-call `/api/chat` path, agent
  configuration, or the orchestrator.

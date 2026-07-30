# ALP-191 Durable Strategic-Signal History Design

Date: 2026-07-30
Issue: ALP-191
Status: Approved after operator direction and independent fable-root review

## Goal

Give the post-call briefing complete, bounded context from saved insights and
the live Strategic Signals agent without changing the live synthesis API or
turning transient signal cards into editable `Question` rows.

The briefing must receive:

- every admitted non-dismissed insight with its answer, follow-up, source,
  vote, offering-match, and agent-source details;
- operator `asked` rows, where `question` is the user query and
  `answer_summary` is the model response; and
- durable, deduplicated history from every successful live Strategic Signals
  cycle.

## Existing Boundaries

The final transcript remains the persisted `TranscriptEntry` sequence, not the
interim caption stream. The meeting and discovery lenses continue to receive
the raw briefing context. The arbiter remains source-isolated: it receives the
two lens JSON documents plus bounded operator-authored meeting context, but
never the transcript, saved insights, directives, documents, speaker roster,
or strategic-signal history directly.

The latest `SessionSynthesis(mode="live")` fields keep their existing shapes.
The live UI and in-call Ask endpoint continue reading those latest-cycle fields
without receiving the history.

## Storage

Add a server-only `signal_history` JSON column to `session_syntheses`. It is
not added to `SessionSynthesisOut`.

Each successful live cycle contributes cards from:

- `strategic_signals`;
- `risks_blockers`;
- `unresolved_discovery_questions`;
- `top_opportunities`; and
- `action_plan`.

History is deduplicated inside the existing `_persist_synthesis` transaction,
after the advisory lock and row lock have been acquired. It is updated only
when `mode == "live"` and `status == "completed"`. Post-call and error
persistence never alter it.

An entry contains the source section, latest card fields, `first_seen`,
`last_seen`, `count`, and the latest model id. Evidence references are
latest-only so repeated cycles cannot grow one entry without bound.

Identity is `(section, normalized title)`. Normalization case-folds, collapses
whitespace, and strips trailing punctuation. If the title is empty, normalized
summary is the fallback. A matching entry keeps `first_seen`, increments
`count`, updates `last_seen`, and replaces the body with the latest wording.
A changed title creates a new entry. `count` records observed card occurrences,
not distinct completed cycles, so duplicate cards in one cycle each count.

The history is capped at 200 entries. When the cap is exceeded, entries with
the oldest `last_seen` are evicted. This represents every repeated observation
through occurrence metadata while preventing unbounded JSON-row growth.
SQLAlchemy JSON mutation must use whole-list reassignment; in-place append is
not considered persisted behavior.

Migration `021` adds the column with a non-null empty-list default. The startup
`_add_missing_columns` patch adds the same column for desktop and older local
databases that do not run Alembic.

## Briefing Context

All non-dismissed `Question` rows are loaded in creation order. Each admitted
entry is compact JSON containing:

- `id`, `item_type`, `question`, and `rationale`;
- `source_context`;
- `answered` and `answer_summary`;
- `needs_followup` and `followup_question`;
- `vote` and `offering_match`; and
- `agent_source`.

For `item_type="asked"`, `question` is explicitly documented as the operator's
query and `answer_summary` as the generated response. Answered rows remain
eligible; only dismissed rows are excluded.

Insight and signal-history context have separate fixed character budgets:
`BRIEF_INSIGHTS_BUDGET_CHARS = 12000` and
`BRIEF_SIGNAL_HISTORY_BUDGET_CHARS = 6000`. Both admit newest entries first,
render admitted entries chronologically, use compact JSON separators, and
include an explicit truncation marker when older entries are omitted. The
newest entry is clipped if necessary so the section never goes blank. The
formatted signal history is appended to the Existing Insights context consumed
by both lenses, so existing custom lens prompts that retain `{insights_text}`
receive it without a new placeholder. The same bounded rich-insight JSON is
intentionally used by the live Strategic Signals prompt.

The history formatter exposes occurrence metadata so a lens can distinguish a
one-off cue from a signal repeated across the call.

## Arbiter Contract

The arbiter input remains unchanged:

- operator-authored meeting context;
- `mode="post_call"`;
- meeting-lens JSON; and
- discovery-lens JSON.

It does not receive transcript markers, insight JSON, signal-history entries,
directives, document summaries, or speaker metadata. Meeting context remains
because it is bounded framing supplied by the operator and keeps reconciliation
appropriate to the selected meeting type; it is not call evidence.

## Error and Compatibility Behavior

- A failed or partial Strategic Signals cycle does not add history.
- Blank or explicitly unselected agent models are not replaced or inferred.
- Existing latest-cycle live payloads and `SessionSynthesisOut` stay unchanged.
- A missing history column is repaired by startup schema patching.
- Existing rows start with an empty history and remain readable.
- No changes are made to first-run model selection, provider recommendations,
  the orchestrator constructor, or the activity roster.

## Verification

Backend tests must prove:

1. Insight formatting includes every requested field and preserves an `asked`
   query/response.
2. Oversized insight context admits newest entries first, remains valid compact
   JSON, and reports truncation.
3. Reworded cards with the same normalized title deduplicate while changed
   titles remain distinct.
4. Counts and first/last timestamps update correctly.
5. Two separate persistence transactions retain both history updates after a
   fresh read, guarding against in-place JSON mutation.
6. The 200-entry cap evicts the oldest `last_seen`.
7. Post-call and error persistence do not modify history.
8. Signal-history context is admitted newest-first under its own budget and is
   included in both lens prompts.
9. The arbiter prompt contains meeting context and lens outputs but no raw
   transcript, insights, or history markers.
10. Latest-cycle live fields keep their existing shape and
    `SessionSynthesisOut` does not expose history.
11. Alembic upgrade/downgrade and startup schema patching agree on the column.

Run the focused briefing, strategic-signals, provider-routing, and schema
suites, then the full backend suite. On Windows, the pre-existing
`test_master_key_file_created_private` `0o600` versus `0o666` mismatch is
environmental only if it remains the sole failure.

## Deliberate Limits

The JSON history is intentionally capped. If production needs raw per-cycle
audit playback, cross-session history queries, or more than 200 unique live
cards per call, replace it with the previously rejected snapshot table. Until
then, a bounded column on the already locked live synthesis row is the smallest
durable design.

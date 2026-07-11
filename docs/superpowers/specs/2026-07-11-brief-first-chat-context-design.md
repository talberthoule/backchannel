# Brief-First Meeting Chat Context - Design

Date: 2026-07-11
Status: Approved

## Goal

Make post-call chat consider the saved briefing, saved insights, and
speaker-attributed transcript for every selected meeting. Use the briefing to
frame what matters most while retaining insights and transcript evidence.

## Current-State Finding

Chat currently queries only `Session`, `Speaker`, and `TranscriptEntry`.
`SessionSynthesis` and `Question` rows are never loaded, and the system prompt
explicitly tells the model to use only transcripts. Briefings and insights are
therefore absent rather than merely underweighted.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Primary interpretation | Completed/partial post-call briefing | It is the settled dual-lens synthesis and the user's preferred frame |
| Supporting context | Non-dismissed saved insights | Preserves detail, follow-ups, rationale, answers, and agent findings |
| Ground truth | Speaker-attributed transcript | Direct statements and quotations must remain traceable to the meeting |
| Weighting mechanism | Explicit source roles plus priority-aware character budget | Deterministic, testable, and requires no retrieval infrastructure |
| Conflict behavior | Surface conflicts; transcript wins factual quotations | A synthesis is useful but must not overwrite direct evidence silently |
| Retrieval architecture | Existing relational queries | Vector search/RAG is unnecessary at the current 60,000-character scope |

## Context Contract

For every selected session, the backend loads:

1. the `post_call` `SessionSynthesis` row when its status is `completed` or
   `partial`, including settled sections, insight clusters, and arbiter notes;
2. every non-dismissed `Question`, ordered by creation time, including type,
   text, rationale, answer/follow-up state, offering match, and source context;
3. every transcript entry in sequence with its resolved speaker name; and
4. session name/date metadata.

Missing briefing or insights are valid empty states. Chat still works from the
remaining sources.

## Prompt Structure and Weighting

The system instruction defines the source roles:

- Begin from the briefing when deciding priorities, themes, outcomes, risks,
  and next steps.
- Use saved insights to retain supporting analysis and unresolved detail.
- Use the transcript as factual evidence and the only source for direct quotes.
- When sources disagree, say what conflicts and ground the factual answer in
  the transcript instead of hiding the discrepancy.
- If none of the supplied sources contains the answer, say so plainly.

The user prompt is assembled in this order:

1. `Meeting Briefings (primary context)`
2. `Saved Insights (supporting context)`
3. `Meeting Transcripts (grounding evidence)`
4. bounded chat conversation

The existing 60,000-character meeting-context budget is shared by priority.
Available briefings are admitted before insights, and insights before
transcript text. Sessions are sorted by their actual meeting date; within each
layer, the newest meetings retain priority under truncation while rendered
output remains chronological. Brief and insight blocks carry session headers
so cross-meeting answers remain attributable.

This is semantic and budget priority, not blind authority: the briefing guides
the answer, while direct transcript evidence can correct it.

## Components

### Backend chat router

- Extend the existing per-session query to load `SessionSynthesis` with
  clusters and active `Question` rows.
- Bound the number of selected session IDs at the request boundary.
- Format compact briefing and insight blocks with existing persisted fields.
- Extend `build_chat_prompt` to apply the priority-aware budget.
- Update the system prompt to describe source precedence and conflict rules.

No new endpoint, model, table, background task, or dependency is introduced.

### Frontend chat copy

The session selector label changes from `Transcripts:` to `Meetings:`. Empty
state and input copy say the selected meeting briefing, insights, and transcript
are in scope. Request/response shapes remain unchanged.

## Error Handling

- Missing synthesis: omit the briefing block and continue.
- Error/pending synthesis: do not present it as a settled briefing; continue
  with insights and transcript.
- No insights: omit the insight block and continue.
- No transcript: briefing/insight questions still work, but the model must not
  invent direct quotations.
- Context beyond budget: truncate lower-priority transcript content first and
  include an explicit `[truncated]` marker.
- Unknown selected session/model failures: preserve the current `404`/`400`
  behavior.

## Testing

- Prompt unit tests prove briefing, insights, transcript, and conversation are
  all included when available.
- Ordering tests prove briefing precedes insights and insights precede
  transcript.
- Budget tests prove transcript truncates before insight or briefing content.
- Empty-state tests cover missing briefing, missing insights, and missing
  transcript.
- Existing newest-session truncation and bounded-history tests remain valid.
- The complete backend suite and frontend production build run before merge.

## Deliberate Scope Cuts

- No embeddings, vector database, relevance classifier, or extra LLM call.
- No user-adjustable weighting slider; the source contract is product behavior.
- No regenerated briefing at chat time; chat uses the persisted settled result.
- No changes to synthesis generation or insight creation.

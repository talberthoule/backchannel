# Backchannel enhancement backlog

Prepared for Linear on 2026-09-10 from the September codebase review and user feedback.
These began as issue drafts; no Linear tools or connected browser were available
in the authoring session. The rendering portion of item 6 is now tracked in
ALP-396 and implemented in commit 6480433, with approval recorded by the reviewer.
The remaining items are drafts: recheck Linear for duplicates before filing.
Source observations should be revalidated when work starts.

## 1. Track meeting commitments with editable owners, dates, and progress

Suggested priority: High. Type: Feature.

Problem: Generated briefing action plans are useful summaries, but users need
durable commitments they can correct, assign, complete, and review across meetings.

Scope:

- Editable commitment description, owner, optional due date, and status.
- Statuses: Open, In progress, Blocked, Completed; completed work can be reopened.
- A meeting view and a group-level open-commitments view share the same records.
- Review the group's remaining open commitments during setup for the next meeting.
- Retain links to the originating meeting and available source evidence.

Explicit user requirement: Owner entry MUST support both selection from a
dropdown of captured/known names AND manual text entry. Incorrectly captured or
missing names must never prevent assigning a commitment. Manual entry is a normal
workflow, not an error workaround.

Acceptance criteria:

- Choose a captured name from suggestions, or type a different/new name directly.
- Manually enter an owner when no speakers were captured; no speaker record is required.
- Correct a misspelled owner and preserve the exact corrected name across reloads,
  meeting/group views, exports, and next-meeting review.
- Human edits are not silently replaced by later AI analysis or speaker remapping.
- Owner suggestions and manual entry are keyboard accessible, visibly labeled,
  validated at the API boundary, and covered by the existing privacy protections.
- Empty ownership is an intentional Unassigned state. Dates may be unset.
- Completion removes a commitment from open/next-meeting lists without deleting it;
  reopening restores it. Counts reflect the same underlying records.
- Carry-forward references existing commitments rather than duplicating them.
- Existing meetings continue to load without commitment records.

Source: `backend/app/models.py` (`Question`, `SessionSynthesis`),
`backend/app/routers/questions.py`, `frontend/src/components/PostCall/OverviewView.tsx`.
Design exploration: `output/commitments-mock/commitments.html`, when available locally.
The mock's original owner control only allows fixed choices; it must be revised to
support the user's manual-entry requirement before implementation acceptance.

## 2. Link insights to evidence and allow manual transcript corrections

Suggested priority: Normal. Type: Feature.

Problem: Insight source context is presented as text, and transcript updates
currently expose speaker reassignment rather than manual text correction.

Acceptance criteria:

- Show evidence opens and highlights the originating transcript passage when a
  reliable reference exists; unavailable references are explained honestly.
- Users can correct transcript text while preserving the original and a record of
  the correction. User changes survive reloads and are protected from silent overwrite.
- Clearly identify when derived insights/briefings are stale and offer deliberate
  reanalysis without automatically making paid model calls on every edit.
- References remain meaningful or explicitly stale after re-transcription.
- Preserve privacy protections for manual text at storage and provider boundaries.
- Defer click-to-audio seeking until reliable recording offsets are available;
  wall-clock transcription completion times must not masquerade as audio offsets.

Source: `backend/app/routers/transcripts.py`, `backend/app/models.py`,
`frontend/src/components/PostCall/TranscriptReview.tsx`,
`frontend/src/components/ActiveCall/QuestionCard.tsx`.

## 3. Search discussion content across meetings

Suggested priority: Normal. Type: Feature.

Problem: Session search matches names, groups, and dates. Cross-meeting chat
already exists but selects context through a fixed character budget, which can
exclude older relevant evidence.

Acceptance criteria:

- Search saved transcript and insight content with meeting/group scope.
- Results show a matching snippet, originating meeting, and a direct passage link.
- Preserve existing name/group/date discovery and clear empty/error states.
- Bound and paginate results; start with existing database capabilities.
- Retrieve query-relevant evidence for chat within its context budget and retain
  provenance. Do not claim all selected meeting content was included when truncated.
- Follow existing PII handling and session boundaries; do not create an unprotected
  duplicate corpus or send data to an additional provider by default.

Source: `frontend/src/lib/sessionSearch.ts`, `backend/app/routers/chat.py`,
`backend/app/routers/sessions.py`.

## 4. Remove all session recordings when deleting a session

Suggested priority: High. Type: Bug.

Problem: Session deletion removes database records. Startup orphan cleanup only
targets auxiliary microphone/system WAVs; mixed recordings and cleaned playback
copies fall outside that cleanup.

Acceptance criteria:

- Delete the session's mixed, microphone, system, and generated cleaned audio.
- Resolve and validate exact session-owned targets before removing any files;
  unrelated session files and workspace/application roots are never targets.
- Preserve a durable way to retry cleanup after failures or crashes, even when the
  database deletion has committed. Missing files are an idempotent success.
- Refuse or safely coordinate deletion while that session is actively recording.
- Verify the complete artifact lifecycle, including files created by playback caching.
- Add a focused failure/retry and isolation regression check.

Configurable age-based audio retention is a separate follow-up, not required for
this deletion fix.

Source: `backend/app/routers/sessions.py`, `backend/app/services/audio_store.py`,
`backend/app/main.py` (`_cleanup_orphan_audio`).

## 5. Load available session sections when optional requests fail

Suggested priority: High. Type: Bug / resilience.

Problem: `useSession` applies data only after nine requests complete through one
`Promise.all`. One rejection prevents successful results from being applied and
only logs the error to the console.

Acceptance criteria:

- Load essential session metadata independently of optional sections.
- Display successful sections even if another request fails.
- Distinguish failed sections from legitimately empty sections and show a retry.
- Retry only failed requests unless the user explicitly refreshes everything.
- Guard against late responses from a previously selected session, including retries.
- Preserve the distinction between loading, not found, partial success, and failure.
- Add one focused interaction check for mixed success/failure and session switching.

Source: `frontend/src/hooks/useSession.ts` and its consumers in `frontend/src/App.tsx`.

## 6. Bound live-call event retention and rendering work

Suggested priority: High. Type: Performance.

2026-09-11 handoff: ALP-396 covers the rendering work, committed in 6480433 on
`agent/alp-396-live-insight-paging`, reviewed APPROVE, not merged or released.
The user repeatedly reproduced whole-machine sluggishness with All (860+ insights)
and restored responsiveness with a small filter (18 action items). Both insight
and transcript views now mount at most 40 rows; memoized data/rows and reused
timestamp formatters remove repeated work. Full-history transcript search and
history/live navigation remain available. Verification: 236 frontend tests, two
synthetic browser harnesses including 10,000-entry datasets, and production build.

Still open: unbounded WebSocket message retention and real-call validation of the
updated desktop build. The existing message array must not simply be truncated
without changing App's index-based consumption. Do not file the completed
rendering work again as a new issue.

Problem: `useWebSocket` appends and copies every message for the connection lifetime,
even after App processes it. The live view also merges/sorts accumulated records
and renders full transcript/insight lists as a resumed meeting grows.

Acceptance criteria:

- Process messages without retaining an unbounded history of consumed events.
- Preserve message ordering, exactly-once handling within a connection, stop/drain
  completion, and stale-connection guards. Do not simply truncate the array while
  retaining App's index-based consumption scheme.
- Prevent unrelated frequent updates from rebuilding unchanged transcript/insight data.
- Bound the mounted/rendered work for long lists while retaining complete saved
  history, search, navigation, and accessible interaction.
- Exercise repeated stop/resume and long-call workloads; compare browser memory,
  main-thread time, and responsiveness before/after rather than relying on test counts.
- Do not discard captured audio/transcript data to improve performance.

2026-09-10 diagnostic context: A live v0.6.5 session had five segments, about 1,036
transcript entries, and 901 insights. Backend requests responded in 20-470 ms and
transcripts were current. Backchannel used approximately 7-11% of total CPU in
short samples and about 680 MB working set / 1.48 GB private memory, with stable
thread count. Herdr consumed approximately 30-31% of total CPU; around 60 GB of
96 GB RAM was free. These observations identify a frontend growth risk, not proof
that Backchannel alone caused the reported whole-machine slowdown.

An older segment remained marked open from before a reboot. Investigate crash
reconciliation separately; an open database row does not establish a live worker leak.

Source: `frontend/src/hooks/useWebSocket.ts`, `frontend/src/App.tsx`,
`frontend/src/components/ActiveCall/TranscriptPanel.tsx`,
`frontend/src/components/ActiveCall/QuestionList.tsx`.

## 7. Automatically discover frontend tests in the test command

Suggested priority: High; small scope. Type: Developer experience / test coverage.

Problem: The explicit file list in `frontend/package.json` omitted
`src/lib/sessionSearch.test.mjs` and `src/components/PrivacyModeCard.test.mjs`
during the initial review. Those six tests passed separately; the registered
suite passed 219 tests.

Acceptance criteria:

- `npm test` discovers every intended `src/**/*.test.mjs` file automatically.
- New tests run in CI without editing a second registration list.
- Discovery works on supported Windows and Linux environments with the repository's
  Node version and existing test runner; do not add a framework just for discovery.
- Keep generated files, dependencies, and unrelated output directories out of discovery.
- Confirm both previously omitted files are included, and a failing discovered test
  produces a nonzero exit code in the local and CI commands.

Source: `frontend/package.json`, `.github/workflows/tests.yml`.

## Suggested sequencing

File or link all seven issues after checking Linear for existing work. Start with
deletion, partial session loading, and automatic test discovery. Prioritize the
long-call performance work using a measured replay. Tracked commitments are the
next product feature, with manual owner entry included from the first version.

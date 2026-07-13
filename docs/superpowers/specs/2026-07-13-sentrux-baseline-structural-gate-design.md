# ALP-72 Sentrux Baseline and Structural Gate Design

## Goal

Make Sentrux useful as a regression gate again without weakening source-code
constraints or hiding the two generated npm lockfiles that Sentrux 0.5.7 cannot
exclude by path.

## Verified Starting State

The isolated branch starts from `origin/master` at `1bd5f9e`. Sentrux 0.5.7
reports:

- quality signal: 6465
- coupling: 0.09
- cycles: 0
- god files: 1
- complex functions: 27
- `audio_websocket`: CC 51 and 387 lines
- `docs-site/package-lock.json`: 5718 lines
- `frontend/package-lock.json`: 4311 lines

The stored baseline reports quality 6142, coupling 0.54, zero god files, and
eight complex functions. That stale structural state makes `sentrux gate .`
fail on untouched `master`.

The Sentrux 0.5.7 scanner uses `git ls-files` as its primary source, so both
tracked lockfiles are analyzed. Its rules parser accepts per-language settings,
but `check_rules` applies only the global constraints in this release. A JSON
language override therefore cannot create an honest lockfile exception.

## Decisions

### Refactor the WebSocket at existing seams

Keep `audio_websocket` as the FastAPI route and preserve the current protocol,
ordering, database writes, reconnect behavior, and finalization behavior.
Extract three cohesive blocks into module-level helpers in
`backend/app/ws/audio_handler.py`:

1. `async _start_call_segment(session_id: uuid.UUID, is_resume: bool) ->
   SegmentAudioWriter | None` owns call-segment numbering, resume-marker
   creation, session state transition, and audio-writer creation.
2. `async _reconnect_audio_pipeline(websocket: WebSocket, diarizer: Any,
   sys_diarizer: Any | None, transcription_queue: OrderedTranscriptionQueue,
   orchestrator: AgentOrchestrator) -> bool` owns diarizer flushing and reset,
   gateway reconnect, active-status emission, and reconnect failure handling.
3. `_decode_audio_frame(raw_frame: bytes) -> tuple[int, bytes]` owns the
   existing odd-length track-prefix rule and legacy even-length microphone
   fallback.

The route will keep the speaker-resolution and transcript-emission closures
because moving them would require a new state object and broad parameter
plumbing. The three selected extractions are enough to move the route below
both configured thresholds with margin while reducing its cyclomatic
complexity. The frame decoder provides that margin without deleting useful
comments or compressing statements solely to lower the line metric.

### Keep generated lockfiles tracked and keep the 3000-line rule

Do not remove or relocate either package lock. They are generated dependency
manifests used by builds and release workflows.

Do not raise `max_file_lines` above 3000. A higher global limit would allow new
source files to grow solely to silence generated-file findings.

Document the two exact generated-file exceptions beside `max_file_lines` in
`.sentrux/rules.toml`, including their reviewed line counts and the Sentrux
0.5.7 path-exclusion limitation. `sentrux check .` may report only these two
approved exceptions. Any additional file, function-length finding, or CC
finding remains a failure.

Do not add a second file-length checker. The repository has no structural CI
wrapper today, and duplicating Sentrux would create two sources of policy for a
known tool limitation.

### Refresh and identify the baseline

After the refactor and behavior checks pass, run `sentrux gate --save .` from a
clean branch based on the reviewed `origin/master` state. Add these top-level
metadata fields to `.sentrux/baseline.json`:

- `sentrux_version`: `0.5.7`
- `source_revision`: the full refactor commit hash represented by the baseline
- `plugin_versions`: Python 0.2.0, Markdown 0.2.0, TypeScript 0.1.0,
  JavaScript 0.1.0, HTML 0.1.0, JSON 0.1.0, CSS 0.1.0, YAML 0.2.0,
  SQL 0.2.0, PowerShell 0.2.0, TOML 0.1.0, and Dockerfile 0.2.0

Sentrux 0.5.7 ignores unknown JSON fields when loading the baseline. Run
`sentrux gate .` after adding metadata to prove the file remains loadable and
the refreshed state is not degraded. Future intentional `gate --save` runs
must review and restore these metadata fields because the Sentrux serializer
writes only its native metric fields.

Update the Sentrux snapshot in `AGENTS.md` and `CLAUDE.md` to match the saved
metrics and version. Do not claim `sentrux check .` is fully green while the two
documented generated-file exceptions remain.

## Error Handling and Behavior Preservation

The extracted reconnect helper will retain the existing broad reconnect
boundary: it logs an exception and returns `False`, allowing the route to stop
the receive loop and finalize the call. The call-segment helper will retain the
current no-session behavior by returning no audio writer without creating a
segment or resume marker. The frame decoder will preserve both accepted wire
formats: odd frames may carry a one-byte microphone or system track prefix,
while even frames remain legacy microphone PCM.

No new exception swallowing, retry policy, protocol message, database schema,
configuration value, or dependency is introduced.

## Verification

Add focused stdlib `unittest` coverage for the extracted helper behavior before
moving the route code. Then verify:

1. Focused audio-handler tests pass.
2. The complete backend suite passes in the repository's Docker environment.
3. The desktop stdlib suite passes in Docker or an available Python 3.12
   environment.
4. `npm run build` passes in `frontend/`.
5. All docs-site Node tests and `npm run build` pass using the documented
   no-lock install workaround when `npm ci` encounters the existing
   cross-platform optional-dependency drift.
6. `sentrux check .` reports only the two documented lockfile exceptions.
7. `sentrux gate .` passes against the refreshed, versioned baseline.
8. `git diff --check` passes and the worktree contains only intentional files.

## Files in Scope

- `backend/app/ws/audio_handler.py`
- `backend/tests/test_audio_handler.py`
- `.sentrux/rules.toml`
- `.sentrux/baseline.json`
- `AGENTS.md`
- `CLAUDE.md`

## Non-Goals

- Redesigning the live audio pipeline or WebSocket protocol
- Splitting the audio handler into new service classes
- Refactoring unrelated complex functions counted by Sentrux 0.5.7
- Removing npm lockfiles or changing package-manager policy
- Raising structural thresholds to make existing findings disappear
- Adding a new CI workflow or structural-analysis dependency

## Acceptance Mapping

- The audio route no longer violates `max_cc` or `max_fn_lines`.
- The generated lockfiles remain visible as exact, approved exceptions without
  weakening the 3000-line source constraint.
- The baseline represents reviewed current structure and records the tool,
  plugins, and source revision that produced it.
- `sentrux gate .` becomes a meaningful green regression comparison on the
  reviewed branch.
- New feature regressions are not hidden by a broader threshold or stale
  baseline.

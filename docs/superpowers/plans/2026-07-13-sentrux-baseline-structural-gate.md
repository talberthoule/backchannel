# ALP-72 Sentrux Baseline Structural Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sentrux an honest structural regression gate by reducing `audio_websocket` below the existing function limits, recording the two unavoidable generated lockfile exceptions, and refreshing a reproducible baseline.

**Architecture:** Extract three cohesive module-level helpers from the WebSocket route without changing runtime behavior: frame decoding, audio-pipeline reconnection, and call-segment startup. Protect each extraction with focused stdlib `unittest` coverage, retain the existing global source limits, and generate the baseline only after all source and policy changes are verified.

**Tech Stack:** Python 3.11, FastAPI WebSockets, SQLAlchemy async sessions, stdlib `unittest`, Sentrux 0.5.7, PowerShell, Docker, Node.js/npm.

## Global Constraints

- Work only in `.worktrees/alp-72-sentrux` on `agent/alp-72-sentrux`.
- Follow test-driven development for each Python extraction: add one focused failing test, run it and confirm the intended failure, implement the minimum change, then rerun it.
- Preserve the current WebSocket protocol, speaker prefixes, session state transitions, transcript marker text, reconnect status payload, and exception behavior.
- Keep all existing package lockfiles tracked and unchanged.
- Keep `max_file_lines = 3000`; do not weaken `max_cc` or `max_fn_lines`.
- Accept only these Sentrux 0.5.7 check exceptions: `docs-site/package-lock.json` at 5718 lines and `frontend/package-lock.json` at 4311 lines. Any other check finding fails the task.
- Use `apply_patch` for hand edits. Use `sentrux gate --save .` only for the generated native baseline fields.
- Keep new prose and comments ASCII.
- Do not push, merge, tag, deploy, or mutate releases as part of ALP-72.

---

## Task 1: Extract Audio Frame Decoding

**Files:**

- Create: `backend/tests/test_audio_handler.py`.
- Modify: `backend/app/ws/audio_handler.py`.

**Interface:**

- Consume: one raw WebSocket binary frame.
- Produce: `tuple[int, bytes]` containing the selected track and PCM bytes.
- Preserve: even-length legacy frames remain track 0 and unmodified; odd-length frames consume a 0/1 prefix, while an unknown prefix falls back to track 0 and is still stripped.

- [ ] **Step 1: Add the focused failing decoder test**

Create `backend/tests/test_audio_handler.py` with:

```python
import unittest

from app.ws.audio_handler import _decode_audio_frame


class AudioFrameDecodingTests(unittest.TestCase):
    def test_decodes_prefixed_and_legacy_frames(self):
        cases = [
            (b"\x00\x01\x02", (0, b"\x01\x02")),
            (b"\x01\x03\x04", (1, b"\x03\x04")),
            (b"\x07\x05\x06", (0, b"\x05\x06")),
            (b"\x08\x09", (0, b"\x08\x09")),
        ]

        for raw_frame, expected in cases:
            with self.subTest(raw_frame=raw_frame):
                self.assertEqual(expected, _decode_audio_frame(raw_frame))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the intended failure**

From the repository worktree root:

```powershell
$backend = (Resolve-Path backend).Path
$frontend = (Resolve-Path frontend).Path
docker run --rm --mount "type=bind,source=$backend,target=/app" --mount "type=bind,source=$frontend,target=/frontend" -w /app backchannel-backend:latest python -m unittest tests.test_audio_handler.AudioFrameDecodingTests -v
```

Expected: failure while importing `_decode_audio_frame` because it does not exist yet. If the failure is unrelated, fix the test environment before proceeding.

- [ ] **Step 3: Add the decoder and replace the inline branch**

In `backend/app/ws/audio_handler.py`, insert this immediately before `_flush_remaining_audio`:

```python
def _decode_audio_frame(raw_frame: bytes) -> tuple[int, bytes]:
    if len(raw_frame) % 2 == 0:
        return 0, raw_frame
    track = raw_frame[0] if raw_frame[0] in (0, 1) else 0
    return track, raw_frame[1:]
```

Inside `audio_websocket`, replace:

```python
                raw_frame = message["bytes"]
                if len(raw_frame) % 2 == 1:
                    track = raw_frame[0] if raw_frame[0] in (0, 1) else 0
                    pcm_data = raw_frame[1:]
                else:
                    track = 0
                    pcm_data = raw_frame
```

with:

```python
                track, pcm_data = _decode_audio_frame(message["bytes"])
```

- [ ] **Step 4: Rerun the focused test**

Run the command from Step 2.

Expected: `1` test passes.

- [ ] **Step 5: Commit the extraction**

```powershell
git add backend/app/ws/audio_handler.py backend/tests/test_audio_handler.py
git diff --cached --check
git commit -m "refactor: extract audio frame decoding"
```

Expected: commit succeeds and the worktree is clean.

---

## Task 2: Extract Audio-Pipeline Reconnection

**Files:**

- Modify: `backend/tests/test_audio_handler.py`.
- Modify: `backend/app/ws/audio_handler.py`.

**Interface:**

- Consume: WebSocket, microphone diarizer, optional system diarizer, ordered transcription queue, and orchestrator.
- Produce: `True` after a successful gateway reconnect and status message; `False` after a reconnect exception.
- Preserve: flush both diarizers before reconnecting, add `sys_` only to system track speaker IDs, reset each present diarizer, and log reconnect exceptions.

- [ ] **Step 1: Expand the test imports**

Replace the imports at the top of `backend/tests/test_audio_handler.py` with:

```python
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.ws.audio_handler import _decode_audio_frame, _reconnect_audio_pipeline
```

- [ ] **Step 2: Add reconnect success and failure tests**

Append this class before the `if __name__ == "__main__"` block:

```python
class AudioReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_flushes_both_tracks_and_reports_success(self):
        mic_segment = SimpleNamespace(speaker_id="auto_1", pcm_bytes=b"mic")
        system_segment = SimpleNamespace(speaker_id="auto_2", pcm_bytes=b"system")
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        diarizer = MagicMock()
        system_diarizer = MagicMock()
        transcription_queue = MagicMock()
        orchestrator = MagicMock()
        orchestrator._reconnect_gateway = AsyncMock(return_value=True)

        with patch(
            "app.ws.audio_handler.flush_diarizer_segments",
            side_effect=[[mic_segment], [system_segment]],
        ) as flush_segments:
            reconnected = await _reconnect_audio_pipeline(
                websocket,
                diarizer,
                system_diarizer,
                transcription_queue,
                orchestrator,
            )

        self.assertTrue(reconnected)
        flush_segments.assert_has_calls([call(diarizer), call(system_diarizer)])
        self.assertEqual(
            [call("auto_1", b"mic"), call("sys_auto_2", b"system")],
            transcription_queue.add.call_args_list,
        )
        diarizer.reset.assert_called_once_with()
        system_diarizer.reset.assert_called_once_with()
        orchestrator._reconnect_gateway.assert_awaited_once_with()
        websocket.send_json.assert_awaited_once_with(
            {
                "type": "status",
                "data": {
                    "state": "active",
                    "message": "Reconnected to AI",
                },
            }
        )

    async def test_returns_false_when_gateway_reconnect_raises(self):
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        diarizer = MagicMock()
        transcription_queue = MagicMock()
        orchestrator = MagicMock()
        orchestrator._reconnect_gateway = AsyncMock(
            side_effect=RuntimeError("closed")
        )

        with (
            patch(
                "app.ws.audio_handler.flush_diarizer_segments",
                return_value=[],
            ),
            self.assertLogs("app.ws.audio_handler", level="ERROR"),
        ):
            reconnected = await _reconnect_audio_pipeline(
                websocket,
                diarizer,
                None,
                transcription_queue,
                orchestrator,
            )

        self.assertFalse(reconnected)
        diarizer.reset.assert_called_once_with()
        orchestrator._reconnect_gateway.assert_awaited_once_with()
        websocket.send_json.assert_not_awaited()
```

- [ ] **Step 3: Run the reconnect tests and verify the intended failure**

Use the Docker command from Task 1, changing the test selector to `tests.test_audio_handler.AudioReconnectTests`.

Expected: failure while importing `_reconnect_audio_pipeline` because it does not exist yet.

- [ ] **Step 4: Implement the module-level reconnect helper**

Insert this immediately after `_flush_remaining_audio` in `backend/app/ws/audio_handler.py`:

```python
async def _reconnect_audio_pipeline(
    websocket: WebSocket,
    diarizer: Any,
    sys_diarizer: Any | None,
    transcription_queue: OrderedTranscriptionQueue,
    orchestrator: AgentOrchestrator,
) -> bool:
    for seg in await asyncio.to_thread(flush_diarizer_segments, diarizer):
        transcription_queue.add(seg.speaker_id, seg.pcm_bytes)
    diarizer.reset()
    if sys_diarizer is not None:
        for seg in await asyncio.to_thread(flush_diarizer_segments, sys_diarizer):
            transcription_queue.add(f"sys_{seg.speaker_id}", seg.pcm_bytes)
        sys_diarizer.reset()
    try:
        success = await orchestrator._reconnect_gateway()
        if success:
            await websocket.send_json(
                {
                    "type": "status",
                    "data": {
                        "state": "active",
                        "message": "Reconnected to AI",
                    },
                }
            )
        return success
    except Exception as exc:
        logger.error(f"Reconnect failed: {exc}")
        return False
```

- [ ] **Step 5: Remove the nested reconnect function and redirect both call sites**

Delete the entire nested `reconnect_orchestrator` definition inside `audio_websocket`. Replace both occurrences of:

```python
                    if not await reconnect_orchestrator():
```

with:

```python
                    if not await _reconnect_audio_pipeline(websocket, diarizer, sys_diarizer, transcription_queue, orchestrator):
```

Keep each call on one logical line so the route has safe margin below `max_fn_lines`, and do not change the existing failure-status payloads following either call.

- [ ] **Step 6: Run all audio-handler tests**

Use the Task 1 Docker command with selector `tests.test_audio_handler`.

Expected: `3` tests pass.

- [ ] **Step 7: Commit the extraction**

```powershell
git add backend/app/ws/audio_handler.py backend/tests/test_audio_handler.py
git diff --cached --check
git commit -m "refactor: extract audio pipeline reconnect"
```

Expected: commit succeeds and the worktree is clean.

---

## Task 3: Extract Call-Segment Startup

**Files:**

- Modify: `backend/tests/test_audio_handler.py`.
- Modify: `backend/app/ws/audio_handler.py`.

**Interface:**

- Consume: session UUID and resume flag.
- Produce: a configured `SegmentAudioWriter` when the session exists; `None` when it does not.
- Preserve: next segment numbering, resume marker text and sequence, existing `started_at`, active-state transition, cleared `ended_at`, add order, and one commit.

- [ ] **Step 1: Expand the test imports**

Replace the import block at the top of `backend/tests/test_audio_handler.py` with:

```python
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.models import CallSegment, TranscriptEntry
from app.ws.audio_handler import (
    _decode_audio_frame,
    _reconnect_audio_pipeline,
    _start_call_segment,
)
```

- [ ] **Step 2: Add the async-session fake and startup tests**

Insert this fake immediately after the imports:

```python
class FakeSessionContext:
    def __init__(self, session, last_segment_number=None):
        self.session = session
        self.last_segment_number = last_segment_number
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, model, item_id):
        return self.session

    async def execute(self, statement):
        return SimpleNamespace(
            scalar_one_or_none=lambda: self.last_segment_number
        )

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1
```

Append this class before the `if __name__ == "__main__"` block:

```python
class CallSegmentStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_starts_next_segment_and_adds_resume_marker(self):
        session_id = uuid.uuid4()
        original_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session = SimpleNamespace(
            state="completed",
            started_at=original_started_at,
            ended_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db = FakeSessionContext(session, last_segment_number=2)
        writer = MagicMock()

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch(
                "app.ws.audio_handler.SegmentAudioWriter",
                return_value=writer,
            ) as writer_class,
            patch(
                "app.ws.audio_handler.get_next_sequence",
                new=AsyncMock(return_value=41),
            ),
        ):
            result = await _start_call_segment(session_id, is_resume=True)

        self.assertIs(writer, result)
        writer_class.assert_called_once_with(session_id, 3)
        self.assertEqual(2, len(db.added))
        segment, marker = db.added
        self.assertIsInstance(segment, CallSegment)
        self.assertEqual(session_id, segment.session_id)
        self.assertEqual(3, segment.segment_number)
        self.assertIsNotNone(segment.started_at.tzinfo)
        self.assertIsInstance(marker, TranscriptEntry)
        self.assertEqual(session_id, marker.session_id)
        self.assertEqual("--- Session Resumed (Call 3) ---", marker.text)
        self.assertEqual(41, marker.sequence)
        self.assertEqual("active", session.state)
        self.assertEqual(original_started_at, session.started_at)
        self.assertIsNone(session.ended_at)
        self.assertEqual(1, db.commits)

    async def test_returns_none_when_session_does_not_exist(self):
        session_id = uuid.uuid4()
        db = FakeSessionContext(None)

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_handler.SegmentAudioWriter") as writer_class,
        ):
            result = await _start_call_segment(session_id, is_resume=False)

        self.assertIsNone(result)
        writer_class.assert_not_called()
        self.assertEqual([], db.added)
        self.assertEqual(0, db.commits)
```

- [ ] **Step 3: Run the startup tests and verify the intended failure**

Use the Task 1 Docker command with selector `tests.test_audio_handler.CallSegmentStartTests`.

Expected: failure while importing `_start_call_segment` because it does not exist yet.

- [ ] **Step 4: Implement the module-level startup helper**

Insert this after `_reconnect_audio_pipeline` and before `_finalize_call` in `backend/app/ws/audio_handler.py`:

```python
async def _start_call_segment(
    session_id: uuid.UUID,
    is_resume: bool,
) -> SegmentAudioWriter | None:
    async with async_session() as db:
        session = await db.get(Session, session_id)
        if session is None:
            return None

        result = await db.execute(
            select(CallSegment.segment_number)
            .where(CallSegment.session_id == session_id)
            .order_by(CallSegment.segment_number.desc())
            .limit(1)
        )
        last_segment_number = result.scalar_one_or_none()
        segment_number = (last_segment_number or 0) + 1
        segment = CallSegment(
            session_id=session_id,
            segment_number=segment_number,
            started_at=datetime.now(timezone.utc),
        )
        db.add(segment)
        audio_writer = SegmentAudioWriter(session_id, segment_number)

        if is_resume:
            sequence = await get_next_sequence(session_id, db)
            marker = TranscriptEntry(
                session_id=session_id,
                text=f"--- Session Resumed (Call {segment_number}) ---",
                sequence=sequence,
            )
            db.add(marker)

        if session.state in ("pre_call", "completed"):
            session.state = "active"
            if not session.started_at:
                session.started_at = datetime.now(timezone.utc)
            session.ended_at = None

        await db.commit()
        return audio_writer
```

- [ ] **Step 5: Replace inline segment startup**

Inside `audio_websocket`, replace the full `async with async_session() as db` block that creates the segment, writer, resume marker, and session state transition with:

```python
        audio_writer = await _start_call_segment(session_id, is_resume)
```

Keep the existing pre-try initialization `audio_writer: SegmentAudioWriter | None = None` so finalization remains safe if an earlier operation raises.

- [ ] **Step 6: Run the focused and full backend suites**

First run `tests.test_audio_handler` using the Docker command from Task 1.

Expected: `5` tests pass.

Then run:

```powershell
$backend = (Resolve-Path backend).Path
$frontend = (Resolve-Path frontend).Path
docker run --rm --mount "type=bind,source=$backend,target=/app" --mount "type=bind,source=$frontend,target=/frontend" -w /app backchannel-backend:latest python -m unittest discover -s tests
```

Expected: the entire backend suite passes.

- [ ] **Step 7: Prove that only the generated lockfile findings remain**

Run:

```powershell
& "C:/Users/thoule/.local/bin/sentrux.exe" check .
```

Expected: `audio_handler.py` is absent from all findings. The command exits 1 only because `max_file_lines` identifies exactly:

```text
docs-site/package-lock.json (5718 lines)
frontend/package-lock.json (4311 lines)
```

Stop if `max_cc`, `max_fn_lines`, any third file, or any different line count appears.

- [ ] **Step 8: Commit the extraction**

```powershell
git add backend/app/ws/audio_handler.py backend/tests/test_audio_handler.py
git diff --cached --check
git commit -m "refactor: isolate audio session setup"
```

Expected: commit succeeds and the worktree is clean.

---

## Task 4: Record the Generated Lockfile Exception Policy

**Files:**

- Modify: `.sentrux/rules.toml`.

**Interface:**

- Preserve the actual global constraint.
- Explain why the two generated files remain exceptions under Sentrux 0.5.7.
- Make the acceptance boundary exact enough that a third violation or changed lockfile size requires review.

- [ ] **Step 1: Add the policy adjacent to the file-length rule**

Immediately above `max_file_lines = 3000` in `.sentrux/rules.toml`, add:

```toml
# Sentrux 0.5.7 has no per-path max_file_lines exceptions and applies global
# constraints to tracked JSON. The generated lockfiles are approved exceptions:
# docs-site/package-lock.json (5718), frontend/package-lock.json (4311).
# Do not raise this source guard to hide them; any additional finding is debt.
```

Do not alter any constraint value.

- [ ] **Step 2: Re-run and assert the exact exception set**

Run:

```powershell
$output = & "C:/Users/thoule/.local/bin/sentrux.exe" check . 2>&1
$exitCode = $LASTEXITCODE
$text = $output -join [Environment]::NewLine
$expected = @(
  "docs-site/package-lock.json (5718 lines)",
  "frontend/package-lock.json (4311 lines)"
)

if ($exitCode -ne 1) {
  throw "Expected sentrux check to exit 1 for the two approved lockfiles; got $exitCode."
}
foreach ($finding in $expected) {
  if (-not $text.Contains($finding)) {
    throw "Missing approved finding: $finding"
  }
}
foreach ($forbidden in @("max_cc", "max_fn_lines", "audio_handler.py")) {
  if ($text.Contains($forbidden)) {
    throw "Unexpected Sentrux finding: $forbidden"
  }
}
if (($output | Select-String -SimpleMatch "package-lock.json").Count -ne 2) {
  throw "Sentrux reported a lockfile set other than the two approved files."
}
```

Expected: the assertion block completes without throwing.

- [ ] **Step 3: Commit the policy**

```powershell
git add .sentrux/rules.toml
git diff --cached --check
git commit -m "docs: record Sentrux lockfile exceptions"
git rev-parse HEAD
```

Record the 40-character hash printed by the final command. This is the structural source revision to store in the generated baseline.

---

## Task 5: Refresh the Baseline, Documentation, and Verification Evidence

**Files:**

- Modify: `.sentrux/baseline.json`.
- Modify: `AGENTS.md`.
- Modify: `CLAUDE.md`.

**Interface:**

- Generate native baseline metrics from the fully refactored and policy-documented tree.
- Add audit metadata that Sentrux 0.5.7 ignores safely but humans can reproduce.
- Keep both durable documentation files synchronized with the final metrics and known check exceptions.

- [ ] **Step 1: Run all non-Sentrux verification before baselining**

Backend:

```powershell
$backend = (Resolve-Path backend).Path
$frontend = (Resolve-Path frontend).Path
docker run --rm --mount "type=bind,source=$backend,target=/app" --mount "type=bind,source=$frontend,target=/frontend" -w /app backchannel-backend:latest python -m unittest discover -s tests
```

Expected: all backend tests pass, including the five new audio-handler tests.

Desktop:

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
Push-Location desktop
try {
  python -m unittest discover -s tests
} finally {
  Pop-Location
  Remove-Item Env:PYTHONPATH
}
```

Expected: all desktop tests pass.

Frontend:

```powershell
Push-Location frontend
try {
  npm ci
  npm run build
} finally {
  Pop-Location
}
```

Expected: dependency installation and the production build pass without modifying `frontend/package-lock.json`.

Documentation site:

```powershell
Push-Location docs-site
try {
  npm install --package-lock=false
  node --test *.test.js
  npm run build
} finally {
  Pop-Location
}
```

Expected: all documentation-site tests and the build pass. The no-lock install is intentional because the existing package manifest and lockfile drift is already recorded; this task must not rewrite the lock.

Confirm the dependency commands did not create tracked drift:

```powershell
git status --short
```

Expected: clean.

- [ ] **Step 2: Generate a preliminary baseline and read its native metrics**

```powershell
& "C:/Users/thoule/.local/bin/sentrux.exe" gate --save .
Get-Content .sentrux/baseline.json
```

Expected: the baseline is regenerated successfully. Record the exact native `quality_signal`, `coupling_score`, `cycle_count`, `god_file_count`, and `complex_fn_count` values from the generated JSON.

- [ ] **Step 3: Synchronize the durable documentation**

In both `AGENTS.md` and `CLAUDE.md`, replace the stale Sentrux snapshot sentence with the exact metrics generated in Step 2. In the same Sentrux section, add:

```markdown
The baseline records the Sentrux, plugin, and source revisions used to generate it. `sentrux check .` is expected to report only the two approved generated lockfile exceptions documented next to `max_file_lines` in `.sentrux/rules.toml`; any other finding must be fixed before the baseline is refreshed.
```

Keep the two files semantically identical in this section. Use the CLI-displayed quality value, which is `quality_signal` multiplied by 10,000 and rounded to the nearest integer, and preserve coupling to the precision displayed by the CLI.

- [ ] **Step 4: Regenerate the final native baseline after the documentation edit**

```powershell
& "C:/Users/thoule/.local/bin/sentrux.exe" gate --save .
Get-Content .sentrux/baseline.json
```

Expected: the final native metrics match both documentation files. If the Markdown edit changes a metric, update both files to the newly generated value and run this step once more before continuing.

- [ ] **Step 5: Add reproducibility metadata to the generated baseline**

Use `apply_patch` to add these top-level fields to `.sentrux/baseline.json` without changing its native generated fields:

- `sentrux_version`: exactly `"0.5.7"`.
- `source_revision`: exactly the 40-character hash recorded after Task 4.
- `plugin_versions`: exactly:

```json
{
  "python": "0.2.0",
  "markdown": "0.2.0",
  "typescript": "0.1.0",
  "javascript": "0.1.0",
  "html": "0.1.0",
  "json": "0.1.0",
  "css": "0.1.0",
  "yaml": "0.2.0",
  "sql": "0.2.0",
  "powershell": "0.2.0",
  "toml": "0.1.0",
  "dockerfile": "0.2.0"
}
```

Do not invent or infer any version. Preserve valid JSON with a trailing newline.

- [ ] **Step 6: Prove the enriched baseline remains loadable**

```powershell
& "C:/Users/thoule/.local/bin/sentrux.exe" gate .
```

Expected: exit code 0 and no baseline degradation. Then rerun the exact exception assertion block from Task 4 Step 2; it must complete without throwing.

- [ ] **Step 7: Review the final diff against the approved design**

```powershell
git diff --check
git diff --stat
git diff -- backend/app/ws/audio_handler.py backend/tests/test_audio_handler.py
git diff -- .sentrux/rules.toml .sentrux/baseline.json AGENTS.md CLAUDE.md
```

Self-review checklist:

- `audio_websocket` contains no inline frame-prefix branch, nested reconnect helper, or inline call-segment startup block.
- The three extracted signatures match the approved design.
- The route still sends the same reconnect failure messages at both call sites.
- The startup helper returns `None` only for a missing session and otherwise commits once.
- No package lockfile changed.
- No Sentrux threshold changed.
- The baseline metadata names and versions are exact.
- Both durable docs report the final generated metrics and the same exception policy.
- No placeholders, temporary debugging code, or non-ASCII punctuation were added.

- [ ] **Step 8: Commit the baseline and documentation**

```powershell
git add .sentrux/baseline.json AGENTS.md CLAUDE.md
git diff --cached --check
git commit -m "chore: refresh Sentrux structural baseline"
```

- [ ] **Step 9: Run the final clean-tree gate**

```powershell
& "C:/Users/thoule/.local/bin/sentrux.exe" gate .
git status --short
```

Expected: Sentrux gate passes and `git status --short` prints nothing.

- [ ] **Step 10: Update Linear ALP-72 with evidence**

Add one concise Linear comment containing:

- branch name `agent/alp-72-sentrux`;
- the final commit hashes;
- focused and full test results;
- final Sentrux quality/coupling/cycle/god-file/complex-function metrics;
- confirmation that `sentrux gate .` passes;
- confirmation that `sentrux check .` reports only the two documented generated lockfiles;
- confirmation that no lockfile, threshold, release, deploy, or tag mutation occurred.

Do not move ALP-72 to Done until the branch is integrated or the repository's normal review policy says the implementation commit itself is sufficient.

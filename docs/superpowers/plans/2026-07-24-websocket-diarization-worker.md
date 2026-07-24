# WebSocket Diarization Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep live call audio connected and recorded while local diarization or the optional live gateway is slow.

**Architecture:** The WebSocket receive coroutine will persist and enqueue audio without waiting for diarization. One per-call worker will process mic and system frames sequentially, while gateway sends and reconnects remain bounded and non-fatal. Uvicorn buffering, call-segment ownership, and finalization ordering will be hardened around that split.

**Tech Stack:** Python 3, FastAPI/Starlette WebSockets, `asyncio`, Uvicorn 0.34, websockets 14.1, SQLAlchemy, stdlib `unittest`

## Global Constraints

- Continuity and eventual transcript completeness take priority over live transcript latency.
- Use exactly one permanent diarization worker per live call.
- Keep the application backlog in process with `asyncio.Queue`; add no Kafka, Celery, Redis, or dependency.
- Persist mixed, mic, and system audio before optional gateway forwarding.
- Use `ws_ping_timeout=90`, `ws_max_queue=2048`, and `ws_max_size=65536` in all three Uvicorn entry points.
- Bound each live gateway send to one second; gateway failure must not end the call or reset diarizers.
- Preserve global transcription-job insertion order.
- Keep new source edits ASCII.

## File Map

- Modify `backend/app/ws/audio_handler.py`: queue items, worker, gateway isolation, disconnect handling, split recording, exact segment ownership, and shutdown ordering.
- Modify `backend/app/services/agents/orchestrator.py`: make gateway health inspection read-only so the receive loop controls non-blocking recovery.
- Modify `backend/tests/test_audio_handler.py`: focused worker, gateway, disconnect, persistence, and segment-ownership tests.
- Modify `backend/tests/test_orchestrator_context_update.py`: health-check regression test.
- Modify `desktop/launcher.py` and `desktop/tests/test_launcher.py`: packaged desktop Uvicorn settings.
- Modify `backend/scripts/start_backend.py` and `backend/tests/test_start_backend.py`: Docker/source Uvicorn settings and native-script contract test.
- Modify `backend/scripts/setup_windows_gpu.ps1`: native Windows GPU Uvicorn settings.
- Do not create a broker adapter, worker service, migration, frontend component, or dependency.

---

### Task 1: Harden Every Uvicorn Entry Point

**Files:**
- Modify: `desktop/launcher.py:320-328`
- Modify: `desktop/tests/test_launcher.py:284-290`
- Modify: `backend/scripts/start_backend.py:14-21`
- Modify: `backend/scripts/setup_windows_gpu.ps1:56`
- Modify: `backend/tests/test_start_backend.py:20-48`

**Interfaces:**
- Consumes: Uvicorn's existing `ws_ping_timeout`, `ws_max_queue`, and `ws_max_size` configuration.
- Produces: Identical WebSocket protocol limits for packaged desktop, Docker/source, and native Windows GPU starts.

- [ ] **Step 1: Write failing startup assertions**

Update the exact desktop `uvicorn.Config` assertion:

```python
        uvicorn.Config.assert_called_once_with(
            "app.main:app",
            host=launcher.LOOPBACK_HOST,
            port=54321,
            log_config=None,
            headers=[(launcher.INSTANCE_HEADER, "ours")],
            ws_ping_timeout=90.0,
            ws_max_queue=2048,
            ws_max_size=65_536,
        )
```

In `backend/tests/test_start_backend.py`, define the shared expected command and use it in both tests:

```python
EXPECTED_COMMAND = [
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--ws-ping-timeout",
    "90",
    "--ws-max-queue",
    "2048",
    "--ws-max-size",
    "65536",
]
```

Replace the first test's expected argument list with `EXPECTED_COMMAND`, keep
the reload assertion as `EXPECTED_COMMAND + ["--reload"]`, and add:

```python
        execvp.assert_called_once_with(
            "uvicorn",
            EXPECTED_COMMAND + ["--reload"],
        )

    def test_native_gpu_start_uses_same_websocket_limits(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "setup_windows_gpu.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("--ws-ping-timeout 90", script)
        self.assertIn("--ws-max-queue 2048", script)
        self.assertIn("--ws-max-size 65536", script)
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_start_backend
Set-Location ..\desktop
python -m unittest tests.test_launcher.LauncherHelperTests.test_run_starts_on_reserved_socket
```

Expected: both suites fail because the three WebSocket settings are absent.

- [ ] **Step 3: Add the exact protocol settings**

Add these keyword arguments to `desktop/launcher.py`:

```python
            ws_ping_timeout=90.0,
            ws_max_queue=2048,
            ws_max_size=65_536,
```

Extend `backend/scripts/start_backend.py` immediately after the port:

```python
        "--ws-ping-timeout",
        "90",
        "--ws-max-queue",
        "2048",
        "--ws-max-size",
        "65536",
```

Replace the native script's Uvicorn invocation with:

```powershell
& $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-timeout 90 --ws-max-queue 2048 --ws-max-size 65536
```

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_start_backend
Set-Location ..\desktop
python -m unittest tests.test_launcher.LauncherHelperTests.test_run_starts_on_reserved_socket
```

Expected: all focused startup tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/scripts/start_backend.py backend/scripts/setup_windows_gpu.ps1 backend/tests/test_start_backend.py desktop/launcher.py desktop/tests/test_launcher.py
git commit -m "fix: harden websocket transport limits"
```

---

### Task 2: Align Recording From Call Start and Own the Exact Segment

**Files:**
- Modify: `backend/app/ws/audio_handler.py:333-450`
- Modify: `backend/app/ws/audio_handler.py:453-582`
- Modify: `backend/tests/test_audio_handler.py:20-46`
- Modify: `backend/tests/test_audio_handler.py:550-739`

**Interfaces:**
- Consumes: `TrackMixer.add()` returning `(mixed, mic, system)` with silence for an absent track.
- Produces: `_start_call_segment(session_id) -> tuple[uuid.UUID, dict[str, SegmentAudioWriter | None]] | None`.
- Produces: `_finalize_call` with a `call_segment_id: uuid.UUID | None = None` keyword that only closes its owned segment.

- [ ] **Step 1: Change persistence and start-segment tests first**

Replace the mic-only persistence test with:

```python
    def test_pre_split_frames_write_all_aligned_files(self):
        writers = {
            "mixed": MagicMock(),
            "mic": MagicMock(),
            "system": MagicMock(),
        }

        audio_handler._append_audio_frames(
            writers,
            (b"mixed", b"mic", b"\x00" * len(b"system")),
            split_track_established=False,
        )

        writers["mixed"].append.assert_called_once_with(b"mixed")
        writers["mic"].append.assert_called_once_with(b"mic")
        writers["system"].append.assert_called_once_with(b"\x00" * len(b"system"))
```

Delete `test_establishing_split_backfills_aligned_track_prefixes`.

Update `test_starts_next_segment_and_adds_resume_marker` to unpack and verify
the returned segment identity:

```python
        segment_id, result_writers = result
        self.assertEqual(db.added[0].id, segment_id)
        self.assertEqual(
            {"mixed": writers[0], "mic": writers[1], "system": writers[2]},
            result_writers,
        )
```

- [ ] **Step 2: Add a stale-finalizer regression test**

Extend `FakeSessionContext` with `call_segment` and queued execute results:

```python
    def __init__(
        self,
        session,
        last_segment_number=None,
        insight_total=0,
        call_segment=None,
        execute_results=None,
    ):
        self.session = session
        self.last_segment_number = last_segment_number
        self.insight_total = insight_total
        self.call_segment = call_segment
        self._execute_results = list(
            execute_results
            if execute_results is not None
            else [last_segment_number]
        )
        self.added = []
        self.commits = 0

    async def get(self, model, item_id):
        if model is CallSegment:
            if self.call_segment and self.call_segment.id == item_id:
                return self.call_segment
            return None
        return self.session

    async def execute(self, statement):
        value = self._execute_results.pop(0) if self._execute_results else None
        return SimpleNamespace(scalar_one_or_none=lambda: value)
```

Add this test to `FinalizeCallDrainModeTests`:

```python
    async def test_stale_finalizer_does_not_complete_resumed_session(self):
        session_id = uuid.uuid4()
        owned_id = uuid.uuid4()
        newer_id = uuid.uuid4()
        owned = SimpleNamespace(
            id=owned_id,
            ended_at=None,
            audio_path=None,
            mic_audio_path=None,
            system_audio_path=None,
        )
        session = SimpleNamespace(state="active", ended_at=None)
        db = FakeSessionContext(
            session,
            call_segment=owned,
            execute_results=[newer_id],
        )
        orchestrator = self._make_orchestrator(briefing=False)
        websocket = MagicMock(send_json=AsyncMock())
        transcription_queue = MagicMock(
            drain=AsyncMock(),
            stats={"jobs": 0, "emitted": 0, "failed": 0},
        )

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_handler.flush_diarizer_segments", return_value=[]),
        ):
            await audio_handler._finalize_call(
                session_id,
                websocket,
                MagicMock(),
                orchestrator,
                transcription_queue,
                call_segment_id=owned_id,
                drain_mode="minimal",
            )

        self.assertIsNotNone(owned.ended_at)
        self.assertEqual("active", session.state)
        self.assertIsNone(session.ended_at)
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler.CallSegmentStartTests tests.test_audio_handler.SegmentAudioPersistenceTests tests.test_audio_handler.FinalizeCallDrainModeTests
```

Expected: failures show split writers are skipped, the start helper returns only
the writer dictionary, and `_finalize_call` does not accept `call_segment_id`.

- [ ] **Step 4: Implement aligned writes and exact ownership**

In `_append_audio_frames`, remove the split-state skip so the loop is:

```python
    for track, pcm in zip(("mixed", "mic", "system"), frames):
        writer = audio_writers[track]
        if not writer:
            continue
        try:
            writer.append(pcm)
        except Exception as exc:
            logger.warning("Disabling %s segment audio persistence: %s", track, exc)
            try:
                failed_path = writer.close()
                if isinstance(failed_path, str):
                    (data_dir() / failed_path).unlink(missing_ok=True)
            except Exception:
                pass
            audio_writers[track] = None
```

Delete `_establish_split_audio_persistence` and both of its call sites. Keep
split-state updates, but do no mixed-WAV readback.

Assign the segment ID explicitly and return it:

```python
        segment_id = uuid.uuid4()
        segment = CallSegment(
            id=segment_id,
            session_id=session_id,
            segment_number=segment_number,
            started_at=datetime.now(timezone.utc),
        )
```

```python
        await db.commit()
        return segment_id, audio_writers
```

Add the optional ID to `_finalize_call`:

```python
    call_segment_id: uuid.UUID | None = None,
```

Replace the latest-open-segment lookup and session completion block with:

```python
    async with async_session() as db:
        owned_segment = (
            await db.get(CallSegment, call_segment_id)
            if call_segment_id is not None
            else None
        )
        if owned_segment and owned_segment.ended_at is None:
            owned_segment.ended_at = datetime.now(timezone.utc)
            if audio_writers:
                try:
                    for field, path in _close_audio_writers(
                        audio_writers,
                        split_track_established,
                    ).items():
                        setattr(owned_segment, field, path)
                except Exception as exc:
                    logger.warning("Failed to finalize segment audio: %s", exc)

        newer_open_segment_id = None
        if call_segment_id is not None:
            result = await db.execute(
                select(CallSegment.id)
                .where(
                    CallSegment.session_id == session_id,
                    CallSegment.ended_at.is_(None),
                    CallSegment.id != call_segment_id,
                )
                .limit(1)
            )
            newer_open_segment_id = result.scalar_one_or_none()

        session = await db.get(Session, session_id)
        if (
            session
            and session.state == "active"
            and newer_open_segment_id is None
        ):
            session.state = "completed"
            session.ended_at = datetime.now(timezone.utc)
        await db.commit()
```

Wire the new return type immediately so this commit remains runnable. Initialize
the owned ID beside `audio_writers`:

```python
    call_segment_id: uuid.UUID | None = None
    audio_writers: dict[str, SegmentAudioWriter | None] | None = None
```

Replace the call-segment start with:

```python
        segment_start = await _start_call_segment(session_id)
        if segment_start is not None:
            call_segment_id, audio_writers = segment_start
```

Pass `call_segment_id=call_segment_id` to the existing `_finalize_call` call.

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler.CallSegmentStartTests tests.test_audio_handler.SegmentAudioPersistenceTests tests.test_audio_handler.FinalizeCallDrainModeTests
```

Expected: all focused lifecycle and persistence tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/ws/audio_handler.py backend/tests/test_audio_handler.py
git commit -m "fix: preserve call segment ownership"
```

---

### Task 3: Add the Single Ordered Diarization Worker

**Files:**
- Modify: `backend/app/ws/audio_handler.py:1-50`
- Modify: `backend/app/ws/audio_handler.py:188-240`
- Modify: `backend/tests/test_audio_handler.py`

**Interfaces:**
- Produces: immutable `_QueuedAudioFrame(track, pcm_bytes, split_track_established, enqueued_at)`.
- Produces: `_run_diarization_worker(queue, mic_diarizer, create_system_diarizer, on_segment, on_error, on_item_done=None) -> system_diarizer | None`.
- Consumes: a `None` queue item as the stop sentinel.

- [ ] **Step 1: Add worker-order and slow-consumer tests**

Add `threading` to the test imports and create:

```python
class DiarizationWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_worker_does_not_block_producer_enqueue(self):
        started = threading.Event()
        release = threading.Event()

        class SlowDiarizer:
            def feed_audio(self, pcm_bytes):
                started.set()
                release.wait(timeout=2)
                return []

        queue = asyncio.Queue()
        worker = asyncio.create_task(
            audio_handler._run_diarization_worker(
                queue,
                SlowDiarizer(),
                MagicMock(),
                AsyncMock(),
                AsyncMock(),
            )
        )
        queue.put_nowait(
            audio_handler._QueuedAudioFrame(0, b"first", False, monotonic())
        )
        self.assertTrue(await asyncio.to_thread(started.wait, 1))

        queue.put_nowait(
            audio_handler._QueuedAudioFrame(0, b"second", False, monotonic())
        )
        self.assertEqual(1, queue.qsize())

        release.set()
        queue.put_nowait(None)
        await worker

    async def test_worker_preserves_arrival_and_split_state(self):
        events = []

        class EchoDiarizer:
            def __init__(self, prefix):
                self.prefix = prefix

            def feed_audio(self, pcm_bytes):
                return [
                    SimpleNamespace(
                        speaker_id=f"{self.prefix}_{pcm_bytes.decode()}",
                        pcm_bytes=pcm_bytes,
                    )
                ]

        async def on_segment(item, segment):
            events.append(
                (
                    item.track,
                    item.pcm_bytes,
                    item.split_track_established,
                    segment.speaker_id,
                )
            )

        mic = EchoDiarizer("mic")
        system = EchoDiarizer("sys")
        create_system = MagicMock(return_value=system)
        queue = asyncio.Queue()
        worker = asyncio.create_task(
            audio_handler._run_diarization_worker(
                queue,
                mic,
                create_system,
                on_segment,
                AsyncMock(),
            )
        )
        queue.put_nowait(audio_handler._QueuedAudioFrame(0, b"a", False, 1.0))
        queue.put_nowait(audio_handler._QueuedAudioFrame(1, b"b", True, 2.0))
        queue.put_nowait(audio_handler._QueuedAudioFrame(0, b"c", True, 3.0))
        queue.put_nowait(None)

        returned_system = await worker

        self.assertIs(system, returned_system)
        create_system.assert_called_once_with()
        self.assertEqual(
            [
                (0, b"a", False, "mic_a"),
                (1, b"b", True, "sys_b"),
                (0, b"c", True, "mic_c"),
            ],
            events,
        )

    async def test_item_failure_reports_and_continues(self):
        class FlakyDiarizer:
            def feed_audio(self, pcm_bytes):
                if pcm_bytes == b"bad":
                    raise RuntimeError("inference failed")
                return [SimpleNamespace(speaker_id="auto_1", pcm_bytes=pcm_bytes)]

        handled = []
        errors = []

        async def on_segment(item, segment):
            handled.append(segment.pcm_bytes)

        async def on_error(item, exc):
            errors.append((item.pcm_bytes, str(exc)))

        queue = asyncio.Queue()
        worker = asyncio.create_task(
            audio_handler._run_diarization_worker(
                queue,
                FlakyDiarizer(),
                MagicMock(),
                on_segment,
                on_error,
            )
        )
        queue.put_nowait(audio_handler._QueuedAudioFrame(0, b"bad", False, 1.0))
        queue.put_nowait(audio_handler._QueuedAudioFrame(0, b"good", False, 2.0))
        queue.put_nowait(None)
        await worker

        self.assertEqual([(b"bad", "inference failed")], errors)
        self.assertEqual([b"good"], handled)
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler.DiarizationWorkerTests
```

Expected: errors report missing `_QueuedAudioFrame` and
`_run_diarization_worker`.

- [ ] **Step 3: Implement the minimal worker**

Add imports:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
```

Add beside the audio constants:

```python
@dataclass(frozen=True)
class _QueuedAudioFrame:
    track: int
    pcm_bytes: bytes
    split_track_established: bool
    enqueued_at: float
```

Add the worker near the existing diarizer helpers:

```python
async def _run_diarization_worker(
    queue: asyncio.Queue[_QueuedAudioFrame | None],
    mic_diarizer: Any,
    create_system_diarizer: Callable[[], Any],
    on_segment: Callable[[_QueuedAudioFrame, Any], Awaitable[None]],
    on_error: Callable[[_QueuedAudioFrame, Exception], Awaitable[None]],
    on_item_done: Callable[[_QueuedAudioFrame], None] | None = None,
) -> Any | None:
    system_diarizer = None
    while True:
        item = await queue.get()
        if item is None:
            return system_diarizer
        try:
            diarizer = mic_diarizer
            if item.track == 1:
                if system_diarizer is None:
                    system_diarizer = create_system_diarizer()
                diarizer = system_diarizer
            segments = await asyncio.to_thread(diarizer.feed_audio, item.pcm_bytes)
            for segment in segments:
                await on_segment(item, segment)
            item_age = max(0.0, monotonic() - item.enqueued_at)
            if item_age >= 5.0 or queue.qsize() >= 50:
                logger.info(
                    "Diarization backlog: remaining=%s item_age=%.1fs track=%s",
                    queue.qsize(),
                    item_age,
                    item.track,
                )
        except Exception as exc:
            logger.warning(
                "Diarization failed for queued track %s: %s",
                item.track,
                exc,
            )
            try:
                await on_error(item, exc)
            except Exception:
                logger.warning("Diarization error callback failed", exc_info=True)
        finally:
            if on_item_done is not None:
                on_item_done(item)
```

- [ ] **Step 4: Run worker and existing audio tests**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler.DiarizationWorkerTests tests.test_audio_handler.AudioFrameDecodingTests tests.test_audio_handler.AudioFlowAccountingTests
```

Expected: all worker, frame, and accounting tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/ws/audio_handler.py backend/tests/test_audio_handler.py
git commit -m "feat: add ordered diarization worker"
```

---

### Task 4: Isolate Gateway Recovery and Raw Disconnect Handling

**Files:**
- Modify: `backend/app/ws/audio_handler.py:1-50`
- Modify: `backend/app/ws/audio_handler.py:212-245`
- Modify: `backend/app/ws/audio_handler.py:847-964`
- Modify: `backend/app/services/agents/orchestrator.py:355-384`
- Modify: `backend/tests/test_audio_handler.py:150-235`
- Modify: `backend/tests/test_orchestrator_context_update.py`

**Interfaces:**
- Produces: `_receive_websocket_message(websocket, session_id) -> dict | None`.
- Produces: `_send_gateway_audio(orchestrator, pcm_data) -> bool`.
- Produces: `_reconnect_audio_gateway(websocket, orchestrator) -> bool`.
- Changes: `AgentOrchestrator.check_health()` reports health but never reconnects.

- [ ] **Step 1: Replace reconnect tests with gateway-only behavior**

Replace `AudioReconnectTests` with:

```python
class AudioGatewayIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_helper_only_reconnects_gateway(self):
        websocket = MagicMock(send_json=AsyncMock())
        orchestrator = MagicMock()
        orchestrator._reconnect_gateway = AsyncMock(return_value=True)

        reconnected = await audio_handler._reconnect_audio_gateway(
            websocket,
            orchestrator,
        )

        self.assertTrue(reconnected)
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

    async def test_gateway_send_timeout_is_nonfatal(self):
        never = asyncio.Event()
        orchestrator = MagicMock()
        orchestrator.send_audio = AsyncMock(side_effect=never.wait)

        with patch.object(
            audio_handler,
            "_GATEWAY_SEND_TIMEOUT_SECONDS",
            0.01,
        ):
            sent = await audio_handler._send_gateway_audio(
                orchestrator,
                b"audio",
            )

        self.assertFalse(sent)

    async def test_failed_reconnect_returns_false(self):
        websocket = MagicMock(send_json=AsyncMock())
        orchestrator = MagicMock()
        orchestrator._reconnect_gateway = AsyncMock(return_value=False)

        reconnected = await audio_handler._reconnect_audio_gateway(
            websocket,
            orchestrator,
        )

        self.assertFalse(reconnected)
        websocket.send_json.assert_not_awaited()
```

Add raw receive coverage:

```python
class WebSocketDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_disconnect_logs_details_and_reads_once(self):
        websocket = MagicMock()
        websocket.receive = AsyncMock(
            side_effect=[
                {
                    "type": "websocket.disconnect",
                    "code": 1011,
                    "reason": "keepalive ping timeout",
                },
                RuntimeError("second receive must not happen"),
            ]
        )
        session_id = uuid.uuid4()

        with self.assertLogs("app.ws.audio_handler", level="INFO") as logs:
            message = await audio_handler._receive_websocket_message(
                websocket,
                session_id,
            )

        self.assertIsNone(message)
        self.assertEqual(1, websocket.receive.await_count)
        self.assertIn("code=1011", "\n".join(logs.output))
        self.assertIn("keepalive ping timeout", "\n".join(logs.output))
```

- [ ] **Step 2: Add an orchestrator health test**

Add `import asyncio` to `backend/tests/test_orchestrator_context_update.py`,
then add this method to `UpdateMeetingContextTests`:

```python
    async def test_gateway_health_check_does_not_reconnect_inline(self):
        orchestrator = object.__new__(AgentOrchestrator)

        async def fail_gateway():
            raise RuntimeError("gateway ended")

        task = asyncio.create_task(fail_gateway())
        with self.assertRaises(RuntimeError):
            await task
        orchestrator._gateway_task = task
        orchestrator._reconnect_gateway = AsyncMock()

        healthy = await orchestrator.check_health()

        self.assertFalse(healthy)
        orchestrator._reconnect_gateway.assert_not_awaited()
```

- [ ] **Step 3: Run the tests and verify failure**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler.AudioGatewayIsolationTests tests.test_audio_handler.WebSocketDisconnectTests tests.test_orchestrator_context_update
```

Expected: missing helper failures and an assertion that `check_health()` still
reconnects inline.

- [ ] **Step 4: Implement bounded send, gateway-only reconnect, and raw receive**

Remove `WebSocketDisconnect` from the FastAPI import and add constants:

```python
_GATEWAY_SEND_TIMEOUT_SECONDS = 1.0
_GATEWAY_RETRY_SECONDS = 5.0
```

Add:

```python
async def _receive_websocket_message(
    websocket: WebSocket,
    session_id: uuid.UUID,
) -> dict | None:
    message = await websocket.receive()
    if message.get("type") != "websocket.disconnect":
        return message
    logger.info(
        "Browser disconnected for session %s: code=%s reason=%s",
        session_id,
        message.get("code"),
        message.get("reason", ""),
    )
    return None


async def _send_gateway_audio(
    orchestrator: AgentOrchestrator,
    pcm_data: bytes,
) -> bool:
    try:
        await asyncio.wait_for(
            orchestrator.send_audio(pcm_data),
            timeout=_GATEWAY_SEND_TIMEOUT_SECONDS,
        )
        return True
    except Exception as exc:
        logger.warning("Audio gateway send failed: %s", exc)
        return False


async def _reconnect_audio_gateway(
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
) -> bool:
    try:
        success = await orchestrator._reconnect_gateway()
        if success:
            await _send_status(websocket, "active", "Reconnected to AI")
        return success
    except Exception as exc:
        logger.error("Audio Gateway reconnect failed: %s", exc)
        return False
```

Delete `_reconnect_audio_pipeline`.

Change `AgentOrchestrator.check_health` to inspection only:

```python
    async def check_health(self) -> bool:
        if self._gateway_task and self._gateway_task.done():
            exc = (
                self._gateway_task.exception()
                if not self._gateway_task.cancelled()
                else None
            )
            if exc:
                logger.warning("Audio Gateway died: %s", exc)
            else:
                logger.warning("Audio Gateway ended")
            return False
        return True
```

Wire the helpers in the current loop so this commit remains runnable:

```python
            message = await _receive_websocket_message(websocket, session_id)
            if message is None:
                break
```

```python
                        await _send_gateway_audio(orchestrator, mixed)
```

Replace the old frame-error reconnect block with:

```python
                except Exception as exc:
                    logger.exception("Audio frame handling failed")
                    await _send_status(
                        websocket,
                        "audio_error",
                        f"One audio frame could not be processed: {exc}",
                        details={"track": track},
                    )
                    continue
```

Replace the health block with a non-fatal gateway-only reconnect:

```python
            if not await orchestrator.check_health():
                await _reconnect_audio_gateway(websocket, orchestrator)
```

Task 5 moves that reconnect await out of the receive path; this task first
removes all diarizer mutation and call termination from gateway recovery.

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler.AudioGatewayIsolationTests tests.test_audio_handler.WebSocketDisconnectTests tests.test_orchestrator_context_update
```

Expected: all gateway and disconnect tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/ws/audio_handler.py backend/app/services/agents/orchestrator.py backend/tests/test_audio_handler.py backend/tests/test_orchestrator_context_update.py
git commit -m "fix: isolate optional audio gateway"
```

---

### Task 5: Wire the Worker Into the Live WebSocket and Drain It First

**Files:**
- Modify: `backend/app/ws/audio_handler.py:597-979`
- Modify: `backend/tests/test_audio_handler.py`

**Interfaces:**
- Consumes: `_QueuedAudioFrame`, `_run_diarization_worker`, `_send_gateway_audio`, `_reconnect_audio_gateway`, and exact call-segment identity from Tasks 2-4.
- Produces: receive-loop behavior that persists and enqueues without awaiting diarization.
- Produces: `_stop_diarization_worker(websocket, queue, worker_task, pending_enqueued_at) -> system_diarizer | None`.

- [ ] **Step 1: Add a sentinel-drain progress test**

Add:

```python
class DiarizationWorkerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_waits_for_sentinel_and_reports_backlog(self):
        queue = asyncio.Queue()
        pending = deque([monotonic() - 10])
        websocket = MagicMock(send_json=AsyncMock())
        finished = asyncio.Event()

        async def slow_worker():
            await asyncio.sleep(0.03)
            pending.popleft()
            finished.set()
            return "system-diarizer"

        task = asyncio.create_task(slow_worker())

        with patch.object(
            audio_handler,
            "_DIARIZATION_DRAIN_STATUS_SECONDS",
            0.01,
        ):
            result = await audio_handler._stop_diarization_worker(
                websocket,
                queue,
                task,
                pending,
            )

        self.assertTrue(finished.is_set())
        self.assertEqual("system-diarizer", result)
        self.assertIsNone(queue.get_nowait())
        statuses = [
            call.args[0]["data"]
            for call in websocket.send_json.await_args_list
        ]
        self.assertTrue(
            any(status["state"] == "post_processing" for status in statuses)
        )
```

Add `from collections import deque` to the test imports.

- [ ] **Step 2: Run the shutdown test and verify failure**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler.DiarizationWorkerShutdownTests
```

Expected: missing `_stop_diarization_worker` and drain interval constant.

- [ ] **Step 3: Add the drain helper**

Add `from collections import deque` to `audio_handler.py`, then define:

```python
_DIARIZATION_DRAIN_STATUS_SECONDS = 5.0
```

```python
async def _stop_diarization_worker(
    websocket: WebSocket,
    queue: asyncio.Queue[_QueuedAudioFrame | None],
    worker_task: asyncio.Task,
    pending_enqueued_at: deque[float],
) -> Any | None:
    queue.put_nowait(None)
    while not worker_task.done():
        done, _ = await asyncio.wait(
            {worker_task},
            timeout=_DIARIZATION_DRAIN_STATUS_SECONDS,
        )
        if done:
            break
        oldest_age = (
            max(0.0, monotonic() - pending_enqueued_at[0])
            if pending_enqueued_at
            else 0.0
        )
        details = {
            "remaining_frames": len(pending_enqueued_at),
            "oldest_age_seconds": round(oldest_age, 1),
        }
        logger.info(
            "Draining diarization backlog: remaining=%s oldest_age=%.1fs",
            details["remaining_frames"],
            oldest_age,
        )
        await _send_status(
            websocket,
            "post_processing",
            "Finishing queued audio before transcription...",
            details=details,
        )
    return await worker_task
```

- [ ] **Step 4: Create the worker callbacks and task**

After `OrderedTranscriptionQueue` construction, add:

```python
    diarization_queue: asyncio.Queue[_QueuedAudioFrame | None] = asyncio.Queue()
    pending_enqueued_at: deque[float] = deque()

    def _create_system_diarizer():
        return create_diarizer(
            runtime_config.effective_live_diarizer,
            registry=_new_speaker_registry(
                runtime_config.speaker_similarity_threshold
            ),
        )

    async def _on_diarized_segment(item: _QueuedAudioFrame, segment: Any):
        speaker_auto_id = (
            f"sys_{segment.speaker_id}"
            if item.track == 1
            else segment.speaker_id
        )
        logger.info(
            "Diarized segment: speaker=%s bytes=%s",
            speaker_auto_id,
            len(segment.pcm_bytes),
        )
        await _send_status(
            websocket,
            "audio_segment",
            (
                f"Queued {len(segment.pcm_bytes) // _PCM_BYTES_PER_SECOND}s "
                "speech segment for transcription"
            ),
            details={
                "speaker_auto_id": speaker_auto_id,
                "bytes": len(segment.pcm_bytes),
            },
        )
        transcription_queue.add(
            _queued_speaker_auto_id(
                speaker_auto_id,
                item.track,
                item.split_track_established,
            ),
            segment.pcm_bytes,
        )

    async def _on_diarization_error(
        item: _QueuedAudioFrame,
        exc: Exception,
    ):
        await _send_status(
            websocket,
            "transcription_error",
            f"Local speaker processing failed for one audio frame: {exc}",
            details={"track": item.track},
        )

    def _on_diarization_item_done(item: _QueuedAudioFrame):
        if pending_enqueued_at:
            pending_enqueued_at.popleft()

    diarization_worker = asyncio.create_task(
        _run_diarization_worker(
            diarization_queue,
            diarizer,
            _create_system_diarizer,
            _on_diarized_segment,
            _on_diarization_error,
            _on_diarization_item_done,
        )
    )
```

- [ ] **Step 5: Replace inline diarization with enqueueing**

At the start of each binary-frame branch, keep ingress accounting but defer the
status send:

```python
                    audio_chunks_received += 1
                    audio_bytes_received += len(pcm_data)
                    now = monotonic()
                    audio_status_due = now - last_audio_status_at >= 5
                    if audio_status_due:
                        last_audio_status_at = now
```

After mixed audio is persisted, capture state and enqueue:

```python
                    split_track_established = (
                        _split_track_established_after_frame(
                            track,
                            split_track_established,
                        )
                    )
                    enqueued_at = monotonic()
                    pending_enqueued_at.append(enqueued_at)
                    diarization_queue.put_nowait(
                        _QueuedAudioFrame(
                            track=track,
                            pcm_bytes=pcm_data,
                            split_track_established=split_track_established,
                            enqueued_at=enqueued_at,
                        )
                    )
                    audio_flow = _record_audio_flow(
                        audio_bytes_by_track,
                        track,
                        len(pcm_data),
                    )
                    if audio_flow:
                        mic_seconds, system_seconds = audio_flow
                        logger.info(
                            (
                                "Audio ingress: mic=%.1fs system=%.1fs "
                                "aggregate_track_seconds=%.1fs backlog=%s"
                            ),
                            mic_seconds,
                            system_seconds,
                            mic_seconds + system_seconds,
                            len(pending_enqueued_at),
                        )
                    if audio_status_due:
                        await _send_status(
                            websocket,
                            "audio_received",
                            (
                                f"Backend received "
                                f"{audio_bytes_received // _PCM_BYTES_PER_SECOND}s "
                                f"audio ({audio_chunks_received} chunks)"
                            ),
                            details={
                                "chunks": audio_chunks_received,
                                "bytes": audio_bytes_received,
                                "seconds": (
                                    audio_bytes_received
                                    / _PCM_BYTES_PER_SECOND
                                ),
                            },
                        )
```

Delete the receive-loop calls to `create_diarizer`,
`asyncio.to_thread(diarizer.feed_audio, pcm_data)`, segment iteration, and
direct `transcription_queue.add`. Delete the old pre-persistence
`audio_received` status block so the status is sent only after persistence and
enqueue.

- [ ] **Step 6: Make gateway recovery non-blocking in the receive loop**

Initialize before the main `try`:

```python
    gateway_available = True
    gateway_reconnect_task: asyncio.Task | None = None
    gateway_retry_at = 0.0
```

Track the bounded gateway send result from Task 4:

```python
                        if gateway_available:
                            gateway_available = await _send_gateway_audio(
                                orchestrator,
                                mixed,
                            )
```

After each message, inspect health and schedule one reconnect:

```python
            if gateway_reconnect_task and gateway_reconnect_task.done():
                try:
                    gateway_available = bool(gateway_reconnect_task.result())
                except Exception as exc:
                    logger.warning("Audio gateway reconnect task failed: %s", exc)
                    gateway_available = False
                gateway_reconnect_task = None
                gateway_retry_at = monotonic() + _GATEWAY_RETRY_SECONDS

            if gateway_available and not await orchestrator.check_health():
                gateway_available = False

            if (
                not gateway_available
                and gateway_reconnect_task is None
                and monotonic() >= gateway_retry_at
            ):
                gateway_reconnect_task = asyncio.create_task(
                    _reconnect_audio_gateway(websocket, orchestrator)
                )
```

Remove Task 4's inline health reconnect block after adding the background
reconnect state machine. Keep its raw receive helper and frame-error block
unchanged.

- [ ] **Step 7: Drain the worker before the existing owned-segment finalization**

At the start of `finally`, cancel any in-flight reconnect and stop the worker:

```python
        if gateway_reconnect_task and not gateway_reconnect_task.done():
            gateway_reconnect_task.cancel()
            await asyncio.gather(
                gateway_reconnect_task,
                return_exceptions=True,
            )

        sys_diarizer = None
        try:
            sys_diarizer = await _stop_diarization_worker(
                websocket,
                diarization_queue,
                diarization_worker,
                pending_enqueued_at,
            )
        except Exception:
            logger.exception("Diarization worker failed during shutdown")
```

Then call finalization with:

```python
        await _finalize_call(
            session_id,
            websocket,
            diarizer,
            orchestrator,
            transcription_queue,
            call_segment_id=call_segment_id,
            audio_writers=audio_writers,
            sys_diarizer=sys_diarizer,
            split_track_established=split_track_established,
            drain_mode=stop_drain_mode if stopped else "minimal",
        )
```

- [ ] **Step 8: Run focused audio tests**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_audio_handler tests.test_ordered_transcription tests.test_track_mixer tests.test_audio_store
```

Expected: all focused audio-path tests pass, including slow producer/consumer,
sentinel ordering, segment ownership, split recording, gateway isolation, and
disconnect handling.

- [ ] **Step 9: Commit**

```powershell
git add backend/app/ws/audio_handler.py backend/tests/test_audio_handler.py
git commit -m "fix: decouple websocket receive from diarization"
```

---

### Task 6: Verify the Complete Reliability Change

**Files:**
- Verify: `backend/app/ws/audio_handler.py`
- Verify: `backend/app/services/agents/orchestrator.py`
- Verify: `desktop/launcher.py`
- Verify: `backend/scripts/start_backend.py`
- Verify: `backend/scripts/setup_windows_gpu.ps1`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: test, structural, and manual evidence that the call remains connected and finalizes in order.

- [ ] **Step 1: Run all backend tests**

Run:

```powershell
Set-Location backend
python -m unittest discover -s tests
```

Expected: all backend tests pass with zero failures and zero errors.

- [ ] **Step 2: Run all desktop tests**

Run:

```powershell
Set-Location desktop
python -m unittest discover -s tests
```

Expected: all desktop tests pass with zero failures and zero errors.

- [ ] **Step 3: Run structural checks**

Run from the repository root:

```powershell
& 'C:\Users\thoule\.local\bin\sentrux.exe' check .
& 'C:\Users\thoule\.local\bin\sentrux.exe' gate .
```

Expected: `check` reports only the two approved generated lockfile exceptions,
and `gate` reports no unapproved structural regression. Do not refresh the
baseline for this change.

- [ ] **Step 4: Inspect the final diff for forbidden scope**

Run:

```powershell
git diff master...HEAD --check
git diff master...HEAD --name-only
rg -n "kafka|celery|redis" backend desktop -g "*.py" -g "*.ps1"
```

Expected: no whitespace errors, only planned files changed, and no new broker
code or dependency.

- [ ] **Step 5: Perform a manual dual-track reliability call**

Start the normal desktop build or Docker stack, then:

1. Start a call with microphone and system audio enabled.
2. Keep both tracks active for at least 15 minutes.
3. Confirm the UI remains connected while transcript latency fluctuates.
4. Temporarily block the configured live gateway or remove network access long
   enough to force a send timeout and failed reconnect.
5. Confirm recording and local diarization continue while interim gateway text
   is degraded.
6. Restore network access and confirm the gateway can reconnect without
   resetting speaker state.
7. End the call and confirm backlog progress appears until completion.
8. Play mixed, mic, and system recordings and confirm alignment.
9. Confirm transcript entries are emitted in arrival order.

Expected: no audio WebSocket close, no second-receive runtime error, no stale
segment completion, and a normal completed session.

- [ ] **Step 6: Capture log evidence**

Search the desktop log:

```powershell
$logPath = Join-Path $env:LOCALAPPDATA 'Backchannel\backchannel.log'
rg -n "Audio ingress|Diarization backlog|Draining diarization backlog|Audio gateway|Browser disconnected|WebSocket error" $logPath
```

Expected: ingress continues during worker lag, backlog later shrinks, gateway
failure is non-fatal, and there is no
`Cannot call "receive" once a disconnect message has been received`.

- [ ] **Step 7: Commit any test-only correction, otherwise record clean state**

If verification required a test-only correction, commit only that correction:

```powershell
git add backend/tests desktop/tests
git commit -m "test: cover websocket continuity regressions"
```

If no correction was required, run:

```powershell
git status --short
```

Expected: no uncommitted changes.

import asyncio
import threading
import unittest
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import numpy as np

from app.models import CallSegment, TranscriptEntry
from app.services.agents.orchestrator import AgentOrchestrator
from app.ws import audio_handler, audio_messages
from app.ws.audio_handler import (
    _decode_audio_frame,
)
from app.services.voice_enrollment import LOCAL_VOICE_PROFILE_ID


class FakeSessionContext:
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
        # The session's total Question row count; an Exception instance makes
        # the count query fail so tests can prove finalize survives it.
        self.insight_total = insight_total
        self.call_segment = call_segment
        self._execute_results = list(execute_results or [])
        self.executed = []
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, model, item_id):
        if model is CallSegment:
            if self.call_segment and self.call_segment.id == item_id:
                return self.call_segment
            return None
        return self.session

    async def execute(self, statement):
        self.executed.append(statement)
        value = (
            self._execute_results.pop(0)
            if self._execute_results
            else self.session
            if statement._for_update_arg is not None
            else self.last_segment_number
        )
        if callable(value):
            value = value(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    async def scalar(self, statement):
        if isinstance(self.insight_total, Exception):
            raise self.insight_total
        return self.insight_total

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1


class AgentConfigLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_override_replaces_global_enabled_value(self):
        config = SimpleNamespace(slug="analyst", enabled=True)
        override = SimpleNamespace(agent_slug="analyst", enabled=False)
        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [config])),
                    SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [override])),
                ]
            )
        )

        result = await audio_handler._load_agent_configs(db, uuid.uuid4())

        self.assertIs(config, result["analyst"])
        self.assertFalse(result["analyst"].enabled)


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

    async def test_item_done_failure_is_logged_and_worker_continues(self):
        class EchoDiarizer:
            def feed_audio(self, pcm_bytes):
                return [SimpleNamespace(speaker_id="auto_1", pcm_bytes=pcm_bytes)]

        handled = []

        async def on_segment(item, segment):
            handled.append(segment.pcm_bytes)

        def on_item_done(item):
            if item.pcm_bytes == b"first":
                raise RuntimeError("bookkeeping failed")

        queue = asyncio.Queue()
        worker = asyncio.create_task(
            audio_handler._run_diarization_worker(
                queue,
                EchoDiarizer(),
                MagicMock(),
                on_segment,
                AsyncMock(),
                on_item_done,
            )
        )
        queue.put_nowait(audio_handler._QueuedAudioFrame(0, b"first", False, 1.0))
        queue.put_nowait(audio_handler._QueuedAudioFrame(0, b"second", False, 2.0))
        queue.put_nowait(None)

        with self.assertLogs("app.ws.audio_handler", level="WARNING") as logs:
            await worker

        self.assertEqual([b"first", b"second"], handled)
        self.assertIn("Diarization item completion callback failed", logs.output[0])


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

        with patch(
            "app.ws.audio_runtime._DIARIZATION_DRAIN_STATUS_SECONDS",
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


class AudioPipelineOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_cancellation_keeps_persisted_frame_queued(self):
        events = []
        gateway_started = asyncio.Event()
        never = asyncio.Event()
        queue = asyncio.Queue()
        pending = deque()
        writers = {
            track: MagicMock(
                append=MagicMock(
                    side_effect=lambda _pcm, track=track: events.append(track)
                )
            )
            for track in ("mixed", "mic", "system")
        }
        state = SimpleNamespace(
            audio_chunks_received=0,
            audio_bytes_received=0,
            audio_bytes_by_track=[0, 0],
            last_audio_status_at=monotonic(),
            split_track_established=False,
            gateway_available=True,
        )
        gateway_saw_queued_frame = []

        async def blocked_gateway(*_args):
            events.append("gateway")
            gateway_saw_queued_frame.append(not queue.empty())
            gateway_started.set()
            await never.wait()

        with patch(
            "app.ws.audio_messages._send_gateway_audio",
            side_effect=blocked_gateway,
        ):
            task = asyncio.create_task(
                audio_messages._handle_audio_frame(
                    b"\x00\x01\x02",
                    MagicMock(send_json=AsyncMock()),
                    MagicMock(),
                    MagicMock(
                        add=MagicMock(
                            return_value=(b"mixed", b"mic", b"system")
                        )
                    ),
                    writers,
                    queue,
                    pending,
                    state,
                )
            )
            await gateway_started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(
            ["mixed", "mic", "system", "gateway"],
            events,
        )
        self.assertEqual([True], gateway_saw_queued_frame)
        item = queue.get_nowait()
        self.assertEqual((0, b"\x01\x02", False), (
            item.track,
            item.pcm_bytes,
            item.split_track_established,
        ))
        self.assertEqual(1, len(pending))

    async def test_persists_before_gateway_and_stops_worker_before_finalize(self):
        events = []
        segment_id = uuid.uuid4()
        writers = {
            track: MagicMock(append=MagicMock(side_effect=lambda pcm, track=track: events.append(track)))
            for track in ("mixed", "mic", "system")
        }
        websocket = MagicMock(
            send_json=AsyncMock(),
            receive=AsyncMock(
                side_effect=[
                    {"bytes": b"\x00\x01\x02"},
                    {"text": '{"type":"stop","drain":"skip_analysis"}'},
                ]
            ),
        )
        orchestrator = MagicMock(
            start=AsyncMock(),
            check_health=AsyncMock(return_value=True),
        )
        transcription_queue = MagicMock()

        async def worker(queue, *_args):
            item = await queue.get()
            events.append(("worker", item.pcm_bytes))
            self.assertIsNone(await queue.get())
            events.append("worker_stopped")
            return "system-diarizer"

        async def send_gateway(*_args):
            events.append("gateway")
            return True

        async def finalize(*_args, **kwargs):
            events.append("finalize")
            self.assertEqual(segment_id, kwargs["call_segment_id"])
            self.assertIs(writers, kwargs["audio_writers"])
            self.assertEqual("system-diarizer", kwargs["sys_diarizer"])
            self.assertEqual("skip_analysis", kwargs["drain_mode"])

        mixer = MagicMock(add=MagicMock(return_value=(b"mixed", b"mic", b"system")))
        start_segment = AsyncMock(return_value=(segment_id, writers))
        with (
            patch("app.ws.audio_pipeline.TrackMixer", return_value=mixer),
            patch("app.ws.audio_pipeline._run_diarization_worker", side_effect=worker),
            patch("app.ws.audio_messages._send_gateway_audio", side_effect=send_gateway),
        ):
            await audio_handler._run_audio_pipeline(
                uuid.uuid4(),
                websocket,
                False,
                MagicMock(),
                orchestrator,
                transcription_queue,
                MagicMock(),
                audio_handler._requested_drain_mode,
                start_segment,
                finalize,
            )

        self.assertEqual(
            [
                "mixed",
                "mic",
                "system",
                "gateway",
                ("worker", b"\x01\x02"),
                "worker_stopped",
                "finalize",
            ],
            events,
        )


class AudioFrameDecodingTests(unittest.TestCase):
    def test_local_embedding_is_enrolled_only_when_passed_to_registry(self):
        local = np.array([1.0, 0.0], dtype=np.float32)

        mic = audio_handler._new_speaker_registry(0.68, local)
        system = audio_handler._new_speaker_registry(0.68)

        self.assertEqual(LOCAL_VOICE_PROFILE_ID, mic.match(local)[0])
        self.assertIsNone(system.match(local)[0])

    def test_decodes_prefixed_and_legacy_frames(self):
        self.assertTrue(hasattr(audio_handler, "_decode_audio_frame"))
        decode_audio_frame = audio_handler._decode_audio_frame
        cases = [
            (b"\x00\x01\x02", (0, b"\x01\x02")),
            (b"\x01\x03\x04", (1, b"\x03\x04")),
            (b"\x07\x05\x06", (0, b"\x05\x06")),
            (b"\x08\x09", (0, b"\x08\x09")),
        ]

        for raw_frame, expected in cases:
            with self.subTest(raw_frame=raw_frame):
                self.assertEqual(expected, decode_audio_frame(raw_frame))

    def test_split_track_topology_stays_established_after_sharing_stops(self):
        update_state = audio_handler._split_track_established_after_message
        update_from_frame = audio_handler._split_track_established_after_frame

        established = update_state(
            {"type": "track_state", "track": 1, "active": True}, False
        )
        self.assertTrue(established)
        established = update_state(
            {"type": "track_state", "track": 1, "active": False}, established
        )
        self.assertTrue(established)
        queued = audio_handler._queued_speaker_auto_id("auto_1", 0, established)
        self.assertEqual(("auto_1", True), audio_handler._normalize_speaker_auto_id(queued))
        self.assertFalse(
            update_state({"type": "directive", "text": "keep going"}, False)
        )
        self.assertTrue(update_from_frame(1, False))
        self.assertTrue(update_from_frame(0, True))

    def test_queued_mic_job_snapshots_split_track_state(self):
        self.assertTrue(hasattr(audio_handler, "_queued_speaker_auto_id"))
        self.assertTrue(hasattr(audio_handler, "_normalize_speaker_auto_id"))

        queued = audio_handler._queued_speaker_auto_id("auto_1", 0, True)

        self.assertEqual(("auto_1", True), audio_handler._normalize_speaker_auto_id(queued))
        self.assertEqual("auto_1", audio_handler._queued_speaker_auto_id("auto_1", 0, False))
        self.assertEqual("sys_auto_1", audio_handler._queued_speaker_auto_id("sys_auto_1", 1, True))


class AudioFlowAccountingTests(unittest.TestCase):
    def test_reports_per_connection_seconds_by_track(self):
        first_connection = [0, 0]
        second_connection = [0, 0]

        self.assertEqual(
            (10.0, 0.0),
            audio_handler._record_audio_flow(first_connection, track=0, byte_count=320_000),
        )
        self.assertIsNone(
            audio_handler._record_audio_flow(second_connection, track=0, byte_count=160_000)
        )
        self.assertEqual([160_000, 0], second_connection)

        split_connection = [0, 0]
        self.assertIsNone(
            audio_handler._record_audio_flow(split_connection, track=0, byte_count=160_000)
        )
        self.assertEqual(
            (5.0, 5.0),
            audio_handler._record_audio_flow(split_connection, track=1, byte_count=160_000),
        )


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

        async def block_send(_pcm_data):
            await never.wait()

        orchestrator.send_audio = AsyncMock(side_effect=block_send)

        with patch(
            "app.ws.audio_runtime._GATEWAY_SEND_TIMEOUT_SECONDS",
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


class StopDrainModeTests(unittest.TestCase):
    def test_bare_stop_keeps_full_drain(self):
        self.assertTrue(hasattr(audio_handler, "_requested_drain_mode"))
        self.assertEqual("full", audio_handler._requested_drain_mode({"type": "stop"}))

    def test_stop_can_request_skip_analysis(self):
        self.assertEqual(
            "skip_analysis",
            audio_handler._requested_drain_mode({"type": "stop", "drain": "skip_analysis"}),
        )

    def test_unknown_or_minimal_drain_requests_fall_back_to_full(self):
        for requested in ("minimal", "bogus", 7, None):
            with self.subTest(requested=requested):
                self.assertEqual(
                    "full",
                    audio_handler._requested_drain_mode({"type": "stop", "drain": requested}),
                )


class FinalizeCallDrainModeTests(unittest.IsolatedAsyncioTestCase):
    def _make_orchestrator(self, briefing=True):
        plans = {
            "full": ["final_insights", "insight_reconciliation", "opportunity_matching"]
            + (["call_briefing"] if briefing else []),
            "skip_analysis": ["final_insights", "insight_reconciliation"],
            "minimal": [],
        }
        orchestrator = MagicMock()
        orchestrator.drain_stages = MagicMock(side_effect=lambda mode="full": list(plans[mode]))
        orchestrator.graceful_drain = AsyncMock(
            return_value={
                "transcript_available": True,
                "insights_saved": 2,
                "synthesizer_ops": 1,
                "opportunity_ops": 0,
            }
        )
        orchestrator.close_all = AsyncMock()
        return orchestrator

    async def _run_finalize(self, orchestrator, drain_mode=None, insight_total=23):
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        session = SimpleNamespace(state="active", ended_at=None)
        db = FakeSessionContext(session, last_segment_number=None, insight_total=insight_total)
        transcription_queue = MagicMock()
        transcription_queue.drain = AsyncMock()
        transcription_queue.stats = {"jobs": 0, "emitted": 0, "failed": 0}
        kwargs = {}
        if drain_mode is not None:
            kwargs["drain_mode"] = drain_mode

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_persistence.flush_diarizer_segments", return_value=[]),
        ):
            await audio_handler._finalize_call(
                uuid.uuid4(),
                websocket,
                MagicMock(),
                orchestrator,
                transcription_queue,
                **kwargs,
            )

        statuses = [c.args[0]["data"] for c in websocket.send_json.await_args_list]
        return statuses, session, transcription_queue

    async def test_default_finalize_runs_full_drain(self):
        orchestrator = self._make_orchestrator(briefing=True)

        statuses, session, transcription_queue = await self._run_finalize(orchestrator)

        orchestrator.graceful_drain.assert_awaited_once()
        self.assertEqual("full", orchestrator.graceful_drain.await_args.kwargs["mode"])
        orchestrator.close_all.assert_awaited_once()
        transcription_queue.drain.assert_awaited_once()
        first, last = statuses[0], statuses[-1]
        self.assertEqual("speaker_assignment", first["stage"])
        self.assertEqual(1, first["current_step"])
        self.assertEqual(6, first["total_steps"])
        self.assertEqual(
            [
                "speaker_assignment",
                "final_insights",
                "insight_reconciliation",
                "opportunity_matching",
                "call_briefing",
                "saving_session",
            ],
            first["steps"],
        )
        self.assertEqual("completed", last["state"])
        self.assertEqual(6, last["current_step"])
        self.assertEqual(6, last["total_steps"])
        self.assertEqual(100, last["progress"])
        self.assertIn("details", last)
        # The drain counters describe only the final analysis pass; the
        # session-wide total rides alongside so the client can anchor them.
        self.assertEqual(2, last["details"]["insights_saved"])
        self.assertEqual(1, last["details"]["synthesizer_ops"])
        self.assertEqual(23, last["details"]["session_insight_total"])
        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)

    async def test_skip_analysis_finalize_drains_without_late_stages(self):
        orchestrator = self._make_orchestrator(briefing=True)

        statuses, session, _ = await self._run_finalize(orchestrator, drain_mode="skip_analysis")

        orchestrator.graceful_drain.assert_awaited_once()
        self.assertEqual("skip_analysis", orchestrator.graceful_drain.await_args.kwargs["mode"])
        first, last = statuses[0], statuses[-1]
        self.assertEqual(4, first["total_steps"])
        self.assertEqual(
            [
                "speaker_assignment",
                "final_insights",
                "insight_reconciliation",
                "saving_session",
            ],
            first["steps"],
        )
        self.assertEqual("completed", last["state"])
        self.assertEqual(4, last["total_steps"])
        self.assertEqual("completed", session.state)

    async def test_minimal_finalize_runs_zero_analysis_steps(self):
        orchestrator = self._make_orchestrator(briefing=True)

        statuses, session, transcription_queue = await self._run_finalize(
            orchestrator, drain_mode="minimal"
        )

        orchestrator.graceful_drain.assert_not_awaited()
        orchestrator.close_all.assert_awaited_once()
        transcription_queue.drain.assert_awaited_once()
        first, last = statuses[0], statuses[-1]
        self.assertEqual(1, first["current_step"])
        self.assertEqual(2, first["total_steps"])
        self.assertEqual(["speaker_assignment", "saving_session"], first["steps"])
        saving = statuses[-2]
        self.assertEqual("saving_session", saving["stage"])
        self.assertEqual(2, saving["current_step"])
        # Minimal mode still reports honest transcription stats and the
        # session-wide insight total, but carries no analysis output.
        minimal_details = {
            "transcription": {"jobs": 0, "emitted": 0, "failed": 0},
            "session_insight_total": 23,
        }
        self.assertEqual(minimal_details, saving.get("details"))
        self.assertEqual("completed", last["state"])
        self.assertEqual(2, last["total_steps"])
        self.assertEqual(minimal_details, last.get("details"))
        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)

    async def test_finalize_survives_insight_count_failure(self):
        orchestrator = self._make_orchestrator(briefing=True)

        with self.assertLogs("app.ws.audio_handler", level="WARNING"):
            statuses, session, _ = await self._run_finalize(
                orchestrator, insight_total=RuntimeError("db unavailable")
            )

        last = statuses[-1]
        self.assertEqual("completed", last["state"])
        # The drain counters still arrive; only the optional total is missing.
        self.assertEqual(2, last["details"]["insights_saved"])
        self.assertNotIn("session_insight_total", last["details"])
        self.assertEqual("completed", session.state)

    async def test_minimal_finalize_survives_orchestrator_shutdown_failure(self):
        orchestrator = self._make_orchestrator(briefing=True)
        orchestrator.close_all = AsyncMock(side_effect=RuntimeError("gateway close failed"))

        with self.assertLogs("app.ws.audio_handler", level="WARNING"):
            statuses, session, transcription_queue = await self._run_finalize(
                orchestrator, drain_mode="minimal"
            )

        orchestrator.close_all.assert_awaited_once()
        orchestrator.graceful_drain.assert_not_awaited()
        transcription_queue.drain.assert_awaited_once()
        self.assertEqual("completed", statuses[-1]["state"])
        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)

    async def test_stale_finalizer_does_not_complete_resumed_session(self):
        session_id = uuid.uuid4()
        owned_id = uuid.uuid4()
        newer_id = uuid.uuid4()
        owned = SimpleNamespace(
            id=owned_id,
            segment_number=1,
            ended_at=None,
            audio_path=None,
            mic_audio_path=None,
            system_audio_path=None,
        )
        session = SimpleNamespace(state="active", ended_at=None)
        db = FakeSessionContext(
            session,
            call_segment=owned,
            execute_results=[session, newer_id],
        )
        orchestrator = self._make_orchestrator(briefing=False)
        websocket = MagicMock(send_json=AsyncMock())
        transcription_queue = MagicMock(
            drain=AsyncMock(),
            stats={"jobs": 0, "emitted": 0, "failed": 0},
        )

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_persistence.flush_diarizer_segments", return_value=[]),
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

    async def test_older_orphaned_segment_does_not_block_completion(self):
        session_id = uuid.uuid4()
        owned_id = uuid.uuid4()
        older_id = uuid.uuid4()
        owned = SimpleNamespace(
            id=owned_id,
            segment_number=2,
            ended_at=None,
            audio_path=None,
            mic_audio_path=None,
            system_audio_path=None,
        )
        session = SimpleNamespace(state="active", ended_at=None)
        db = FakeSessionContext(
            session,
            call_segment=owned,
            execute_results=[
                session,
                lambda statement: (
                    None
                    if "call_segments.segment_number >" in str(statement)
                    else older_id
                ),
            ],
        )
        orchestrator = self._make_orchestrator(briefing=False)
        websocket = MagicMock(send_json=AsyncMock())
        transcription_queue = MagicMock(
            drain=AsyncMock(),
            stats={"jobs": 0, "emitted": 0, "failed": 0},
        )

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_persistence.flush_diarizer_segments", return_value=[]),
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

        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)

    async def test_finalize_locks_session_before_segment_check(self):
        session_id = uuid.uuid4()
        owned_id = uuid.uuid4()
        owned = SimpleNamespace(
            id=owned_id,
            segment_number=1,
            ended_at=None,
            audio_path=None,
            mic_audio_path=None,
            system_audio_path=None,
        )
        session = SimpleNamespace(state="active", ended_at=None)
        db = FakeSessionContext(
            session,
            call_segment=owned,
            execute_results=[session, None],
        )
        orchestrator = self._make_orchestrator(briefing=False)
        websocket = MagicMock(send_json=AsyncMock())
        transcription_queue = MagicMock(
            drain=AsyncMock(),
            stats={"jobs": 0, "emitted": 0, "failed": 0},
        )

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_persistence.flush_diarizer_segments", return_value=[]),
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

        self.assertIsNotNone(db.executed[0]._for_update_arg)


class MinimalFinalizeAnalysisShutdownTests(unittest.IsolatedAsyncioTestCase):
    """Real-orchestrator coverage for the disconnect path.

    The orchestrator's interval analysis tasks are real asyncio tasks here
    (only the LLM call itself is stubbed), so these tests prove no analysis
    cycle can run once a minimal finalize has started, even while a slow
    transcription drain keeps yielding control across analyst intervals.
    """

    _ANALYST_INTERVAL = 0.02

    def _build_live_orchestrator(self, analysis_calls: list) -> tuple[MagicMock, AgentOrchestrator]:
        def config(**overrides):
            base = {
                "enabled": False,
                "model_id": "test-model",
                "prompt": "",
                "interval_seconds": self._ANALYST_INTERVAL,
                "sub_types": "",
                "lenses": "",
                "knowledge_source_ids": "",
            }
            base.update(overrides)
            return SimpleNamespace(**base)

        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        orchestrator = AgentOrchestrator(
            session_id=uuid.uuid4(),
            websocket=websocket,
            directives=[],
            doc_summaries="",
            active_questions=[],
            speakers=[],
            agent_configs={
                "audio_gateway": config(),
                "consolidated_analyst": config(enabled=True, sub_types="question"),
                "objection_handler": config(),
                "synthesizer": config(),
                "opportunity_specialist": config(),
            },
        )

        async def record_analysis_cycle(**kwargs):
            analysis_calls.append(kwargs)
            return []

        orchestrator.consolidated_agent.run_cycle = record_analysis_cycle
        return websocket, orchestrator

    async def test_minimal_finalize_stops_analysis_before_slow_transcription_drain(self):
        analysis_calls: list = []
        websocket, orchestrator = self._build_live_orchestrator(analysis_calls)
        await orchestrator.start()
        self.addAsyncCleanup(AgentOrchestrator.close_all, orchestrator)
        await orchestrator.feed_transcript("We are worried about rollout timing.", "Alice")

        # Sanity: while the call is live, the real interval analyst task fires.
        deadline = monotonic() + 2.0
        while not analysis_calls and monotonic() < deadline:
            await asyncio.sleep(0.01)
        self.assertTrue(
            analysis_calls,
            "interval analyst never fired while live; harness is not exercising the loop",
        )

        events: list[str] = []
        real_close_all = orchestrator.close_all

        async def recording_close_all():
            events.append("close_all")
            await real_close_all()

        orchestrator.close_all = recording_close_all

        async def slow_drain():
            # A long transcription flush after a disconnect: keeps yielding
            # control across many analyst intervals.
            events.append("drain_start")
            for _ in range(10):
                await asyncio.sleep(self._ANALYST_INTERVAL)
            events.append("drain_end")

        transcription_queue = SimpleNamespace(
            add=MagicMock(),
            drain=slow_drain,
            stats={"jobs": 0, "emitted": 0, "failed": 0},
        )
        session = SimpleNamespace(state="active", ended_at=None)
        db = FakeSessionContext(session, last_segment_number=None)
        analysis_calls.clear()

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_persistence.flush_diarizer_segments", return_value=[]),
        ):
            await audio_handler._finalize_call(
                uuid.uuid4(),
                websocket,
                MagicMock(),
                orchestrator,
                transcription_queue,
                drain_mode="minimal",
            )

        # Ordering: the orchestrator is stopped before the drain starts.
        self.assertEqual(["close_all", "drain_start", "drain_end"], events)
        # Zero analysis cycles ran during or after the minimal finalize.
        self.assertEqual([], analysis_calls)
        self.assertTrue(orchestrator._consolidated_task.done())
        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)


class CallSegmentStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_locks_active_session_and_clears_stale_end_time(self):
        session_id = uuid.uuid4()
        session = SimpleNamespace(
            state="active",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db = FakeSessionContext(session, last_segment_number=None)

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_handler.SegmentAudioWriter", return_value=MagicMock()),
        ):
            await audio_handler._start_call_segment(session_id)

        self.assertIsNotNone(db.executed[0]._for_update_arg)
        self.assertEqual("active", session.state)
        self.assertIsNone(session.ended_at)

    async def test_initial_segment_does_not_add_resume_marker_from_active_state(self):
        session_id = uuid.uuid4()
        session = SimpleNamespace(
            state="active",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ended_at=None,
        )
        db = FakeSessionContext(session, last_segment_number=None)

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_handler.SegmentAudioWriter", return_value=MagicMock()),
        ):
            await audio_handler._start_call_segment(session_id)

        self.assertEqual(1, len(db.added))
        self.assertIsInstance(db.added[0], CallSegment)

    async def test_starts_next_segment_and_adds_resume_marker(self):
        self.assertTrue(hasattr(audio_handler, "_start_call_segment"))
        start_call_segment = audio_handler._start_call_segment
        session_id = uuid.uuid4()
        original_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session = SimpleNamespace(
            state="completed",
            started_at=original_started_at,
            ended_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db = FakeSessionContext(session, last_segment_number=2)
        writers = [MagicMock(), MagicMock(), MagicMock()]

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch(
                "app.ws.audio_handler.SegmentAudioWriter",
                side_effect=writers,
            ) as writer_class,
            patch(
                "app.ws.audio_handler.get_next_sequence",
                new=AsyncMock(return_value=41),
            ),
        ):
            result = await start_call_segment(session_id)

        segment_id, result_writers = result
        self.assertEqual(db.added[0].id, segment_id)
        self.assertEqual(
            {"mixed": writers[0], "mic": writers[1], "system": writers[2]},
            result_writers,
        )
        writer_class.assert_has_calls(
            [
                call(session_id, 3),
                call(session_id, 3, track="mic"),
                call(session_id, 3, track="sys"),
            ]
        )
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
        self.assertTrue(hasattr(audio_handler, "_start_call_segment"))
        start_call_segment = audio_handler._start_call_segment
        session_id = uuid.uuid4()
        db = FakeSessionContext(None)

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_handler.SegmentAudioWriter") as writer_class,
        ):
            result = await start_call_segment(session_id)

        self.assertIsNone(result)
        writer_class.assert_not_called()
        self.assertEqual([], db.added)
        self.assertEqual(0, db.commits)


class SegmentAudioPersistenceTests(unittest.TestCase):
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

    def test_auxiliary_append_failure_keeps_mixed_writer_active(self):
        self.assertTrue(hasattr(audio_handler, "_append_audio_frames"))
        writers = {
            "mixed": MagicMock(),
            "mic": MagicMock(),
            "system": MagicMock(),
        }
        writers["mic"].append.side_effect = OSError("mic disk error")

        with self.assertLogs("app.ws.audio_handler", level="WARNING"):
            audio_handler._append_audio_frames(
                writers,
                (b"mixed", b"mic", b"system"),
            )

        writers["mixed"].append.assert_called_once_with(b"mixed")
        writers["system"].append.assert_called_once_with(b"system")
        self.assertIsNone(writers["mic"])
        self.assertIsNotNone(writers["mixed"])

    def test_auxiliary_close_failure_still_returns_mixed_path(self):
        writers = {
            "mixed": MagicMock(close=MagicMock(return_value="audio/mixed.wav")),
            "mic": MagicMock(close=MagicMock(side_effect=OSError("mic close error"))),
            "system": MagicMock(close=MagicMock(return_value="audio/sys.wav")),
        }

        try:
            with self.assertLogs("app.ws.audio_handler", level="WARNING"):
                paths = audio_handler._close_audio_writers(
                    writers,
                    split_track_established=True,
                )
        except OSError as exc:
            self.fail(f"auxiliary close failure escaped: {exc}")

        self.assertEqual("audio/mixed.wav", paths["audio_path"])
        self.assertIsNone(paths["mic_audio_path"])
        self.assertEqual("audio/sys.wav", paths["system_audio_path"])

    def test_split_track_paths_are_retained(self):
        self.assertTrue(hasattr(audio_handler, "_close_audio_writers"))
        writers = {
            "mixed": MagicMock(close=MagicMock(return_value="audio/mixed.wav")),
            "mic": MagicMock(close=MagicMock(return_value="audio/mic.wav")),
            "system": MagicMock(close=MagicMock(return_value="audio/sys.wav")),
        }

        paths = audio_handler._close_audio_writers(writers, split_track_established=True)

        self.assertEqual(
            {
                "audio_path": "audio/mixed.wav",
                "mic_audio_path": "audio/mic.wav",
                "system_audio_path": "audio/sys.wav",
            },
            paths,
        )

    def test_mic_only_track_files_are_removed(self):
        self.assertTrue(hasattr(audio_handler, "_close_audio_writers"))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            mic_path = root / "audio" / "mic.wav"
            system_path = root / "audio" / "sys.wav"
            mic_path.parent.mkdir()
            mic_path.write_bytes(b"mic")
            system_path.write_bytes(b"system")
            writers = {
                "mixed": MagicMock(close=MagicMock(return_value="audio/mixed.wav")),
                "mic": MagicMock(close=MagicMock(return_value="audio/mic.wav")),
                "system": MagicMock(close=MagicMock(return_value="audio/sys.wav")),
            }

            with patch("app.ws.audio_persistence.data_dir", return_value=root):
                paths = audio_handler._close_audio_writers(
                    writers,
                    split_track_established=False,
                )

            self.assertEqual("audio/mixed.wav", paths["audio_path"])
            self.assertIsNone(paths["mic_audio_path"])
            self.assertIsNone(paths["system_audio_path"])
            self.assertFalse(mic_path.exists())
            self.assertFalse(system_path.exists())

    def test_call_segment_accepts_track_paths(self):
        self.assertTrue(hasattr(CallSegment, "mic_audio_path"))
        self.assertTrue(hasattr(CallSegment, "system_audio_path"))
        segment = CallSegment(
            session_id=uuid.uuid4(),
            segment_number=1,
            mic_audio_path="audio/mic.wav",
            system_audio_path="audio/sys.wav",
        )

        self.assertEqual("audio/mic.wav", segment.mic_audio_path)
        self.assertEqual("audio/sys.wav", segment.system_audio_path)


class FakeRestoreSessionContext:
    """Async-session fake for the refusal-restore flow.

    execute() results are consumed in order: finished-segment probe first,
    then the transcript-entry probe.
    """

    def __init__(self, session, execute_results, commit_error=None):
        self.session = session
        self._execute_results = list(execute_results)
        self._commit_error = commit_error
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, model, item_id):
        return self.session

    async def execute(self, statement):
        value = self._execute_results.pop(0)
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    async def commit(self):
        if self._commit_error is not None:
            raise self._commit_error
        self.commits += 1


class RefusalRestoreTests(unittest.IsolatedAsyncioTestCase):
    """A refused start must never leave a session stranded in "active"."""

    def _active_session(self, ended_at=None):
        return SimpleNamespace(
            state="active",
            ended_at=ended_at,
            started_at=datetime.now(timezone.utc),
        )

    async def _restore(self, db):
        with patch("app.ws.audio_handler.async_session", return_value=db):
            return await audio_handler._restore_session_after_refusal(uuid.uuid4())

    async def test_fresh_refusal_restores_pre_call_and_clears_started_at(self):
        session = self._active_session()
        db = FakeRestoreSessionContext(session, [None, None])

        restored = await self._restore(db)

        self.assertEqual("pre_call", restored)
        self.assertEqual("pre_call", session.state)
        self.assertIsNone(session.started_at)
        self.assertEqual(1, db.commits)

    async def test_resumed_refusal_with_finished_segment_restores_completed(self):
        session = self._active_session()
        db = FakeRestoreSessionContext(session, [object(), None])

        restored = await self._restore(db)

        self.assertEqual("completed", restored)
        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)
        self.assertEqual(1, db.commits)

    async def test_completed_zero_segment_imported_session_restores_completed(self):
        # Imported/analyzed session: transcript entries exist, no call
        # segments, and the resume PATCH already cleared ended_at.
        session = self._active_session()
        db = FakeRestoreSessionContext(session, [None, object()])

        restored = await self._restore(db)

        self.assertEqual("completed", restored)
        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)

    async def test_surviving_ended_at_restores_completed_without_probes(self):
        session = self._active_session(ended_at=datetime.now(timezone.utc))
        db = FakeRestoreSessionContext(session, [None, None])

        restored = await self._restore(db)

        self.assertEqual("completed", restored)
        self.assertEqual("completed", session.state)

    async def test_non_active_session_is_left_untouched(self):
        session = SimpleNamespace(
            state="completed",
            ended_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
        db = FakeRestoreSessionContext(session, [None, None])

        restored = await self._restore(db)

        self.assertIsNone(restored)
        self.assertEqual("completed", session.state)
        self.assertEqual(0, db.commits)

    async def test_missing_session_is_a_no_op(self):
        db = FakeRestoreSessionContext(None, [None, None])

        self.assertIsNone(await self._restore(db))
        self.assertEqual(0, db.commits)

    async def test_restore_failure_is_contained(self):
        session = self._active_session()
        db = FakeRestoreSessionContext(
            session, [None, None], commit_error=RuntimeError("db down")
        )

        # Must not raise: the refusal proceeds even when the restore fails.
        self.assertIsNone(await self._restore(db))


class TranscriptionReadinessGateTests(unittest.IsolatedAsyncioTestCase):
    def _websocket(self):
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        websocket.close = AsyncMock()
        return websocket

    async def test_refuses_and_closes_when_transcription_is_not_ready(self):
        from app.services.transcription_readiness import TranscriptionReadiness

        self.assertTrue(hasattr(audio_handler, "_refuse_unready_transcription"))
        websocket = self._websocket()
        readiness = TranscriptionReadiness(
            ready=False,
            model_id="gemini-3.5-flash-lite",
            provider="google",
            reason="Transcription cannot run: no Google API key is configured.",
        )

        refused = await audio_handler._refuse_unready_transcription(websocket, readiness)

        self.assertTrue(refused)
        websocket.close.assert_awaited_once()
        payload = websocket.send_json.await_args.args[0]
        self.assertEqual("status", payload["type"])
        self.assertEqual("transcription_unready", payload["data"]["state"])
        self.assertEqual(readiness.reason, payload["data"]["message"])

    async def test_allows_call_when_transcription_is_ready(self):
        from app.services.transcription_readiness import TranscriptionReadiness

        websocket = self._websocket()
        readiness = TranscriptionReadiness(
            ready=True, model_id="local-whisper-base", provider="local"
        )

        refused = await audio_handler._refuse_unready_transcription(websocket, readiness)

        self.assertFalse(refused)
        websocket.send_json.assert_not_awaited()
        websocket.close.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

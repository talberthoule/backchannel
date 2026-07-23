import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import numpy as np

from app.models import CallSegment, TranscriptEntry
from app.services.agents.orchestrator import AgentOrchestrator
from app.ws import audio_handler
from app.ws.audio_handler import (
    _decode_audio_frame,
    _reconnect_audio_pipeline,
)
from app.services.voice_enrollment import LOCAL_VOICE_PROFILE_ID


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


class AudioReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_flushes_both_tracks_and_reports_success(self):
        self.assertTrue(hasattr(audio_handler, "_reconnect_audio_pipeline"))
        reconnect_audio_pipeline = audio_handler._reconnect_audio_pipeline
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
            reconnected = await reconnect_audio_pipeline(
                websocket,
                diarizer,
                system_diarizer,
                transcription_queue,
                orchestrator,
                True,
            )

        self.assertTrue(reconnected)
        flush_segments.assert_has_calls([call(diarizer), call(system_diarizer)])
        self.assertEqual(
            [call("mic_auto_1", b"mic"), call("sys_auto_2", b"system")],
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
        self.assertTrue(hasattr(audio_handler, "_reconnect_audio_pipeline"))
        reconnect_audio_pipeline = audio_handler._reconnect_audio_pipeline
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
            reconnected = await reconnect_audio_pipeline(
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

    async def _run_finalize(self, orchestrator, drain_mode=None):
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        session = SimpleNamespace(state="active", ended_at=None)
        db = FakeSessionContext(session, last_segment_number=None)
        transcription_queue = MagicMock()
        transcription_queue.drain = AsyncMock()
        transcription_queue.stats = {"jobs": 0, "emitted": 0, "failed": 0}
        kwargs = {}
        if drain_mode is not None:
            kwargs["drain_mode"] = drain_mode

        with (
            patch("app.ws.audio_handler.async_session", return_value=db),
            patch("app.ws.audio_handler.flush_diarizer_segments", return_value=[]),
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
        # Minimal mode still reports honest transcription stats, but carries
        # no analysis output in the details.
        minimal_details = {"transcription": {"jobs": 0, "emitted": 0, "failed": 0}}
        self.assertEqual(minimal_details, saving.get("details"))
        self.assertEqual("completed", last["state"])
        self.assertEqual(2, last["total_steps"])
        self.assertEqual(minimal_details, last.get("details"))
        self.assertEqual("completed", session.state)
        self.assertIsNotNone(session.ended_at)

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
            patch("app.ws.audio_handler.flush_diarizer_segments", return_value=[]),
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
            result = await start_call_segment(session_id)

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

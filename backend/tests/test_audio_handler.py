import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.models import CallSegment, TranscriptEntry
from app.ws import audio_handler
from app.ws.audio_handler import (
    _decode_audio_frame,
    _reconnect_audio_pipeline,
)


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


class AudioFrameDecodingTests(unittest.TestCase):
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

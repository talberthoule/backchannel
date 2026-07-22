import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
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

        self.assertEqual(
            {"mixed": writers[0], "mic": writers[1], "system": writers[2]},
            result,
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

            with patch("app.ws.audio_handler.data_dir", return_value=root):
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


if __name__ == "__main__":
    unittest.main()

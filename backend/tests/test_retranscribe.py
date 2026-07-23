import inspect
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

from app.models import CallSegment, Speaker, TranscriptEntry
from app.routers import imports as import_router
from app.routers import retranscribe
from app.routers.imports import _transcribe_audio_diarized
from app.services.speaker_diarizer import DiarizedSegment, SpeakerRegistry


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class FakeSpeakerDB:
    def __init__(self, speakers):
        self.speakers = speakers
        self.added = []

    async def execute(self, statement):
        return FakeScalarResult(self.speakers)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        pass

    async def commit(self):
        pass


class FakeDiarizer:
    def __init__(self, speaker_id="auto_1"):
        self.speaker_id = speaker_id

    def feed_audio(self, pcm):
        return [DiarizedSegment(self.speaker_id, b"speech")]


class ScheduledDiarizer:
    def __init__(self, schedule):
        self.schedule = schedule
        self.calls = 0

    def feed_audio(self, pcm):
        self.calls += 1
        text = self.schedule.get(self.calls)
        return [DiarizedSegment("auto_1", text.encode())] if text else []


class LatencyDiarizer:
    def __init__(self, schedule):
        self.schedule = schedule
        self.calls = 0

    def feed_audio(self, pcm):
        self.calls += 1
        item = self.schedule.get(self.calls)
        if not item:
            return []
        text, start_sample = item
        segment = DiarizedSegment("auto_1", text.encode())
        segment.start_sample = start_sample
        return [segment]


class SplitTrackRetranscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_mic_track_with_no_user_falls_back_to_external_mapping(self):
        session_id = uuid.uuid4()
        remote = Speaker(
            id=uuid.uuid4(), session_id=session_id, name="Remote", is_user=False,
            speaker_type="external",
        )
        db = FakeSpeakerDB([remote])
        await self._transcribe_local_fallback(session_id, db)

        entries = [value for value in db.added if isinstance(value, TranscriptEntry)]
        self.assertEqual([remote.id], [entry.speaker_id for entry in entries])

    async def test_mic_track_with_multiple_users_falls_back_to_external_mapping(self):
        session_id = uuid.uuid4()
        speakers = [
            Speaker(id=uuid.uuid4(), session_id=session_id, name="User 1", is_user=True),
            Speaker(id=uuid.uuid4(), session_id=session_id, name="User 2", is_user=True),
            Speaker(
                id=uuid.uuid4(), session_id=session_id, name="Remote", is_user=False,
                speaker_type="external",
            ),
        ]
        db = FakeSpeakerDB(speakers)
        await self._transcribe_local_fallback(session_id, db)

        entries = [value for value in db.added if isinstance(value, TranscriptEntry)]
        self.assertEqual([speakers[2].id], [entry.speaker_id for entry in entries])

    async def _transcribe_local_fallback(self, session_id, db):
        runtime_config = SimpleNamespace(
            effective_live_diarizer="speaker",
            speaker_similarity_threshold=0.68,
        )
        with (
            patch("app.routers.imports.convert_to_pcm16", return_value=b"pcm"),
            patch("app.routers.imports.create_diarizer", return_value=FakeDiarizer()),
            patch("app.routers.imports.flush_diarizer_segments", return_value=[]),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=SimpleNamespace(batch_model_id="model")),
            ),
            patch(
                "app.routers.imports.create_transcriber",
                return_value=SimpleNamespace(
                    transcribe_segment=AsyncMock(return_value="hello")
                ),
            ),
            patch("app.routers.imports.get_next_sequence", new=AsyncMock(return_value=1)),
        ):
            await _transcribe_audio_diarized(
                b"mic", "wav", session_id, db, model_id="model",
                registry=SpeakerRegistry(), auto_speaker_map={},
                runtime_config=runtime_config, local_track=True,
            )

    async def test_orders_by_speech_start_when_earlier_turn_completes_later(self):
        session_id = uuid.uuid4()
        remote = Speaker(
            id=uuid.uuid4(),
            session_id=session_id,
            name="Remote",
            is_user=False,
            speaker_type="external",
        )
        db = FakeSpeakerDB([remote])
        runtime_config = SimpleNamespace(
            effective_live_diarizer="speaker",
            speaker_similarity_threshold=0.68,
        )
        chunk = b"\x00" * 3200
        mic_diarizer = LatencyDiarizer({3: ("earlier-long-mic", 0)})
        system_diarizer = LatencyDiarizer({2: ("later-short-system", 1600)})

        with (
            patch("app.routers.imports.convert_to_pcm16", side_effect=[chunk * 3, chunk * 3]),
            patch("app.routers.imports.create_diarizer", side_effect=[mic_diarizer, system_diarizer]),
            patch("app.routers.imports.flush_diarizer_segments", return_value=[]),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=SimpleNamespace(batch_model_id="model")),
            ),
            patch(
                "app.routers.imports.create_transcriber",
                return_value=SimpleNamespace(
                    transcribe_segment=AsyncMock(side_effect=lambda pcm: pcm.decode())
                ),
            ),
            patch("app.routers.imports.get_next_sequence", new=AsyncMock(side_effect=[1, 2])),
        ):
            await import_router._transcribe_split_audio_diarized(
                b"mic-wav",
                b"system-wav",
                session_id,
                db,
                model_id="model",
                mic_registry=SpeakerRegistry(),
                remote_registry=SpeakerRegistry(),
                mic_auto_speaker_map={},
                remote_auto_speaker_map={},
                runtime_config=runtime_config,
            )

        entries = [value for value in db.added if isinstance(value, TranscriptEntry)]
        self.assertEqual(
            ["earlier-long-mic", "later-short-system"],
            [entry.text for entry in entries],
        )

    async def test_flush_only_turns_order_by_speech_start(self):
        session_id = uuid.uuid4()
        remote = Speaker(
            id=uuid.uuid4(),
            session_id=session_id,
            name="Remote",
            is_user=False,
            speaker_type="external",
        )
        db = FakeSpeakerDB([remote])
        runtime_config = SimpleNamespace(
            effective_live_diarizer="speaker",
            speaker_similarity_threshold=0.68,
        )
        mic_diarizer = LatencyDiarizer({})
        system_diarizer = LatencyDiarizer({})
        mic_tail = DiarizedSegment("auto_1", b"later-mic")
        mic_tail.start_sample = 3200
        system_tail = DiarizedSegment("auto_1", b"earlier-system")
        system_tail.start_sample = 1600

        with (
            patch("app.routers.imports.convert_to_pcm16", return_value=b"pcm"),
            patch("app.routers.imports.create_diarizer", side_effect=[mic_diarizer, system_diarizer]),
            patch(
                "app.routers.imports.flush_diarizer_segments",
                side_effect=[[mic_tail], [system_tail]],
            ),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=SimpleNamespace(batch_model_id="model")),
            ),
            patch(
                "app.routers.imports.create_transcriber",
                return_value=SimpleNamespace(
                    transcribe_segment=AsyncMock(side_effect=lambda pcm: pcm.decode())
                ),
            ),
            patch("app.routers.imports.get_next_sequence", new=AsyncMock(side_effect=[1, 2])),
        ):
            await import_router._transcribe_split_audio_diarized(
                b"mic-wav",
                b"system-wav",
                session_id,
                db,
                model_id="model",
                mic_registry=SpeakerRegistry(),
                remote_registry=SpeakerRegistry(),
                mic_auto_speaker_map={},
                remote_auto_speaker_map={},
                runtime_config=runtime_config,
            )

        entries = [value for value in db.added if isinstance(value, TranscriptEntry)]
        self.assertEqual(
            ["earlier-system", "later-mic"],
            [entry.text for entry in entries],
        )

    async def test_aligned_tracks_persist_transcript_in_conversation_order(self):
        self.assertTrue(hasattr(import_router, "_transcribe_split_audio_diarized"))
        session_id = uuid.uuid4()
        me = Speaker(
            id=uuid.uuid4(),
            session_id=session_id,
            name="Me",
            is_user=True,
            speaker_type="team",
        )
        remote = Speaker(
            id=uuid.uuid4(),
            session_id=session_id,
            name="Remote",
            is_user=False,
            speaker_type="external",
        )
        db = FakeSpeakerDB([me, remote])
        runtime_config = SimpleNamespace(
            effective_live_diarizer="speaker",
            speaker_similarity_threshold=0.68,
        )
        chunk = b"\x00" * 3200
        mic_diarizer = ScheduledDiarizer({1: "mic-1", 3: "mic-3"})
        system_diarizer = ScheduledDiarizer({2: "sys-2", 4: "sys-4"})

        with (
            patch(
                "app.routers.imports.convert_to_pcm16",
                side_effect=[chunk * 4, chunk * 4],
            ),
            patch(
                "app.routers.imports.create_diarizer",
                side_effect=[mic_diarizer, system_diarizer],
            ),
            patch("app.routers.imports.flush_diarizer_segments", return_value=[]),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=SimpleNamespace(batch_model_id="model")),
            ),
            patch(
                "app.routers.imports.create_transcriber",
                return_value=SimpleNamespace(
                    transcribe_segment=AsyncMock(
                        side_effect=lambda pcm: pcm.decode()
                    )
                ),
            ),
            patch(
                "app.routers.imports.get_next_sequence",
                new=AsyncMock(side_effect=[1, 2, 3, 4]),
            ),
        ):
            count = await import_router._transcribe_split_audio_diarized(
                b"mic-wav",
                b"system-wav",
                session_id,
                db,
                model_id="model",
                mic_registry=SpeakerRegistry(),
                remote_registry=SpeakerRegistry(),
                mic_auto_speaker_map={},
                remote_auto_speaker_map={},
                runtime_config=runtime_config,
            )

        entries = [value for value in db.added if isinstance(value, TranscriptEntry)]
        self.assertEqual(4, count)
        self.assertEqual(
            ["mic-1", "sys-2", "mic-3", "sys-4"],
            [entry.text for entry in entries],
        )
        self.assertEqual(
            [me.id, remote.id, me.id, remote.id],
            [entry.speaker_id for entry in entries],
        )

    async def test_mic_segments_bind_to_sole_user_including_unknown(self):
        session_id = uuid.uuid4()
        me = Speaker(
            id=uuid.uuid4(),
            session_id=session_id,
            name="Me",
            is_user=True,
            speaker_type="team",
        )
        db = FakeSpeakerDB([me])
        runtime_config = SimpleNamespace(
            effective_live_diarizer="speaker",
            speaker_similarity_threshold=0.68,
        )

        with (
            patch("app.routers.imports.convert_to_pcm16", return_value=b"pcm"),
            patch(
                "app.routers.imports.create_diarizer",
                return_value=SimpleNamespace(
                    feed_audio=lambda pcm: [
                        DiarizedSegment("auto_1", b"speech"),
                        DiarizedSegment("auto_unknown", b"speech"),
                    ]
                ),
            ),
            patch("app.routers.imports.flush_diarizer_segments", return_value=[]),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=SimpleNamespace(batch_model_id="model")),
            ),
            patch(
                "app.routers.imports.create_transcriber",
                return_value=SimpleNamespace(
                    transcribe_segment=AsyncMock(return_value="hello")
                ),
            ),
            patch(
                "app.routers.imports.get_next_sequence",
                new=AsyncMock(side_effect=[1, 2]),
            ),
        ):
            await _transcribe_audio_diarized(
                b"mic",
                "wav",
                session_id,
                db,
                model_id="model",
                registry=SpeakerRegistry(),
                auto_speaker_map={},
                runtime_config=runtime_config,
                local_track=True,
            )

        entries = [value for value in db.added if isinstance(value, TranscriptEntry)]
        self.assertEqual([me.id, me.id], [entry.speaker_id for entry in entries])

    async def test_split_track_fixture_retains_me_and_remote_across_two_segments(self):
        parameters = inspect.signature(_transcribe_audio_diarized).parameters
        self.assertIn("registry", parameters)
        self.assertIn("auto_speaker_map", parameters)
        self.assertIn("runtime_config", parameters)
        self.assertIn("local_track", parameters)

        session_id = uuid.uuid4()
        me = Speaker(
            id=uuid.uuid4(),
            session_id=session_id,
            name="Me",
            is_user=True,
            speaker_type="team",
        )
        remote = Speaker(
            id=uuid.uuid4(),
            session_id=session_id,
            name="Remote",
            is_user=False,
            speaker_type="external",
        )
        db = FakeSpeakerDB([me, remote])
        runtime_config = SimpleNamespace(
            effective_live_diarizer="speaker",
            speaker_similarity_threshold=0.68,
        )
        mic_registry = SpeakerRegistry()
        remote_registry = SpeakerRegistry()
        mic_map = {}
        remote_map = {}

        with (
            patch("app.routers.imports.convert_to_pcm16", return_value=b"pcm"),
            patch("app.routers.imports.create_diarizer", return_value=FakeDiarizer()),
            patch("app.routers.imports.flush_diarizer_segments", return_value=[]),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=SimpleNamespace(batch_model_id="model")),
            ),
            patch(
                "app.routers.imports.create_transcriber",
                return_value=SimpleNamespace(
                    transcribe_segment=AsyncMock(return_value="hello")
                ),
            ),
            patch(
                "app.routers.imports.get_next_sequence",
                new=AsyncMock(side_effect=[1, 2, 3, 4]),
            ),
        ):
            for _ in range(2):
                await _transcribe_audio_diarized(
                    b"mic",
                    "wav",
                    session_id,
                    db,
                    model_id="model",
                    registry=mic_registry,
                    auto_speaker_map=mic_map,
                    runtime_config=runtime_config,
                    local_track=True,
                )
            for _ in range(2):
                await _transcribe_audio_diarized(
                    b"system",
                    "wav",
                    session_id,
                    db,
                    model_id="model",
                    registry=remote_registry,
                    auto_speaker_map=remote_map,
                    runtime_config=runtime_config,
                )

        entries = [value for value in db.added if isinstance(value, TranscriptEntry)]
        self.assertEqual([me.id, me.id, remote.id, remote.id], [entry.speaker_id for entry in entries])
        self.assertEqual({}, mic_map)
        self.assertEqual({"auto_1": str(remote.id)}, remote_map)

    async def test_split_paths_share_separate_mic_and_remote_state(self):
        self.assertTrue(hasattr(retranscribe, "_transcribe_stored_segments"))
        session_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for segment_number in (1, 2):
                mic = Path("audio") / f"segment_{segment_number}_mic.wav"
                system = Path("audio") / f"segment_{segment_number}_sys.wav"
                for path in (mic, system):
                    full_path = root / path
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_bytes(path.name.encode())
                paths.append(
                    CallSegment(
                        session_id=session_id,
                        segment_number=segment_number,
                        mic_audio_path=str(mic),
                        system_audio_path=str(system),
                    )
                )

            transcribe = AsyncMock(return_value=2)
            with (
                patch("app.routers.retranscribe.data_dir", return_value=root),
                patch(
                    "app.routers.retranscribe.get_diarizer_runtime_config",
                    new=AsyncMock(
                        return_value=SimpleNamespace(speaker_similarity_threshold=0.68)
                    ),
                ),
                patch(
                    "app.routers.retranscribe._transcribe_split_audio_diarized",
                    new=transcribe,
                ),
            ):
                total = await retranscribe._transcribe_stored_segments(
                    paths,
                    session_id,
                    object(),
                    "model",
                )

        self.assertEqual(4, total)
        self.assertEqual(2, transcribe.await_count)
        calls = transcribe.await_args_list
        self.assertIs(calls[0].kwargs["mic_registry"], calls[1].kwargs["mic_registry"])
        self.assertIs(
            calls[0].kwargs["mic_auto_speaker_map"],
            calls[1].kwargs["mic_auto_speaker_map"],
        )
        self.assertIs(
            calls[0].kwargs["remote_registry"],
            calls[1].kwargs["remote_registry"],
        )
        self.assertIs(
            calls[0].kwargs["remote_auto_speaker_map"],
            calls[1].kwargs["remote_auto_speaker_map"],
        )
        self.assertIsNot(
            calls[0].kwargs["mic_registry"],
            calls[0].kwargs["remote_registry"],
        )

    async def test_legacy_mixed_segment_uses_existing_fallback(self):
        self.assertTrue(hasattr(retranscribe, "_transcribe_stored_segments"))
        session_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mixed = root / "audio" / "segment_1.wav"
            mixed.parent.mkdir()
            mixed.write_bytes(b"mixed")
            segment = CallSegment(
                session_id=session_id,
                segment_number=1,
                audio_path="audio/segment_1.wav",
            )
            transcribe = AsyncMock(return_value=1)
            with (
                patch("app.routers.retranscribe.data_dir", return_value=root),
                patch(
                    "app.routers.retranscribe.get_diarizer_runtime_config",
                    new=AsyncMock(
                        return_value=SimpleNamespace(speaker_similarity_threshold=0.68)
                    ),
                ),
                patch("app.routers.retranscribe._transcribe_audio_diarized", new=transcribe),
            ):
                total = await retranscribe._transcribe_stored_segments(
                    [segment],
                    session_id,
                    object(),
                    "model",
                )

        self.assertEqual(1, total)
        transcribe.assert_awaited_once_with(
            b"mixed",
            "wav",
            session_id,
            ANY,
            model_id="model",
        )

    async def test_missing_split_file_falls_back_to_complete_mixed_audio(self):
        session_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mixed = root / "audio" / "segment_1.wav"
            mic = root / "audio" / "segment_1_mic.wav"
            mixed.parent.mkdir()
            mixed.write_bytes(b"mixed")
            mic.write_bytes(b"mic")
            segment = CallSegment(
                session_id=session_id,
                segment_number=1,
                audio_path="audio/segment_1.wav",
                mic_audio_path="audio/segment_1_mic.wav",
                system_audio_path="audio/missing_sys.wav",
            )
            transcribe = AsyncMock(return_value=1)
            with (
                patch("app.routers.retranscribe.data_dir", return_value=root),
                patch(
                    "app.routers.retranscribe.get_diarizer_runtime_config",
                    new=AsyncMock(
                        return_value=SimpleNamespace(speaker_similarity_threshold=0.68)
                    ),
                ),
                patch("app.routers.retranscribe._transcribe_audio_diarized", new=transcribe),
            ):
                total = await retranscribe._transcribe_stored_segments(
                    [segment],
                    session_id,
                    object(),
                    "model",
                )

        self.assertEqual(1, total)
        transcribe.assert_awaited_once_with(
            b"mixed",
            "wav",
            session_id,
            ANY,
            model_id="model",
        )


if __name__ == "__main__":
    unittest.main()

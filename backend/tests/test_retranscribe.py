import inspect
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

from app.models import CallSegment, Speaker, TranscriptEntry
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


class SplitTrackRetranscriptionTests(unittest.IsolatedAsyncioTestCase):
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
                    paths,
                    session_id,
                    object(),
                    "model",
                )

        self.assertEqual(4, total)
        self.assertEqual(4, transcribe.await_count)
        mic_calls = transcribe.await_args_list[0::2]
        system_calls = transcribe.await_args_list[1::2]
        self.assertTrue(all(item.kwargs["local_track"] for item in mic_calls))
        self.assertIs(mic_calls[0].kwargs["registry"], mic_calls[1].kwargs["registry"])
        self.assertIs(
            mic_calls[0].kwargs["auto_speaker_map"],
            mic_calls[1].kwargs["auto_speaker_map"],
        )
        self.assertIs(system_calls[0].kwargs["registry"], system_calls[1].kwargs["registry"])
        self.assertIs(
            system_calls[0].kwargs["auto_speaker_map"],
            system_calls[1].kwargs["auto_speaker_map"],
        )
        self.assertIsNot(
            mic_calls[0].kwargs["registry"],
            system_calls[0].kwargs["registry"],
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


if __name__ == "__main__":
    unittest.main()

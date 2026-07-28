import asyncio
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from app.routers.imports import _transcribe_audio_diarized, import_audio


class FakeUpload:
    filename = "recording.wav"

    async def read(self):
        return b"audio"


class AudioImportRuntimeBoundaryTests(unittest.TestCase):
    def test_only_audio_import_endpoint_disables_sortformer_probe(self):
        session_id = uuid.uuid4()
        db = object()

        with patch(
            "app.routers.imports._transcribe_audio_diarized",
            new=AsyncMock(return_value=1),
        ) as transcribe:
            asyncio.run(import_audio(session_id, FakeUpload(), db))

        transcribe.assert_awaited_once_with(
            b"audio",
            "wav",
            session_id,
            db,
            persist_audio=True,
            probe_sortformer=False,
        )

        with (
            patch("app.routers.imports.convert_to_pcm16", return_value=b"pcm"),
            patch(
                "app.routers.imports.get_diarizer_runtime_config",
                new=AsyncMock(side_effect=RuntimeError("stop after runtime config")),
            ) as runtime_config,
            self.assertRaisesRegex(RuntimeError, "stop after runtime config"),
        ):
            asyncio.run(_transcribe_audio_diarized(b"audio", "wav", session_id, db))

        runtime_config.assert_awaited_once_with(db, probe_sortformer=True)

    def test_conversion_and_diarization_run_off_event_loop_thread(self):
        session_id = uuid.uuid4()
        db = AsyncMock()
        query_result = Mock()
        query_result.scalars.return_value.all.return_value = []
        db.execute.return_value = query_result
        main_thread = threading.get_ident()
        worker_threads = []

        def convert(*_args):
            worker_threads.append(threading.get_ident())
            return b"pcm"

        def diarize(*_args):
            worker_threads.append(threading.get_ident())
            return []

        runtime = Mock(
            effective_live_diarizer="lightweight",
            speaker_similarity_threshold=0.68,
        )
        transcription = Mock(batch_model_id="local-whisper-base")
        with (
            patch("app.routers.imports.convert_to_pcm16", side_effect=convert),
            patch(
                "app.routers.imports.get_diarizer_runtime_config",
                new=AsyncMock(return_value=runtime),
            ),
            patch("app.routers.imports.create_diarizer", return_value=object()),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=transcription),
            ),
            patch("app.routers.imports.create_transcriber", return_value=object()),
            patch("app.routers.imports._diarize_pcm", side_effect=diarize),
            patch(
                "app.routers.imports._persist_diarized_segments",
                new=AsyncMock(return_value=0),
            ),
        ):
            asyncio.run(
                _transcribe_audio_diarized(
                    b"audio",
                    "wav",
                    session_id,
                    db,
                )
            )

        self.assertEqual(2, len(worker_threads))
        self.assertTrue(all(thread != main_thread for thread in worker_threads))


if __name__ == "__main__":
    unittest.main()

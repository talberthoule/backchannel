import asyncio
import threading
import unittest
import uuid
from unittest.mock import ANY, AsyncMock, Mock, patch

from fastapi import BackgroundTasks

from app.routers.imports import _diarize_pcm, _transcribe_audio_diarized, import_audio


class FakeUpload:
    filename = "recording.wav"

    async def read(self):
        return b"audio"


class AudioImportRuntimeBoundaryTests(unittest.TestCase):
    def test_audio_import_returns_a_queued_job_before_transcription_starts(self):
        session_id = uuid.uuid4()
        background_tasks = BackgroundTasks()
        transcribe = AsyncMock(return_value=1)

        with (
            patch("app.routers.imports._transcribe_audio_diarized", new=transcribe),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=Mock(batch_model_id="local-whisper-base")),
            ),
        ):
            result = asyncio.run(
                import_audio(session_id, FakeUpload(), background_tasks, object())
            )

        self.assertEqual("queued", result["status"])
        self.assertEqual("local-whisper-base", result["model_id"])
        self.assertEqual(1, len(background_tasks.tasks))
        transcribe.assert_not_awaited()

    def test_only_audio_import_endpoint_disables_sortformer_probe(self):
        session_id = uuid.uuid4()
        db = object()
        background_tasks = BackgroundTasks()

        class SessionContext:
            async def __aenter__(self):
                self.db = AsyncMock()
                return self.db

            async def __aexit__(self, *_args):
                return False

        with (
            patch(
                "app.routers.imports._transcribe_audio_diarized",
                new=AsyncMock(return_value=1),
            ) as transcribe,
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=Mock(batch_model_id="model")),
            ),
        ):
            asyncio.run(import_audio(session_id, FakeUpload(), background_tasks, db))
            with patch("app.routers.imports.async_session", return_value=SessionContext()):
                asyncio.run(background_tasks())

        transcribe.assert_awaited_once_with(
            b"audio",
            "wav",
            session_id,
            ANY,
            model_id="model",
            persist_audio=True,
            probe_sortformer=False,
            cancel_check=ANY,
            entry_callback=ANY,
            commit=False,
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
            patch(
                "app.routers.imports.create_diarizer",
                return_value=Mock(feed_audio=diarize),
            ),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=transcription),
            ),
            patch("app.routers.imports.create_transcriber", return_value=object()),
            patch("app.routers.imports.flush_diarizer_segments", return_value=[]),
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

        self.assertGreaterEqual(len(worker_threads), 2)
        self.assertTrue(all(thread != main_thread for thread in worker_threads))

    def test_each_diarizer_chunk_is_a_separate_event_loop_handoff(self):
        session_id = uuid.uuid4()
        db = AsyncMock()
        query_result = Mock()
        query_result.scalars.return_value.all.return_value = []
        db.execute.return_value = query_result
        pcm = b"x" * 6400
        diarizer = Mock()
        diarizer.feed_audio.return_value = []
        handed_off = []

        async def run_inline(function, *args):
            handed_off.append(function)
            return function(*args)

        with (
            patch("app.routers.imports.convert_to_pcm16", return_value=pcm),
            patch(
                "app.routers.imports.get_diarizer_runtime_config",
                new=AsyncMock(
                    return_value=Mock(
                        effective_live_diarizer="lightweight",
                        speaker_similarity_threshold=0.68,
                    )
                ),
            ),
            patch("app.routers.imports.create_diarizer", return_value=diarizer),
            patch("app.routers.imports.flush_diarizer_segments", return_value=[]),
            patch(
                "app.routers.imports.get_transcription_runtime_config",
                new=AsyncMock(return_value=Mock(batch_model_id="local-whisper-base")),
            ),
            patch("app.routers.imports.create_transcriber", return_value=object()),
            patch(
                "app.routers.imports._persist_diarized_segments",
                new=AsyncMock(return_value=0),
            ),
            patch("app.routers.imports.asyncio.to_thread", new=AsyncMock(side_effect=run_inline)),
        ):
            asyncio.run(_transcribe_audio_diarized(b"audio", "wav", session_id, db))

        feed_handoffs = [function for function in handed_off if function is diarizer.feed_audio]
        self.assertEqual(2, len(feed_handoffs))

    def test_a_flushed_segment_keeps_its_end_of_audio_fallback_position(self):
        diarizer = Mock()
        diarizer.feed_audio.return_value = []
        flushed = Mock(start_sample=None, pcm_bytes=b"x" * 3200)

        with patch(
            "app.routers.imports.flush_diarizer_segments",
            return_value=[flushed],
        ):
            result = asyncio.run(_diarize_pcm(b"x" * 6400, diarizer))

        self.assertEqual(1600, result[0].start_sample)


if __name__ == "__main__":
    unittest.main()

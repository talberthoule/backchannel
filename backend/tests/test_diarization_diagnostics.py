import io
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi import HTTPException, UploadFile

from app.routers.diagnostics import (
    MAX_BENCHMARK_SECONDS,
    MIN_BENCHMARK_SECONDS,
    delete_voice_profile,
    get_voice_profile_status,
    is_benchmark_pcm_too_short,
    is_enrollment_upload_too_large,
    is_supported_benchmark_audio_filename,
    replace_voice_profile,
    trim_benchmark_pcm,
)
from app.services.diarization_diagnostics import (
    BenchmarkMeasurement,
    classify_benchmark,
    probe_sortformer_environment,
)
from app.services.voice_enrollment import MAX_ENROLLMENT_UPLOAD_BYTES, VoiceEnrollmentError


class DiarizationDiagnosticsTests(unittest.TestCase):
    def test_benchmark_accepts_browser_recorded_webm_audio(self):
        self.assertTrue(is_supported_benchmark_audio_filename("mic-benchmark.webm"))

    def test_trim_benchmark_pcm_caps_audio_length(self):
        cap_bytes = MAX_BENCHMARK_SECONDS * 16000 * 2
        self.assertEqual(len(trim_benchmark_pcm(b"\x00" * (cap_bytes + 100))), cap_bytes)
        self.assertEqual(trim_benchmark_pcm(b"\x00" * 10), b"\x00" * 10)

    def test_benchmark_rejects_audio_shorter_than_one_live_window(self):
        min_bytes = MIN_BENCHMARK_SECONDS * 16000 * 2
        self.assertTrue(is_benchmark_pcm_too_short(b"\x00" * (min_bytes - 1)))
        self.assertFalse(is_benchmark_pcm_too_short(b"\x00" * min_bytes))
        self.assertEqual(MAX_BENCHMARK_SECONDS, MIN_BENCHMARK_SECONDS + 5)

    def test_probe_reports_unavailable_when_optional_imports_are_missing(self):
        def missing_import(_name: str):
            raise ImportError("missing")

        result = probe_sortformer_environment(import_module=missing_import)

        self.assertFalse(result.sortformer_available)
        self.assertFalse(result.torch_available)
        self.assertEqual(result.recommended_live_diarizer, "lightweight")

    def test_enrollment_upload_size_is_bounded(self):
        self.assertFalse(is_enrollment_upload_too_large(MAX_ENROLLMENT_UPLOAD_BYTES))
        self.assertTrue(is_enrollment_upload_too_large(MAX_ENROLLMENT_UPLOAD_BYTES + 1))

    def test_classify_benchmark_passes_fast_cuda_measurement(self):
        measurement = BenchmarkMeasurement(
            audio_seconds=60.0,
            processing_seconds=24.0,
            device="cuda",
            model_id="nvidia/diar_streaming_sortformer_4spk-v2",
        )

        result = classify_benchmark(measurement)

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.recommended_live_diarizer, "sortformer")
        self.assertAlmostEqual(result.real_time_factor, 0.4)

    def test_classify_benchmark_falls_back_for_slow_measurement(self):
        measurement = BenchmarkMeasurement(
            audio_seconds=60.0,
            processing_seconds=90.0,
            device="cpu",
            model_id="nvidia/diar_streaming_sortformer_4spk-v2",
        )

        result = classify_benchmark(measurement)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.recommended_live_diarizer, "lightweight")


class VoiceProfileEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_replacement_commits_only_after_extraction(self):
        file = UploadFile(filename="voice.webm", file=io.BytesIO(b"encoded"))
        db = AsyncMock()
        embedding = np.array([1.0, 0.0], dtype=np.float32)

        with (
            patch("app.routers.diagnostics.convert_to_pcm16", return_value=b"pcm"),
            patch(
                "app.routers.diagnostics.extract_enrollment_embedding",
                return_value=embedding,
            ),
            patch(
                "app.routers.diagnostics.save_local_voice_embedding",
                new=AsyncMock(),
            ) as save,
        ):
            result = await replace_voice_profile(file, db)

        self.assertEqual({"enrolled": True}, result)
        save.assert_awaited_once_with(db, embedding)
        db.commit.assert_awaited_once()

    async def test_failed_replacement_preserves_existing_profile(self):
        file = UploadFile(filename="voice.webm", file=io.BytesIO(b"encoded"))
        db = AsyncMock()

        with (
            patch("app.routers.diagnostics.convert_to_pcm16", return_value=b"pcm"),
            patch(
                "app.routers.diagnostics.extract_enrollment_embedding",
                side_effect=VoiceEnrollmentError("Voice sample must contain audible speech."),
            ),
            patch(
                "app.routers.diagnostics.save_local_voice_embedding",
                new=AsyncMock(),
            ) as save,
        ):
            with self.assertRaises(HTTPException) as raised:
                await replace_voice_profile(file, db)

        self.assertEqual(400, raised.exception.status_code)
        save.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_status_and_delete_never_return_embedding(self):
        db = AsyncMock()
        with patch(
            "app.routers.diagnostics.load_local_voice_embedding",
            new=AsyncMock(return_value=np.ones(2)),
        ):
            self.assertEqual({"enrolled": True}, await get_voice_profile_status(db))

        with patch(
            "app.routers.diagnostics.clear_local_voice_embedding",
            new=AsyncMock(),
        ) as clear:
            await delete_voice_profile(db)

        clear.assert_awaited_once_with(db)
        db.commit.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()

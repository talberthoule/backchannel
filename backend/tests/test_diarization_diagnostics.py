import io
import unittest
from unittest.mock import AsyncMock, Mock, patch

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
    SortformerEnvironment,
    _peak_memory_delta_mb,
    _sample_resident_memory,
    benchmark_sortformer_audio,
    classify_benchmark,
    probe_sortformer_environment,
)
from app.services.voice_enrollment import (
    MAX_ENROLLMENT_SECONDS,
    MAX_ENROLLMENT_UPLOAD_BYTES,
    VoiceEnrollmentError,
)


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
            processing_seconds=12.0,
            device="cuda",
            model_id="nvidia/diar_streaming_sortformer_4spk-v2",
        )

        result = classify_benchmark(measurement)

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.recommended_live_diarizer, "sortformer")
        self.assertAlmostEqual(result.real_time_factor, 0.2)

    def test_classify_benchmark_rejects_old_single_track_false_pass(self):
        measurement = BenchmarkMeasurement(
            audio_seconds=60.0,
            processing_seconds=36.0,
            device="cpu",
            model_id="nvidia/diar_streaming_sortformer_4spk-v2",
        )

        result = classify_benchmark(measurement)

        self.assertEqual("failed", result.status)
        self.assertAlmostEqual(0.9, result.contention_adjusted_real_time_factor)
        self.assertIn("1.67x realtime", result.reason)
        self.assertIn("3.0x required", result.reason)

    def test_classify_benchmark_warns_when_passing_margin_is_thin(self):
        measurement = BenchmarkMeasurement(
            audio_seconds=60.0,
            processing_seconds=19.0,
            device="cuda",
            model_id="nvidia/diar_streaming_sortformer_4spk-v2",
        )

        result = classify_benchmark(measurement)

        self.assertEqual("passed", result.status)
        self.assertIn("thin", result.reason.lower())

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

    def test_benchmark_replays_three_live_windows_with_one_model(self):
        environment = SortformerEnvironment(
            torch_available=True,
            sortformer_available=True,
            cuda_available=True,
            device="cuda",
            gpu_name="test-gpu",
            gpu_memory_gb=16.0,
            model_id="test-model",
            status="ready",
            recommended_live_diarizer="lightweight",
            reason="ready",
        )
        model = object()

        with (
            patch(
                "app.services.diarization_diagnostics._audio_duration_seconds",
                return_value=15.0,
            ),
            patch(
                "app.services.diarization_diagnostics.probe_sortformer_environment",
                return_value=environment,
            ),
            patch(
                "app.services.diarization_diagnostics._load_sortformer_model",
                return_value=model,
            ),
            patch("app.services.diarization_diagnostics._prepare_model") as prepare,
            patch("app.services.diarization_diagnostics._run_diarization") as run,
            patch(
                "app.services.diarization_diagnostics.time.perf_counter",
                side_effect=[0.0, 2.0, 2.0, 4.0, 4.0, 6.0],
            ),
            patch(
                "app.services.diarization_diagnostics._resident_memory_bytes",
                side_effect=[
                    100 * 1024 ** 2,
                    130 * 1024 ** 2,
                    160 * 1024 ** 2,
                    150 * 1024 ** 2,
                    140 * 1024 ** 2,
                ],
                create=True,
            ) as memory_probe,
            patch(
                "app.services.diarization_diagnostics._sample_resident_memory",
                side_effect=lambda _stop, samples: samples.append(160 * 1024 ** 2),
            ),
        ):
            result = benchmark_sortformer_audio("sample.wav")

        prepare.assert_called_once_with(model, "cuda")
        self.assertEqual(3, run.call_count)
        self.assertEqual(45.0, result.audio_seconds)
        self.assertEqual(6.0, result.processing_seconds)
        self.assertEqual(60.0, result.peak_memory_mb)
        self.assertEqual(5, memory_probe.call_count)

    def test_memory_footprint_is_unknown_when_rss_does_not_advance(self):
        self.assertIsNone(_peak_memory_delta_mb([100, 100, 100]))

    def test_memory_sampler_records_resident_memory_until_stopped(self):
        stop = Mock()
        stop.wait.side_effect = [False, False, True]
        samples = []

        with patch(
            "app.services.diarization_diagnostics._resident_memory_bytes",
            side_effect=[120, 140],
        ):
            _sample_resident_memory(stop, samples)

        self.assertEqual([120, 140], samples)


class VoiceProfileEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_replacement_commits_only_after_extraction(self):
        file = UploadFile(filename="voice.webm", file=io.BytesIO(b"encoded"))
        db = AsyncMock()
        embedding = np.array([1.0, 0.0], dtype=np.float32)

        with (
            patch("app.routers.diagnostics.convert_to_pcm16", return_value=b"pcm") as convert,
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
        convert.assert_called_once_with(
            b"encoded",
            "webm",
            max_seconds=MAX_ENROLLMENT_SECONDS,
        )
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

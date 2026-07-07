import unittest

from app.routers.diagnostics import is_supported_benchmark_audio_filename
from app.services.diarization_diagnostics import (
    BenchmarkMeasurement,
    classify_benchmark,
    probe_sortformer_environment,
)


class DiarizationDiagnosticsTests(unittest.TestCase):
    def test_benchmark_accepts_browser_recorded_webm_audio(self):
        self.assertTrue(is_supported_benchmark_audio_filename("mic-benchmark.webm"))

    def test_probe_reports_unavailable_when_optional_imports_are_missing(self):
        def missing_import(_name: str):
            raise ImportError("missing")

        result = probe_sortformer_environment(import_module=missing_import)

        self.assertFalse(result.sortformer_available)
        self.assertFalse(result.torch_available)
        self.assertEqual(result.recommended_live_diarizer, "lightweight")

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


if __name__ == "__main__":
    unittest.main()

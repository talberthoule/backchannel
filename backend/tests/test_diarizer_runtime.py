import asyncio
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import AppSetting
from app.services.diarization_diagnostics import BenchmarkResult, SortformerEnvironment
from app.services.diarizer_runtime import (
    SETTING_SELECTED_DIARIZER,
    SETTING_SORTFORMER_BENCHMARK_RTF,
    SETTING_SORTFORMER_BENCHMARK_STATUS,
    SETTING_SPEAKER_SIMILARITY_THRESHOLD,
    get_diarizer_runtime_config,
    record_sortformer_benchmark,
    set_speaker_similarity_threshold,
)


class FakeDb:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.commits = 0

    async def get(self, model, key):
        del model
        return self.settings.get(key)

    def add(self, setting):
        self.settings[setting.key] = setting

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


def _benchmark_result(status: str, rtf: float) -> BenchmarkResult:
    return BenchmarkResult(
        status=status,
        recommended_live_diarizer="lightweight",
        real_time_factor=rtf,
        audio_seconds=15.0,
        processing_seconds=0.0,
        device="cpu",
        model_id="test-model",
        threshold=0.6,
        reason="test",
    )


def _environment() -> SortformerEnvironment:
    return SortformerEnvironment(
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


class DiarizerRuntimeTests(unittest.TestCase):
    def test_lightweight_runtime_can_skip_sortformer_probe(self):
        db = FakeDb({
            SETTING_SELECTED_DIARIZER: AppSetting(
                key=SETTING_SELECTED_DIARIZER,
                value="lightweight",
            )
        })

        with patch(
            "app.services.diarizer_runtime.probe_sortformer_environment",
            side_effect=RuntimeError("Sortformer probe should be skipped"),
        ):
            runtime = asyncio.run(get_diarizer_runtime_config(db, probe_sortformer=False))

        self.assertEqual("lightweight", runtime.effective_live_diarizer)

    def test_sortformer_runtime_still_probes_when_probe_is_disabled(self):
        db = FakeDb({
            SETTING_SELECTED_DIARIZER: AppSetting(
                key=SETTING_SELECTED_DIARIZER,
                value="sortformer",
            )
        })

        with patch(
            "app.services.diarizer_runtime.probe_sortformer_environment",
            return_value=_environment(),
        ) as probe:
            asyncio.run(get_diarizer_runtime_config(db, probe_sortformer=False))

        probe.assert_called_once_with()

    def test_runtime_config_reads_stored_speaker_similarity_threshold(self):
        db = FakeDb({
            SETTING_SPEAKER_SIMILARITY_THRESHOLD: AppSetting(
                key=SETTING_SPEAKER_SIMILARITY_THRESHOLD,
                value="0.68",
            )
        })

        runtime = asyncio.run(get_diarizer_runtime_config(db, environment=_environment()))

        self.assertAlmostEqual(0.68, runtime.speaker_similarity_threshold)

    def test_runtime_surfaces_thin_benchmark_headroom(self):
        db = FakeDb({
            SETTING_SORTFORMER_BENCHMARK_STATUS: AppSetting(
                key=SETTING_SORTFORMER_BENCHMARK_STATUS,
                value="passed",
            ),
            SETTING_SORTFORMER_BENCHMARK_RTF: AppSetting(
                key=SETTING_SORTFORMER_BENCHMARK_RTF,
                value="0.32",
            ),
        })

        runtime = asyncio.run(
            get_diarizer_runtime_config(db, environment=_environment())
        )

        self.assertTrue(runtime.sortformer_selectable)
        self.assertIn("3.12x realtime", runtime.selection_reason)
        self.assertIn("3.0x required", runtime.selection_reason)
        self.assertIn("thin", runtime.selection_reason.lower())

    def test_set_speaker_similarity_threshold_persists_valid_value(self):
        db = FakeDb()

        runtime = asyncio.run(set_speaker_similarity_threshold(db, 0.66, environment=_environment()))

        self.assertAlmostEqual(0.66, runtime.speaker_similarity_threshold)
        self.assertEqual("0.66", db.settings[SETTING_SPEAKER_SIMILARITY_THRESHOLD].value)
        self.assertEqual(1, db.commits)

    def test_set_speaker_similarity_threshold_rejects_out_of_range_value(self):
        db = FakeDb()

        with self.assertRaises(ValueError):
            asyncio.run(set_speaker_similarity_threshold(db, 1.2, environment=_environment()))

    def test_record_benchmark_persists_finite_rtf(self):
        db = FakeDb()

        asyncio.run(record_sortformer_benchmark(db, _benchmark_result(status="passed", rtf=0.42)))

        self.assertEqual("passed", db.settings[SETTING_SORTFORMER_BENCHMARK_STATUS].value)
        self.assertEqual("0.42", db.settings[SETTING_SORTFORMER_BENCHMARK_RTF].value)
        self.assertEqual(1, db.commits)

    def test_record_benchmark_clears_rtf_when_not_finite(self):
        db = FakeDb({
            SETTING_SORTFORMER_BENCHMARK_RTF: AppSetting(
                key=SETTING_SORTFORMER_BENCHMARK_RTF,
                value="0.42",
            )
        })

        asyncio.run(record_sortformer_benchmark(db, _benchmark_result(status="unavailable", rtf=math.inf)))

        self.assertEqual("unavailable", db.settings[SETTING_SORTFORMER_BENCHMARK_STATUS].value)
        self.assertEqual("", db.settings[SETTING_SORTFORMER_BENCHMARK_RTF].value)

    def test_record_benchmark_persists_capacity_planner_measurements(self):
        db = FakeDb()
        result = SimpleNamespace(
            status="passed",
            real_time_factor=0.20,
            contention_adjusted_real_time_factor=0.30,
            peak_memory_mb=942.4,
        )

        asyncio.run(record_sortformer_benchmark(db, result))

        self.assertEqual(
            "0.3",
            db.settings[
                "diarization.sortformer.contention_adjusted_real_time_factor"
            ].value,
        )
        self.assertEqual(
            "942.4",
            db.settings["diarization.sortformer.peak_memory_mb"].value,
        )

    def test_runtime_config_treats_stored_non_finite_rtf_as_absent(self):
        db = FakeDb({
            SETTING_SORTFORMER_BENCHMARK_RTF: AppSetting(
                key=SETTING_SORTFORMER_BENCHMARK_RTF,
                value="inf",
            )
        })

        runtime = asyncio.run(get_diarizer_runtime_config(db, environment=_environment()))

        self.assertIsNone(runtime.benchmark_real_time_factor)

    def test_runtime_config_reads_capacity_planner_measurements(self):
        db = FakeDb({
            "diarization.sortformer.contention_adjusted_real_time_factor": AppSetting(
                key="diarization.sortformer.contention_adjusted_real_time_factor",
                value="0.30",
            ),
            "diarization.sortformer.peak_memory_mb": AppSetting(
                key="diarization.sortformer.peak_memory_mb",
                value="942.4",
            ),
        })

        runtime = asyncio.run(
            get_diarizer_runtime_config(db, environment=_environment())
        )

        self.assertEqual(0.30, runtime.benchmark_contention_adjusted_real_time_factor)
        self.assertEqual(942.4, runtime.benchmark_peak_memory_mb)


if __name__ == "__main__":
    unittest.main()

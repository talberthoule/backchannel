import asyncio
import json
import math
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.models import AppSetting
from app.services.diarization_diagnostics import BenchmarkResult, SortformerEnvironment
from app.services.diarizer_runtime import (
    SETTING_SELECTED_DIARIZER,
    SETTING_SORTFORMER_BENCHMARK_RTF,
    SETTING_SORTFORMER_BENCHMARK_STATUS,
    SETTING_SORTFORMER_LAST_RESULT,
    SETTING_SPEAKER_SIMILARITY_THRESHOLD,
    get_diarizer_runtime_config,
    record_sortformer_benchmark,
    set_speaker_similarity_threshold,
)
from app.services.fit_staleness import stamp_fit_record


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
        gpu_backend="cuda",
    )


def _stored_result(**overrides):
    result = {
        "real_time_factor": 0.20,
        "contention_adjusted_real_time_factor": 0.30,
        "peak_memory_mb": 942.4,
        **stamp_fit_record(
            {"model_id": "test-model", "endpoint_fingerprint": None},
            {
                "device": "cuda",
                "gpu_name": "test-gpu",
                "gpu_backend": "cuda",
                "gpu_memory_gb": 16.0,
            },
        ),
    }
    result.update(overrides)
    return AppSetting(key=SETTING_SORTFORMER_LAST_RESULT, value=json.dumps(result))


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
            SETTING_SORTFORMER_LAST_RESULT: _stored_result(real_time_factor=0.32),
        })

        runtime = asyncio.run(
            get_diarizer_runtime_config(db, environment=_environment())
        )

        self.assertTrue(runtime.sortformer_selectable)
        self.assertIn("3.12x realtime", runtime.selection_reason)
        self.assertIn("3.0x required", runtime.selection_reason)
        self.assertIn("thin", runtime.selection_reason.lower())

    def test_runtime_explains_when_a_saved_pass_no_longer_meets_the_requirement(self):
        db = FakeDb({
            SETTING_SELECTED_DIARIZER: AppSetting(
                key=SETTING_SELECTED_DIARIZER,
                value="sortformer",
            ),
            SETTING_SORTFORMER_LAST_RESULT: _stored_result(real_time_factor=0.60),
        })

        runtime = asyncio.run(
            get_diarizer_runtime_config(db, environment=_environment())
        )

        self.assertEqual("lightweight", runtime.effective_live_diarizer)
        self.assertIn("no longer meets", runtime.selection_reason)
        self.assertIn("1.67x realtime", runtime.selection_reason)
        self.assertIn("3.0x required", runtime.selection_reason)

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

        result = _benchmark_result(status="passed", rtf=0.42)
        result = result.__class__(**{**result.__dict__, "contention_adjusted_real_time_factor": 0.5, "peak_memory_mb": 100.0})
        asyncio.run(record_sortformer_benchmark(db, result, _environment()))

        stored = json.loads(db.settings[SETTING_SORTFORMER_LAST_RESULT].value)
        self.assertEqual(0.42, stored["real_time_factor"])
        self.assertEqual(1, stored["schema_version"])
        self.assertEqual(1, db.commits)

    def test_record_benchmark_clears_rtf_when_not_finite(self):
        db = FakeDb({
            SETTING_SORTFORMER_BENCHMARK_RTF: AppSetting(
                key=SETTING_SORTFORMER_BENCHMARK_RTF,
                value="0.42",
            )
        })

        asyncio.run(record_sortformer_benchmark(db, _benchmark_result(status="unavailable", rtf=math.inf), _environment()))
        stored = json.loads(db.settings[SETTING_SORTFORMER_LAST_RESULT].value)
        self.assertIsNone(stored["real_time_factor"])

    def test_record_benchmark_persists_capacity_planner_measurements(self):
        db = FakeDb()
        result = SimpleNamespace(
            status="passed",
            real_time_factor=0.20,
            contention_adjusted_real_time_factor=0.30,
            peak_memory_mb=942.4,
            model_id="test-model",
        )

        asyncio.run(record_sortformer_benchmark(db, result, _environment()))
        stored = json.loads(db.settings[SETTING_SORTFORMER_LAST_RESULT].value)
        self.assertEqual(0.3, stored["contention_adjusted_real_time_factor"])
        self.assertEqual(942.4, stored["peak_memory_mb"])

    def test_record_benchmark_retains_higher_peak_memory_from_a_cold_run(self):
        db = FakeDb({SETTING_SORTFORMER_LAST_RESULT: _stored_result()})
        result = SimpleNamespace(
            status="passed",
            real_time_factor=0.20,
            contention_adjusted_real_time_factor=0.30,
            peak_memory_mb=100.0,
            model_id="test-model",
        )

        asyncio.run(record_sortformer_benchmark(db, result, _environment()))
        stored = json.loads(db.settings[SETTING_SORTFORMER_LAST_RESULT].value)
        self.assertEqual(942.4, stored["peak_memory_mb"])

    def test_peak_memory_resets_when_host_changes(self):
        old = _stored_result()
        db = FakeDb({SETTING_SORTFORMER_LAST_RESULT: old})
        changed = SortformerEnvironment(
            **{**_environment().__dict__, "gpu_name": "new-gpu"}
        )
        result = SimpleNamespace(
            real_time_factor=0.20,
            contention_adjusted_real_time_factor=0.30,
            peak_memory_mb=100.0,
            model_id="test-model",
        )
        asyncio.run(record_sortformer_benchmark(db, result, changed))
        stored = json.loads(db.settings[SETTING_SORTFORMER_LAST_RESULT].value)
        self.assertEqual(100.0, stored["peak_memory_mb"])

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
            SETTING_SORTFORMER_LAST_RESULT: _stored_result(),
        })

        runtime = asyncio.run(
            get_diarizer_runtime_config(db, environment=_environment())
        )

        self.assertEqual(0.30, runtime.benchmark_contention_adjusted_real_time_factor)
        self.assertEqual(942.4, runtime.benchmark_peak_memory_mb)

    def test_legacy_scalar_record_is_incompatible_and_gate_is_closed(self):
        db = FakeDb({
            SETTING_SORTFORMER_BENCHMARK_RTF: AppSetting(
                key=SETTING_SORTFORMER_BENCHMARK_RTF, value="0.20"
            )
        })
        runtime = asyncio.run(get_diarizer_runtime_config(db, environment=_environment()))
        self.assertEqual("incompatible", runtime.benchmark_validity)
        self.assertFalse(runtime.sortformer_selectable)

    def test_current_record_missing_required_measurement_keeps_gate_closed(self):
        db = FakeDb({
            SETTING_SORTFORMER_LAST_RESULT: _stored_result(
                contention_adjusted_real_time_factor=None
            )
        })
        runtime = asyncio.run(get_diarizer_runtime_config(db, environment=_environment()))
        self.assertEqual("incompatible", runtime.benchmark_validity)
        self.assertFalse(runtime.sortformer_selectable)

    def test_hardware_change_supersedes_record_and_keeps_gate_closed(self):
        record = json.loads(_stored_result().value)
        record["host"]["gpu_name"] = "old-gpu"
        db = FakeDb({
            SETTING_SORTFORMER_LAST_RESULT: AppSetting(
                key=SETTING_SORTFORMER_LAST_RESULT, value=json.dumps(record)
            )
        })
        runtime = asyncio.run(get_diarizer_runtime_config(db, environment=_environment()))
        self.assertEqual("superseded", runtime.benchmark_validity)
        self.assertFalse(runtime.sortformer_selectable)
        self.assertIn("old-gpu", runtime.benchmark_validity_reason)

    def test_aged_record_stays_selectable(self):
        record = json.loads(_stored_result().value)
        record["measured_at"] = datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()
        db = FakeDb({
            SETTING_SORTFORMER_LAST_RESULT: AppSetting(
                key=SETTING_SORTFORMER_LAST_RESULT, value=json.dumps(record)
            )
        })
        runtime = asyncio.run(get_diarizer_runtime_config(db, environment=_environment()))
        self.assertEqual("aged", runtime.benchmark_validity)
        self.assertTrue(runtime.sortformer_selectable)


if __name__ == "__main__":
    unittest.main()

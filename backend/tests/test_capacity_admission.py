"""Call-start capacity admission wiring (ALP-156, first increment).

Covers machine-budget detection and the assembly of the diarization demand from
the persisted ALP-155 benchmark fields, including the honest coverage reporting
that keeps a partial verdict from reading as a complete pass.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.capacity_admission import (
    DEFAULT_MEMORY_LIMIT_MB,
    CapacityAssessment,
    assess_call_capacity,
    detect_machine_budget,
)
from app.services.capacity_planner import MachineBudget, STATUS_OVER_BUDGET
from app.services.diarizer_selection import DIARIZER_LIGHTWEIGHT, DIARIZER_SORTFORMER


def _diarizer(
    effective: str = DIARIZER_SORTFORMER,
    contention_rtf: float | None = 0.3,
    peak_memory_mb: float | None = 300.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        effective_live_diarizer=effective,
        benchmark_contention_adjusted_real_time_factor=contention_rtf,
        benchmark_peak_memory_mb=peak_memory_mb,
    )


class DetectMachineBudgetTests(unittest.TestCase):
    def test_cores_are_total_minus_the_reserve(self):
        with mock.patch("app.services.capacity_admission.os.cpu_count", return_value=8):
            budget = detect_machine_budget(memory_limit_mb=4096)
        self.assertEqual(7.0, budget.usable_cores)
        self.assertEqual(4096, budget.memory_limit_mb)

    def test_a_single_core_machine_never_drops_below_one_usable_core(self):
        with mock.patch("app.services.capacity_admission.os.cpu_count", return_value=1):
            budget = detect_machine_budget(memory_limit_mb=2048)
        self.assertEqual(1.0, budget.usable_cores)

    def test_memory_falls_back_to_the_default_when_no_cgroup_limit(self):
        with mock.patch(
            "app.services.capacity_admission._container_memory_limit_mb", return_value=None
        ), mock.patch("app.services.capacity_admission.os.cpu_count", return_value=4):
            budget = detect_machine_budget()
        self.assertEqual(DEFAULT_MEMORY_LIMIT_MB, budget.memory_limit_mb)


class AssessCallCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_sortformer_diarization_is_modelled_from_the_benchmark(self):
        with mock.patch(
            "app.services.capacity_admission.get_diarizer_runtime_config",
            new=mock.AsyncMock(return_value=_diarizer(contention_rtf=0.3, peak_memory_mb=300.0)),
        ):
            assessment = await assess_call_capacity(
                db=None,
                track_count=2,
                budget=MachineBudget(usable_cores=8, memory_limit_mb=8192),
            )
        self.assertIsInstance(assessment, CapacityAssessment)
        self.assertIn("diarization_sortformer", assessment.modelled)
        # 2 tracks * 0.3 contention-adjusted RTF = 0.6 cores of demand.
        self.assertAlmostEqual(0.6, assessment.verdict.cpu_demand_cores)
        # 2 * 300 MB of model footprint.
        self.assertAlmostEqual(600.0, assessment.verdict.memory_demand_mb)
        self.assertTrue(assessment.partial)  # ASR/captioner/text still unmodelled

    async def test_a_dual_track_sortformer_config_can_be_refused(self):
        with mock.patch(
            "app.services.capacity_admission.get_diarizer_runtime_config",
            new=mock.AsyncMock(return_value=_diarizer(contention_rtf=1.05, peak_memory_mb=900.0)),
        ):
            assessment = await assess_call_capacity(
                db=None,
                track_count=2,
                budget=MachineBudget(usable_cores=1, memory_limit_mb=500),
            )
        self.assertEqual(STATUS_OVER_BUDGET, assessment.verdict.status)
        self.assertFalse(assessment.verdict.admits())
        self.assertGreater(len(assessment.verdict.reasons), 0)

    async def test_lightweight_diarizer_is_reported_unmodelled_not_guessed(self):
        with mock.patch(
            "app.services.capacity_admission.get_diarizer_runtime_config",
            new=mock.AsyncMock(return_value=_diarizer(effective=DIARIZER_LIGHTWEIGHT)),
        ):
            assessment = await assess_call_capacity(
                db=None,
                budget=MachineBudget(usable_cores=8, memory_limit_mb=8192),
            )
        self.assertNotIn("diarization_sortformer", assessment.modelled)
        self.assertTrue(any("lightweight" in note for note in assessment.not_modelled))
        self.assertEqual(0.0, assessment.verdict.cpu_demand_cores)

    async def test_missing_benchmark_rtf_leaves_diarization_unmodelled(self):
        with mock.patch(
            "app.services.capacity_admission.get_diarizer_runtime_config",
            new=mock.AsyncMock(return_value=_diarizer(contention_rtf=None)),
        ):
            assessment = await assess_call_capacity(
                db=None,
                budget=MachineBudget(usable_cores=8, memory_limit_mb=8192),
            )
        self.assertNotIn("diarization_sortformer", assessment.modelled)

    async def test_to_dict_exposes_status_coverage_and_headroom(self):
        with mock.patch(
            "app.services.capacity_admission.get_diarizer_runtime_config",
            new=mock.AsyncMock(return_value=_diarizer()),
        ):
            assessment = await assess_call_capacity(
                db=None,
                budget=MachineBudget(usable_cores=8, memory_limit_mb=8192),
            )
        payload = assessment.to_dict()
        self.assertIn("status", payload)
        self.assertIn("cpu_headroom_cores", payload)
        self.assertTrue(payload["partial"])
        self.assertTrue(payload["not_modelled"])
        self.assertIn("machine_budget", payload["modelled"])


if __name__ == "__main__":
    unittest.main()

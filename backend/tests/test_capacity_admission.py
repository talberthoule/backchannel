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


def _agent(
    slug: str,
    model_id: str,
    *,
    enabled: bool = True,
    interval_seconds: int | None = None,
    model_intervals: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        slug=slug,
        model_id=model_id,
        enabled=enabled,
        interval_seconds=interval_seconds,
        model_intervals=model_intervals,
    )


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _AgentDb:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _query):
        return _Rows(self.rows)


def _fit_result(
    *,
    asr_models: list[dict] | None = None,
    text_models: list[dict] | None = None,
    contention: float | None = 1.5,
) -> dict:
    return {
        "contention": contention,
        "asr": {"asr_models": asr_models or []},
        "text_models": text_models or [],
    }


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
    async def _assess(
        self,
        *,
        fit_result: dict | None,
        rows: list[SimpleNamespace],
        batch_model_id: str = "local-parakeet-tdt-0.6b",
        live_model_id: str = "gemini-live",
        local_text_model_ids: tuple[str, ...] = (),
        diarizer: SimpleNamespace | None = None,
        budget: MachineBudget | None = None,
    ) -> CapacityAssessment:
        runtime = SimpleNamespace(
            batch_model_id=batch_model_id,
            live_preview_model_id=live_model_id,
        )
        local_models = [{"id": model_id} for model_id in local_text_model_ids]
        with (
            mock.patch(
                "app.services.capacity_admission.get_diarizer_runtime_config",
                new=mock.AsyncMock(
                    return_value=diarizer
                    or _diarizer(effective=DIARIZER_LIGHTWEIGHT)
                ),
            ),
            mock.patch(
                "app.services.local_fit.load_local_fit_result",
                new=mock.AsyncMock(return_value=fit_result),
            ),
            mock.patch(
                "app.services.local_fit.local_text_models",
                new=mock.AsyncMock(return_value=local_models),
            ),
            mock.patch(
                "app.services.transcription_runtime.get_transcription_runtime_config",
                new=mock.AsyncMock(return_value=runtime),
            ),
        ):
            return await assess_call_capacity(
                db=_AgentDb(rows),
                track_count=2,
                budget=budget or MachineBudget(usable_cores=8, memory_limit_mb=8192),
            )

    async def test_sortformer_diarization_is_modelled_from_the_benchmark(self):
        assessment = await self._assess(
            fit_result=None,
            rows=[],
            diarizer=_diarizer(contention_rtf=0.3, peak_memory_mb=300.0),
        )
        self.assertIsInstance(assessment, CapacityAssessment)
        self.assertIn("diarization_sortformer", assessment.modelled)
        # 2 tracks * 0.3 contention-adjusted RTF = 0.6 cores of demand.
        self.assertAlmostEqual(0.6, assessment.verdict.cpu_demand_cores)
        # 2 * 300 MB of model footprint.
        self.assertAlmostEqual(600.0, assessment.verdict.memory_demand_mb)
        self.assertTrue(assessment.partial)  # ASR/captioner/text still unmodelled

    async def test_a_dual_track_sortformer_config_can_be_refused(self):
        assessment = await self._assess(
            fit_result=None,
            rows=[],
            diarizer=_diarizer(contention_rtf=1.05, peak_memory_mb=900.0),
            budget=MachineBudget(usable_cores=0.85, memory_limit_mb=500),
        )
        self.assertEqual(STATUS_OVER_BUDGET, assessment.verdict.status)
        self.assertFalse(assessment.verdict.admits())
        self.assertGreater(len(assessment.verdict.reasons), 0)

    async def test_lightweight_diarizer_is_reported_unmodelled_not_guessed(self):
        assessment = await self._assess(
            fit_result=None,
            rows=[],
            diarizer=_diarizer(effective=DIARIZER_LIGHTWEIGHT),
        )
        self.assertNotIn("diarization_sortformer", assessment.modelled)
        self.assertTrue(any("lightweight" in note for note in assessment.not_modelled))
        self.assertEqual(0.0, assessment.verdict.cpu_demand_cores)

    async def test_missing_benchmark_rtf_leaves_diarization_unmodelled(self):
        assessment = await self._assess(
            fit_result=None,
            rows=[],
            diarizer=_diarizer(contention_rtf=None),
        )
        self.assertNotIn("diarization_sortformer", assessment.modelled)

    async def test_stale_sortformer_benchmark_requests_a_rerun(self):
        expected = (
            "diarization: the Sortformer benchmark is stale; re-run it to "
            "capture contention and memory"
        )
        for missing_field, diarizer in (
            (
                "contention_adjusted_real_time_factor",
                _diarizer(contention_rtf=None),
            ),
            ("peak_memory_mb", _diarizer(peak_memory_mb=None)),
        ):
            with self.subTest(missing_field=missing_field):
                assessment = await self._assess(
                    fit_result=None,
                    rows=[],
                    diarizer=diarizer,
                )
            self.assertIn(expected, assessment.not_modelled)
            self.assertNotIn("diarization_sortformer", assessment.modelled)

    async def test_to_dict_exposes_status_coverage_and_headroom(self):
        assessment = await self._assess(
            fit_result=None,
            rows=[],
            diarizer=_diarizer(),
        )
        payload = assessment.to_dict()
        self.assertIn("status", payload)
        self.assertIn("cpu_headroom_cores", payload)
        self.assertTrue(payload["partial"])
        self.assertTrue(payload["not_modelled"])
        self.assertIn("machine_budget", payload["modelled"])

    async def test_batch_asr_uses_the_configured_models_stored_rtf(self):
        assessment = await self._assess(
            fit_result=_fit_result(
                asr_models=[
                    {
                        "model_id": "local-parakeet-tdt-0.6b",
                        "status": "ok",
                        "real_time_factor": 0.2,
                        "short_real_time_factor": 0.1,
                    }
                ]
            ),
            rows=[],
        )

        # 0.2 measured RTF * 1.5 contention * 0.6 speech fraction.
        self.assertAlmostEqual(0.18, assessment.verdict.cpu_demand_cores)
        self.assertIn("batch_asr:local-parakeet-tdt-0.6b", assessment.modelled)
        self.assertFalse(any(note.startswith("batch_asr:") for note in assessment.not_modelled))

    async def test_local_captioner_uses_the_stored_short_window_rtf(self):
        assessment = await self._assess(
            fit_result=_fit_result(
                asr_models=[
                    {
                        "model_id": "local-parakeet-tdt-0.6b",
                        "status": "ok",
                        "real_time_factor": 0.2,
                        "short_real_time_factor": 0.1,
                        "live_feasibility": "feasible",
                    }
                ]
            ),
            rows=[
                _agent("audio_gateway", "local-parakeet-live", enabled=True),
            ],
            batch_model_id="gemini-3.5-flash-lite",
            live_model_id="local-parakeet-live",
        )

        # 0.1 short-window RTF * 1.5 contention.
        self.assertAlmostEqual(0.15, assessment.verdict.cpu_demand_cores)
        self.assertIn("live_captioner:local-parakeet-live", assessment.modelled)
        self.assertFalse(
            any(note.startswith("live_captioner:") for note in assessment.not_modelled)
        )

    async def test_text_agent_uses_measured_latency_and_model_specific_interval(self):
        model_id = "endpoint:lm-studio:qwen"
        assessment = await self._assess(
            fit_result=_fit_result(
                text_models=[
                    {
                        "model_id": model_id,
                        "status": "ok",
                        "roles": [
                            {
                                "slug": "consolidated_analyst",
                                "latency_seconds": 8.0,
                            }
                        ],
                    }
                ]
            ),
            rows=[
                _agent(
                    "consolidated_analyst",
                    model_id,
                    interval_seconds=40,
                    model_intervals=f'{{"{model_id}": 80}}',
                )
            ],
            batch_model_id="gemini-3.5-flash-lite",
            local_text_model_ids=(model_id,),
        )

        # One measured 8s call * 1.5 contention every effective 80s interval.
        self.assertAlmostEqual(0.15, assessment.verdict.cpu_demand_cores)
        self.assertIn("text_agent:consolidated_analyst", assessment.modelled)
        role_fit = next(
            fit for fit in assessment.verdict.role_fits
            if fit.role == "consolidated_analyst"
        )
        self.assertIsNone(role_fit.context_window)
        self.assertIsNone(role_fit.context_fits)
        self.assertTrue(
            any(
                "consolidated_analyst" in note and "context window" in note
                for note in assessment.not_modelled
            )
        )

    async def test_missing_measurements_remain_explicitly_unmodelled(self):
        model_id = "endpoint:lm-studio:qwen"
        assessment = await self._assess(
            fit_result=_fit_result(),
            rows=[
                _agent("audio_gateway", "local-parakeet-live"),
                _agent("consolidated_analyst", model_id, interval_seconds=40),
            ],
            live_model_id="local-parakeet-live",
            local_text_model_ids=(model_id,),
        )

        self.assertEqual(0.0, assessment.verdict.cpu_demand_cores)
        for component in (
            "batch_asr:local-parakeet-tdt-0.6b",
            "live_captioner:local-parakeet-live",
            "text_agent:consolidated_analyst",
        ):
            with self.subTest(component=component):
                self.assertTrue(
                    any(note.startswith(component) for note in assessment.not_modelled)
                )

    async def test_real_machine_shape_has_nonzero_modelled_demand(self):
        model_id = "endpoint:lm-studio:qwen"
        assessment = await self._assess(
            fit_result=_fit_result(
                asr_models=[
                    {
                        "model_id": "local-parakeet-tdt-0.6b",
                        "status": "ok",
                        "real_time_factor": 0.2,
                        "short_real_time_factor": 0.1,
                        "live_feasibility": "feasible",
                    }
                ],
                text_models=[
                    {
                        "model_id": model_id,
                        "status": "ok",
                        "roles": [
                            {
                                "slug": "consolidated_analyst",
                                "latency_seconds": 8.0,
                            },
                            {
                                "slug": "objection_handler",
                                "latency_seconds": 2.0,
                            },
                        ],
                    }
                ],
            ),
            rows=[
                _agent("audio_gateway", "local-parakeet-live"),
                _agent("consolidated_analyst", model_id, interval_seconds=40),
                _agent("objection_handler", model_id, interval_seconds=10),
            ],
            live_model_id="local-parakeet-live",
            local_text_model_ids=(model_id,),
            diarizer=_diarizer(contention_rtf=0.3, peak_memory_mb=300.0),
        )

        self.assertGreater(assessment.verdict.cpu_demand_cores, 0.0)
        self.assertGreater(assessment.verdict.memory_demand_mb, 0.0)
        for component in (
            "diarization_sortformer",
            "batch_asr:local-parakeet-tdt-0.6b",
            "live_captioner:local-parakeet-live",
            "text_agent:consolidated_analyst",
            "text_agent:objection_handler",
        ):
            with self.subTest(component=component):
                self.assertIn(component, assessment.modelled)


if __name__ == "__main__":
    unittest.main()

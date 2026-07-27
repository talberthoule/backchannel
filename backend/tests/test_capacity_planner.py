"""The aggregate local resource budget planning core (ALP-156).

These exercise the pure planner: measured headroom on two budget dimensions plus
the per-role context-window fit, the ratified degradation order, and the
worked 2026-07-27 example that motivated the whole design.
"""

import math
import unittest

from app.services.capacity_planner import (
    BatchAsrDemand,
    CaptionerDemand,
    CONSUMER_LOCAL_OFF_PROCESS,
    CONSUMER_REMOTE,
    DEGRADATION_ORDER,
    DiarizationDemand,
    MachineBudget,
    STATUS_OK,
    STATUS_OVER_BUDGET,
    STATUS_THIN,
    TextAgentDemand,
    plan_capacity,
)


def _comfortable_budget() -> MachineBudget:
    return MachineBudget(usable_cores=8, memory_limit_mb=8192, overhead_mb=200)


class DiarizationDemandTests(unittest.TestCase):
    def test_track_count_multiplies_cpu_and_memory(self):
        single = DiarizationDemand(track_count=1, per_track_rtf=0.5, per_instance_memory_mb=400)
        dual = DiarizationDemand(track_count=2, per_track_rtf=0.5, per_instance_memory_mb=400)
        self.assertEqual(0.5, single.cpu_cores())
        self.assertEqual(1.0, dual.cpu_cores())
        self.assertEqual(400, single.memory_mb())
        self.assertEqual(800, dual.memory_mb())

    def test_missing_memory_footprint_reads_as_zero_not_a_crash(self):
        demand = DiarizationDemand(track_count=2, per_track_rtf=0.4, per_instance_memory_mb=None)
        self.assertEqual(0.0, demand.memory_mb())


class TextAgentDemandTests(unittest.TestCase):
    def test_remote_endpoint_costs_no_local_cpu(self):
        remote = TextAgentDemand(
            role="analyst",
            prompt_tokens=2000,
            reserved_output_tokens=800,
            tokens_per_second=40,
            context_window=8000,
            interval_seconds=40,
            location=CONSUMER_REMOTE,
        )
        self.assertEqual(0.0, remote.cpu_cores())

    def test_loopback_endpoint_costs_local_cpu(self):
        local = TextAgentDemand(
            role="analyst",
            prompt_tokens=2000,
            reserved_output_tokens=800,
            tokens_per_second=40,
            context_window=8000,
            interval_seconds=40,
            location=CONSUMER_LOCAL_OFF_PROCESS,
        )
        # (2000 + 800) / 40 = 70s per call, once every 40s => 1.75 cores.
        self.assertAlmostEqual(1.75, local.cpu_cores())

    def test_one_shot_role_adds_no_sustained_cpu_but_is_still_checked(self):
        arbiter = TextAgentDemand(
            role="brief_arbiter",
            prompt_tokens=10000,
            reserved_output_tokens=2000,
            tokens_per_second=40,
            context_window=8000,
            interval_seconds=0,
            one_shot=True,
        )
        self.assertEqual(0.0, arbiter.cpu_cores())
        self.assertFalse(arbiter.context_fits())
        self.assertEqual(12000, arbiter.needed_context_tokens())

    def test_context_and_latency_fit(self):
        agent = TextAgentDemand(
            role="lens",
            prompt_tokens=1000,
            reserved_output_tokens=1000,
            tokens_per_second=10,
            context_window=8000,
            timeout_seconds=120,
            one_shot=True,
        )
        self.assertTrue(agent.context_fits())
        # 2000 / 10 = 200s against a 120s timeout.
        self.assertFalse(agent.latency_fits())

    def test_zero_throughput_is_infinite_latency_not_a_crash(self):
        agent = TextAgentDemand(
            role="lens",
            prompt_tokens=1000,
            reserved_output_tokens=1000,
            tokens_per_second=0,
            context_window=8000,
        )
        self.assertFalse(math.isfinite(agent.projected_call_seconds()))
        self.assertFalse(agent.latency_fits())


class PlanCapacityTests(unittest.TestCase):
    def test_a_light_configuration_is_admitted_cleanly(self):
        verdict = plan_capacity(
            _comfortable_budget(),
            diarization=DiarizationDemand(track_count=1, per_track_rtf=0.3, per_instance_memory_mb=300),
            batch_asr=BatchAsrDemand(real_time_factor=0.3, speech_fraction=0.5, memory_mb=300),
        )
        self.assertEqual(STATUS_OK, verdict.status)
        self.assertTrue(verdict.admits())
        self.assertGreater(verdict.cpu_headroom_cores, 0)
        self.assertEqual((), verdict.degradation_plan)

    def test_the_2026_07_27_configuration_is_refused_with_a_measured_shortfall(self):
        budget = MachineBudget(usable_cores=4, memory_limit_mb=4096, overhead_mb=200)
        verdict = plan_capacity(
            budget,
            diarization=DiarizationDemand(track_count=2, per_track_rtf=1.05, per_instance_memory_mb=900),
            batch_asr=BatchAsrDemand(real_time_factor=0.5, speech_fraction=0.6, memory_mb=500),
            captioner=CaptionerDemand(real_time_factor=0.5, memory_mb=0.0),
            text_agents=[
                TextAgentDemand(
                    role="consolidated_analyst",
                    prompt_tokens=2000,
                    reserved_output_tokens=800,
                    tokens_per_second=40,
                    context_window=8000,
                    interval_seconds=40,
                ),
                TextAgentDemand(
                    role="brief_arbiter",
                    prompt_tokens=10000,
                    reserved_output_tokens=2000,
                    tokens_per_second=40,
                    context_window=8000,
                    one_shot=True,
                ),
            ],
        )
        self.assertEqual(STATUS_OVER_BUDGET, verdict.status)
        self.assertFalse(verdict.admits())
        self.assertGreater(verdict.cpu_load_multiple, 1.0)
        # The override must state the measured shortfall, per role for the arbiter.
        self.assertTrue(any("brief_arbiter" in r and "will not fit" in r for r in verdict.reasons))
        # Ratified degradation order, only the applicable levers.
        self.assertEqual(
            (
                "Drop live interim captions",
                "Widen text-agent intervals",
                "Shed oldest diarization audio",
            ),
            verdict.degradation_plan,
        )

    def test_a_context_overflow_alone_is_a_hard_refusal(self):
        verdict = plan_capacity(
            _comfortable_budget(),
            text_agents=[
                TextAgentDemand(
                    role="brief_arbiter",
                    prompt_tokens=10000,
                    reserved_output_tokens=2000,
                    tokens_per_second=40,
                    context_window=8000,
                    one_shot=True,
                )
            ],
        )
        self.assertEqual(STATUS_OVER_BUDGET, verdict.status)
        self.assertEqual(1, len(verdict.role_fits))
        self.assertFalse(verdict.role_fits[0].context_fits)

    def test_a_latency_overrun_warns_but_does_not_hard_block(self):
        verdict = plan_capacity(
            _comfortable_budget(),
            text_agents=[
                TextAgentDemand(
                    role="brief_meeting_lens",
                    prompt_tokens=1000,
                    reserved_output_tokens=1000,
                    tokens_per_second=10,
                    context_window=8000,
                    timeout_seconds=120,
                    one_shot=True,
                )
            ],
        )
        self.assertEqual(STATUS_THIN, verdict.status)
        self.assertTrue(verdict.admits())
        self.assertTrue(any("brief_meeting_lens" in r for r in verdict.reasons))

    def test_memory_can_be_over_budget_while_cpu_is_fine(self):
        budget = MachineBudget(usable_cores=8, memory_limit_mb=2048, overhead_mb=200)
        verdict = plan_capacity(
            budget,
            diarization=DiarizationDemand(track_count=2, per_track_rtf=0.3, per_instance_memory_mb=900),
            batch_asr=BatchAsrDemand(real_time_factor=0.3, speech_fraction=0.5, memory_mb=500),
        )
        self.assertEqual(STATUS_OVER_BUDGET, verdict.status)
        self.assertGreater(verdict.cpu_headroom_cores, 0)
        self.assertLess(verdict.memory_headroom_mb, 0)
        self.assertTrue(any("memory" in r.lower() for r in verdict.reasons))

    def test_memory_only_breach_plan_omits_levers_that_do_not_relieve_memory(self):
        budget = MachineBudget(usable_cores=8, memory_limit_mb=2048, overhead_mb=200)
        verdict = plan_capacity(
            budget,
            diarization=DiarizationDemand(track_count=2, per_track_rtf=0.3, per_instance_memory_mb=900),
            batch_asr=BatchAsrDemand(real_time_factor=0.3, speech_fraction=0.5, memory_mb=500),
            text_agents=[
                TextAgentDemand(
                    role="consolidated_analyst",
                    prompt_tokens=1000,
                    reserved_output_tokens=400,
                    tokens_per_second=200,
                    context_window=8000,
                    interval_seconds=40,
                )
            ],
        )
        # No captioner and a cpu-only lever must not appear for a memory breach.
        self.assertIn("Shed oldest diarization audio", verdict.degradation_plan)
        self.assertNotIn("Widen text-agent intervals", verdict.degradation_plan)
        self.assertNotIn("Drop live interim captions", verdict.degradation_plan)

    def test_disabled_captioner_costs_nothing(self):
        captioner = CaptionerDemand(real_time_factor=0.9, memory_mb=400, enabled=False)
        self.assertEqual(0.0, captioner.cpu_cores())
        self.assertEqual(0.0, captioner.memory_mb_value())


class DegradationOrderTests(unittest.TestCase):
    def test_protected_levers_are_last_and_never_planned(self):
        keys = [lever.key for lever in DEGRADATION_ORDER]
        self.assertEqual(
            ["live_captions", "text_agent_cadence", "diarization_detail", "batch_transcript", "call_liveness"],
            keys,
        )
        protected = [lever.key for lever in DEGRADATION_ORDER if lever.protected]
        self.assertEqual(["batch_transcript", "call_liveness"], protected)


if __name__ == "__main__":
    unittest.main()

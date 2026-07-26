import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.local_fit import (
    GREEN,
    MAX_INTERVAL,
    MIN_INTERVAL,
    RED,
    YELLOW,
    ProfileLatency,
    TextModelFit,
    apply_recommended_intervals,
    benchmark_text_model,
    classify_latency,
    recommend_interval,
    score_text_model,
    validate_interval_updates,
)


class ClassifyLatencyTests(unittest.TestCase):
    def test_comfortable_headroom_is_green(self):
        # Half the budget or less: green (ratio <= 0.5).
        self.assertEqual(classify_latency(5.0, 10), GREEN)
        self.assertEqual(classify_latency(20.0, 40), GREEN)  # exactly 0.5

    def test_tight_but_keeps_up_is_yellow(self):
        self.assertEqual(classify_latency(8.0, 10), YELLOW)
        self.assertEqual(classify_latency(40.0, 40), YELLOW)  # exactly 1.0

    def test_over_budget_is_red(self):
        self.assertEqual(classify_latency(11.0, 10), RED)
        self.assertEqual(classify_latency(50.0, 40), RED)

    def test_degenerate_inputs(self):
        self.assertEqual(classify_latency(0.0, 10), GREEN)   # instantaneous
        self.assertEqual(classify_latency(5.0, 0), RED)      # no budget


class RecommendIntervalTests(unittest.TestCase):
    def test_fast_model_keeps_current_interval(self):
        # Green with headroom to spare: no change recommended.
        self.assertEqual(recommend_interval(3.0, 10), 10)
        self.assertEqual(recommend_interval(20.0, 40), 40)

    def test_slow_model_is_lengthened_and_rounded(self):
        # 8s call wants a >=16s interval, rounded up to the next 5s step.
        self.assertEqual(recommend_interval(8.0, 10), 20)
        # 50s call wants >=100s.
        self.assertEqual(recommend_interval(50.0, 40), 100)

    def test_recommendation_never_drops_below_current(self):
        self.assertEqual(recommend_interval(1.0, 55), 55)

    def test_unusably_slow_model_is_clamped(self):
        self.assertEqual(recommend_interval(200.0, 40), MAX_INTERVAL)

    def test_floor_is_respected(self):
        self.assertGreaterEqual(recommend_interval(0.1, 1), MIN_INTERVAL)


def _fit(short_latency: float, long_latency: float) -> TextModelFit:
    return TextModelFit(
        model_id="endpoint:lmstudio:llama",
        model_name="llama (local)",
        status="ok",
        short=ProfileLatency(short_latency, 120, 30.0),
        long=ProfileLatency(long_latency, 200, 10.0),
    )


class ScoreTextModelTests(unittest.TestCase):
    def test_failed_fit_scores_no_roles(self):
        failed = TextModelFit("x", "x", status="failed", reason="down")
        self.assertEqual(score_text_model(failed, {}), [])

    def test_fast_model_is_green_across_roles_with_no_changes(self):
        roles = score_text_model(_fit(3.0, 20.0), {})
        self.assertEqual({r.slug for r in roles}, {
            "objection_handler",
            "opportunity_specialist",
            "consolidated_analyst",
            "strategic_signals",
            "synthesizer",
        })
        self.assertTrue(all(r.verdict == GREEN for r in roles))
        self.assertTrue(all(not r.changed for r in roles))

    def test_slow_model_flags_and_recommends_longer_intervals(self):
        by_slug = {r.slug: r for r in score_text_model(_fit(8.0, 50.0), {})}

        # Short-window agent, tight at 10s.
        self.assertEqual(by_slug["objection_handler"].verdict, YELLOW)
        self.assertEqual(by_slug["objection_handler"].recommended_interval_seconds, 20)
        self.assertTrue(by_slug["objection_handler"].changed)

        # Long-window agents over budget.
        self.assertEqual(by_slug["consolidated_analyst"].verdict, RED)
        self.assertEqual(by_slug["consolidated_analyst"].recommended_interval_seconds, 100)

        # Roomy cooldown stays green and untouched.
        self.assertEqual(by_slug["opportunity_specialist"].verdict, GREEN)
        self.assertFalse(by_slug["opportunity_specialist"].changed)

    def test_stored_intervals_override_defaults_as_budget(self):
        # A user who already widened the analyst to 120s should read as green.
        roles = {r.slug: r for r in score_text_model(_fit(8.0, 50.0), {"consolidated_analyst": 120})}
        self.assertEqual(roles["consolidated_analyst"].budget_seconds, 120)
        self.assertEqual(roles["consolidated_analyst"].verdict, GREEN)


class ValidateIntervalUpdatesTests(unittest.TestCase):
    def test_accepts_known_agents_in_range(self):
        cleaned = validate_interval_updates([
            {"slug": "objection_handler", "interval_seconds": 20},
            {"slug": "consolidated_analyst", "interval_seconds": 100},
        ])
        self.assertEqual(cleaned, {"objection_handler": 20, "consolidated_analyst": 100})

    def test_rejects_unknown_agent(self):
        with self.assertRaises(ValueError):
            validate_interval_updates([{"slug": "audio_gateway", "interval_seconds": 20}])

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            validate_interval_updates([{"slug": "objection_handler", "interval_seconds": 1}])
        with self.assertRaises(ValueError):
            validate_interval_updates([{"slug": "objection_handler", "interval_seconds": 10_000}])

    def test_rejects_non_integer_and_bool(self):
        with self.assertRaises(ValueError):
            validate_interval_updates([{"slug": "objection_handler", "interval_seconds": "20"}])
        with self.assertRaises(ValueError):
            validate_interval_updates([{"slug": "objection_handler", "interval_seconds": True}])


class BenchmarkTextModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_benchmark_times_both_windows(self):
        calls: list[str] = []

        async def fake_generate(model_id, prompt, **kwargs):
            calls.append(prompt)
            return "point one; point two; point three"

        fit = await benchmark_text_model("endpoint:x:m", "m", generate=fake_generate)

        self.assertEqual(fit.status, "ok")
        self.assertIsNotNone(fit.short)
        self.assertIsNotNone(fit.long)
        # Warmup + short + long.
        self.assertEqual(len(calls), 3)

    async def test_failed_call_returns_failed_fit_without_raising(self):
        async def broken_generate(model_id, prompt, **kwargs):
            raise RuntimeError("connection refused")

        fit = await benchmark_text_model("endpoint:x:m", "m", generate=broken_generate)

        self.assertEqual(fit.status, "failed")
        self.assertIn("connection refused", fit.reason)


class ApplyRecommendedIntervalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_applies_validated_intervals_and_commits(self):
        row = SimpleNamespace(slug="objection_handler", interval_seconds=10, updated_at=None)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db = AsyncMock()
        db.execute.return_value = result

        applied = await apply_recommended_intervals(
            db, [{"slug": "objection_handler", "interval_seconds": 25}]
        )

        self.assertEqual(applied, {"objection_handler": 25})
        self.assertEqual(row.interval_seconds, 25)
        self.assertIsNotNone(row.updated_at)
        db.commit.assert_awaited_once()

    async def test_invalid_payload_raises_before_touching_db(self):
        db = AsyncMock()
        with self.assertRaises(ValueError):
            await apply_recommended_intervals(db, [{"slug": "nope", "interval_seconds": 25}])
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.local_fit import (
    GREEN,
    MAX_ASR_SECONDS,
    MIN_ASR_SECONDS,
    MAX_INTERVAL,
    MIN_INTERVAL,
    RED,
    YELLOW,
    ProfileLatency,
    TextModelFit,
    apply_recommended_intervals,
    benchmark_asr_model,
    benchmark_text_model,
    build_local_capabilities,
    classify_latency,
    classify_rtf,
    is_asr_clip_too_short,
    recommend_interval,
    run_asr_fit,
    score_text_model,
    trim_asr_clip,
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


class ClassifyRtfTests(unittest.TestCase):
    def test_faster_than_half_real_time_is_green(self):
        self.assertEqual(classify_rtf(0.2), GREEN)
        self.assertEqual(classify_rtf(0.5), GREEN)  # boundary

    def test_up_to_real_time_is_yellow(self):
        self.assertEqual(classify_rtf(0.8), YELLOW)
        self.assertEqual(classify_rtf(1.0), YELLOW)  # boundary

    def test_slower_than_real_time_is_red(self):
        self.assertEqual(classify_rtf(1.4), RED)


class AsrClipHelperTests(unittest.TestCase):
    def test_too_short_clip_is_rejected(self):
        min_bytes = MIN_ASR_SECONDS * 16000 * 2
        self.assertTrue(is_asr_clip_too_short(b"\x00" * (min_bytes - 1)))
        self.assertFalse(is_asr_clip_too_short(b"\x00" * min_bytes))

    def test_long_clip_is_trimmed_to_cap(self):
        cap_bytes = MAX_ASR_SECONDS * 16000 * 2
        self.assertEqual(len(trim_asr_clip(b"\x00" * (cap_bytes + 5000))), cap_bytes)


class BenchmarkAsrModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_benchmark_reports_rtf_and_verdict(self):
        calls: list[bytes] = []

        class FakeTranscriber:
            def __init__(self, model_id):
                self.model_id = model_id

            async def transcribe_segment(self, pcm_bytes):
                calls.append(pcm_bytes)
                return "hello there"

        fit = await benchmark_asr_model(
            "local-whisper-base", b"\x00" * 320000, 10.0, make_transcriber=FakeTranscriber
        )

        self.assertEqual(fit.status, "ok")
        self.assertEqual(fit.audio_seconds, 10.0)
        self.assertIsNotNone(fit.real_time_factor)
        self.assertIn(fit.verdict, {GREEN, YELLOW, RED})
        # Warmup + timed call.
        self.assertEqual(len(calls), 2)

    async def test_failed_transcription_returns_failed_fit(self):
        class BrokenTranscriber:
            def __init__(self, model_id):
                pass

            async def transcribe_segment(self, pcm_bytes):
                raise RuntimeError("onnx runtime missing")

        fit = await benchmark_asr_model(
            "local-whisper-base", b"\x00" * 320000, 10.0, make_transcriber=BrokenTranscriber
        )

        self.assertEqual(fit.status, "failed")
        self.assertIn("onnx runtime missing", fit.reason)


class RunAsrFitTests(unittest.IsolatedAsyncioTestCase):
    async def test_benchmarks_every_bundled_local_asr_model(self):
        class FakeTranscriber:
            def __init__(self, model_id):
                pass

            async def transcribe_segment(self, pcm_bytes):
                return "hi"

        report = await run_asr_fit(b"\x00" * 320000, make_transcriber=FakeTranscriber)

        # Both bundled local ASR models are measured.
        self.assertEqual(len(report["asr_models"]), 2)
        self.assertTrue(all(m["status"] == "ok" for m in report["asr_models"]))
        self.assertGreater(report["audio_seconds"], 0)


class BuildLocalCapabilitiesTests(unittest.TestCase):
    MODELS = [
        {
            "id": "local-whisper-base",
            "name": "Whisper Base (Local)",
            "supports_text": False,
            "supports_batch_audio": True,
            "supports_live_audio": False,
        },
        {
            "id": "endpoint:antares:antares",
            "name": "antares-1b",
            "supports_text": True,
            "supports_batch_audio": False,
            "supports_live_audio": False,
        },
    ]

    def _services(self):
        return {s["key"]: s for s in build_local_capabilities(self.MODELS)["services"]}

    def test_batch_and_text_services_list_the_right_models(self):
        svc = self._services()
        self.assertEqual(
            [o["id"] for o in svc["batch_transcription"]["local_options"]],
            ["local-whisper-base"],
        )
        self.assertEqual(
            [o["id"] for o in svc["analysis_agents"]["local_options"]],
            ["endpoint:antares:antares"],
        )
        # Meeting chat is text too, so the chat endpoint also fills it.
        self.assertEqual(
            [o["id"] for o in svc["meeting_chat"]["local_options"]],
            ["endpoint:antares:antares"],
        )

    def test_live_captions_have_no_local_option_and_name_the_cloud_need(self):
        live = self._services()["live_captions"]
        self.assertEqual(live["local_options"], [])
        self.assertTrue(live["cloud_only"])
        self.assertIn("cloud", live["note"].lower())

    def test_per_model_usable_for_is_derived_from_flags(self):
        usage = {m["id"]: m["usable_for"] for m in build_local_capabilities(self.MODELS)["models"]}
        self.assertEqual(usage["local-whisper-base"], ["Batch transcription"])
        self.assertIn("Analysis agents", usage["endpoint:antares:antares"])
        self.assertIn("Meeting chat & summarization", usage["endpoint:antares:antares"])
        self.assertNotIn("Live interim captions", usage["endpoint:antares:antares"])


if __name__ == "__main__":
    unittest.main()

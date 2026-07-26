import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.local_fit import (
    DEFAULT_CONTENTION,
    FEASIBLE,
    GREEN,
    MARGINAL,
    MAX_ASR_SECONDS,
    MIN_ASR_SECONDS,
    MAX_INTERVAL,
    MIN_INTERVAL,
    NOT_FEASIBLE,
    POST_CALL_GREEN_SECONDS,
    POST_CALL_YELLOW_SECONDS,
    RED,
    YELLOW,
    ProfileLatency,
    TextModelFit,
    _fill_placeholders,
    apply_recommended_intervals,
    benchmark_asr_model,
    benchmark_text_model,
    budgets_for_model,
    build_local_capabilities,
    classify_latency,
    classify_live_feasibility,
    classify_post_call,
    classify_rtf,
    effective_latency,
    is_asr_clip_too_short,
    parse_model_intervals,
    recommend_interval,
    run_asr_fit,
    score_text_model,
    synthetic_speech_clip,
    trim_asr_clip,
    validate_interval_updates,
)
from app.services.local_fit import clip_has_speech


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

    def test_includes_interval_and_post_call_agents(self):
        roles = {r.slug: r for r in score_text_model(_fit(3.0, 20.0), {}, contention=1.0)}
        # Five interval agents plus the three post-call briefing agents.
        for slug in ("objection_handler", "opportunity_specialist", "consolidated_analyst",
                     "strategic_signals", "synthesizer"):
            self.assertFalse(roles[slug].post_call)
            self.assertTrue(roles[slug].editable)
        for slug in ("brief_meeting_lens", "brief_discovery_lens", "brief_arbiter"):
            self.assertTrue(roles[slug].post_call)
            self.assertFalse(roles[slug].editable)

    def test_fast_model_is_green_across_roles_with_no_changes(self):
        roles = score_text_model(_fit(3.0, 20.0), {}, contention=1.0)
        interval_roles = [r for r in roles if not r.post_call]
        self.assertTrue(all(r.verdict == GREEN for r in interval_roles))
        self.assertTrue(all(not r.changed for r in interval_roles))

    def test_slow_model_flags_and_recommends_longer_intervals(self):
        by_slug = {r.slug: r for r in score_text_model(_fit(8.0, 50.0), {}, contention=1.0)}

        self.assertEqual(by_slug["objection_handler"].verdict, YELLOW)
        self.assertEqual(by_slug["objection_handler"].recommended_interval_seconds, 20)
        self.assertTrue(by_slug["objection_handler"].changed)

        self.assertEqual(by_slug["consolidated_analyst"].verdict, RED)
        self.assertEqual(by_slug["consolidated_analyst"].recommended_interval_seconds, 100)

        self.assertEqual(by_slug["opportunity_specialist"].verdict, GREEN)
        self.assertFalse(by_slug["opportunity_specialist"].changed)

    def test_per_model_budget_overrides_default(self):
        # A per-model budget of 120s for the analyst reads as green even when slow.
        roles = {r.slug: r for r in score_text_model(
            _fit(8.0, 50.0), {"consolidated_analyst": 120}, contention=1.0)}
        self.assertEqual(roles["consolidated_analyst"].budget_seconds, 120)
        self.assertEqual(roles["consolidated_analyst"].verdict, GREEN)

    def test_contention_makes_verdicts_stricter(self):
        # Analyst at 20s vs 40s budget: green at 1x (0.5), tips to yellow at 1.5x.
        green = {r.slug: r for r in score_text_model(_fit(3.0, 20.0), {}, contention=1.0)}
        strict = {r.slug: r for r in score_text_model(_fit(3.0, 20.0), {}, contention=1.5)}
        self.assertEqual(green["consolidated_analyst"].verdict, GREEN)
        self.assertEqual(strict["consolidated_analyst"].verdict, YELLOW)
        self.assertTrue(strict["consolidated_analyst"].changed)

    def test_post_call_briefing_judged_on_end_of_call_wait(self):
        # Long call 40s: post-call briefing is fine (<=60s), interval analyst is not.
        roles = {r.slug: r for r in score_text_model(_fit(5.0, 40.0), {}, contention=1.0)}
        self.assertEqual(roles["brief_arbiter"].verdict, GREEN)
        # A 200s briefing would be over the acceptable end-of-call wait.
        slow = {r.slug: r for r in score_text_model(_fit(5.0, 200.0), {}, contention=1.0)}
        self.assertEqual(slow["brief_arbiter"].verdict, RED)


class ContentionAndPostCallHelperTests(unittest.TestCase):
    def test_effective_latency_scales_and_clamps(self):
        self.assertEqual(effective_latency(10.0, 1.5), 15.0)
        self.assertEqual(effective_latency(10.0, 5.0), 30.0)  # clamped to MAX_CONTENTION=3
        self.assertEqual(effective_latency(10.0, 0.1), 10.0)  # clamped to MIN_CONTENTION=1

    def test_classify_post_call_thresholds(self):
        self.assertEqual(classify_post_call(POST_CALL_GREEN_SECONDS), GREEN)
        self.assertEqual(classify_post_call(POST_CALL_YELLOW_SECONDS), YELLOW)
        self.assertEqual(classify_post_call(POST_CALL_YELLOW_SECONDS + 1), RED)

    def test_default_contention_is_conservative(self):
        self.assertGreater(DEFAULT_CONTENTION, 1.0)


class ParseModelIntervalsTests(unittest.TestCase):
    def test_valid_and_invalid_payloads(self):
        self.assertEqual(parse_model_intervals('{"m1": 40, "m2": 90}'), {"m1": 40, "m2": 90})
        self.assertEqual(parse_model_intervals(""), {})
        self.assertEqual(parse_model_intervals("not json"), {})
        self.assertEqual(parse_model_intervals("[1,2]"), {})
        # Booleans are not intervals.
        self.assertEqual(parse_model_intervals('{"m1": true}'), {})


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

    async def test_timed_calls_carry_the_role_system_prompts(self):
        systems: list[str | None] = []

        async def fake_generate(model_id, prompt, **kwargs):
            systems.append(kwargs.get("system"))
            return "ok"

        fit = await benchmark_text_model(
            "endpoint:x:m",
            "m",
            system_prompts={"short": "SHORT_SYS", "long": "LONG_SYS"},
            generate=fake_generate,
        )

        self.assertEqual(fit.status, "ok")
        self.assertEqual(len(systems), 3)
        self.assertIsNone(systems[0])  # warmup carries no system prompt
        self.assertIn("SHORT_SYS", systems)
        self.assertIn("LONG_SYS", systems)

    async def test_failed_call_returns_failed_fit_without_raising(self):
        async def broken_generate(model_id, prompt, **kwargs):
            raise RuntimeError("connection refused")

        fit = await benchmark_text_model("endpoint:x:m", "m", generate=broken_generate)

        self.assertEqual(fit.status, "failed")
        self.assertIn("connection refused", fit.reason)


class ApplyRecommendedIntervalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_per_model_budget_and_commits(self):
        row = SimpleNamespace(
            slug="objection_handler", interval_seconds=10, model_intervals="", updated_at=None
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db = AsyncMock()
        db.execute.return_value = result

        applied = await apply_recommended_intervals(
            db, "endpoint:x:m", [{"slug": "objection_handler", "interval_seconds": 25}]
        )

        self.assertEqual(applied, {"objection_handler": 25})
        # Stored under the model id, not on the global interval.
        self.assertEqual(row.interval_seconds, 10)
        self.assertEqual(parse_model_intervals(row.model_intervals), {"endpoint:x:m": 25})
        self.assertIsNotNone(row.updated_at)
        db.commit.assert_awaited_once()

    async def test_preserves_other_models_budgets(self):
        row = SimpleNamespace(
            slug="objection_handler",
            interval_seconds=10,
            model_intervals='{"endpoint:a:a": 30}',
            updated_at=None,
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db = AsyncMock()
        db.execute.return_value = result

        await apply_recommended_intervals(
            db, "endpoint:b:b", [{"slug": "objection_handler", "interval_seconds": 45}]
        )

        self.assertEqual(
            parse_model_intervals(row.model_intervals),
            {"endpoint:a:a": 30, "endpoint:b:b": 45},
        )

    async def test_invalid_payload_raises_before_touching_db(self):
        db = AsyncMock()
        with self.assertRaises(ValueError):
            await apply_recommended_intervals(db, "m", [{"slug": "nope", "interval_seconds": 25}])
        db.commit.assert_not_awaited()

    async def test_missing_model_id_raises(self):
        db = AsyncMock()
        with self.assertRaises(ValueError):
            await apply_recommended_intervals(db, "", [{"slug": "objection_handler", "interval_seconds": 25}])


class BudgetsForModelTests(unittest.IsolatedAsyncioTestCase):
    def _db_with_rows(self, rows):
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        db = AsyncMock()
        db.execute.return_value = result
        return db

    async def test_per_model_budget_wins_then_global_then_default(self):
        rows = [
            SimpleNamespace(slug="consolidated_analyst", interval_seconds=40,
                            model_intervals='{"m1": 90}'),
            SimpleNamespace(slug="objection_handler", interval_seconds=None, model_intervals=""),
        ]
        db = self._db_with_rows(rows)

        m1 = await budgets_for_model(db, "m1")
        self.assertEqual(m1["consolidated_analyst"], 90)   # per-model wins
        self.assertEqual(m1["objection_handler"], 10)      # seeded default (no global, no per-model)

        db2 = self._db_with_rows(rows)
        m2 = await budgets_for_model(db2, "m2")
        self.assertEqual(m2["consolidated_analyst"], 40)   # falls back to global interval

    async def test_only_interval_agents_are_returned(self):
        db = self._db_with_rows([])
        budgets = await budgets_for_model(db, "m1")
        self.assertNotIn("brief_arbiter", budgets)
        self.assertIn("synthesizer", budgets)


class LiveFeasibilityAndSyntheticClipTests(unittest.TestCase):
    def test_live_feasibility_thresholds(self):
        self.assertEqual(classify_live_feasibility(0.2), FEASIBLE)
        self.assertEqual(classify_live_feasibility(0.5), MARGINAL)
        self.assertEqual(classify_live_feasibility(0.9), NOT_FEASIBLE)

    def test_synthetic_clip_has_speech_energy_and_length(self):
        clip = synthetic_speech_clip(seconds=4)
        self.assertEqual(len(clip), 4 * 16000 * 2)
        self.assertTrue(clip_has_speech(clip))


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


class FillPlaceholdersTests(unittest.TestCase):
    def test_known_placeholders_get_representative_filler(self):
        filled = _fill_placeholders("Analyze.\n{lens_sections}\nContext: {meeting_context_text}")
        self.assertNotIn("{lens_sections}", filled)
        self.assertNotIn("{meeting_context_text}", filled)
        self.assertIn("Lens", filled)  # representative lens block was inserted

    def test_unknown_placeholders_are_dropped_not_left_literal(self):
        filled = _fill_placeholders("Hello {unknown_token} world")
        self.assertNotIn("{unknown_token}", filled)
        self.assertNotIn("{", filled)


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

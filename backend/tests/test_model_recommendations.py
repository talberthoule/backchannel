import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers import models
from app.services.local_fit import local_recommendations_from_fit


CURRENT = {"status": "current", "reason": "", "age_days": 0}


class CloudRecommendationTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_exposes_the_approved_role_matrix(self):
        with (
            patch.object(
                models,
                "provider_key_availability",
                AsyncMock(return_value={"google": True, "openai": True}),
            ),
            patch.object(
                models,
                "legacy_endpoint_configured",
                AsyncMock(return_value=False),
            ),
            patch.object(models, "endpoint_models", AsyncMock(return_value=[])),
            patch.object(
                models,
                "local_model_recommendations",
                AsyncMock(return_value={}),
            ),
        ):
            listed = await models.list_models(SimpleNamespace())

        by_id = {model["id"]: model for model in listed}
        actual = {
            (item["role"], item["provider"]): model_id
            for model_id, model in by_id.items()
            for item in model["recommendations"]
            if item["source"] == "provider_default"
        }
        expected = {
            ("audio_gateway", "google"): "gemini-3.1-flash-live-preview",
            ("audio_gateway", "openai"): "gpt-realtime-whisper",
            ("consolidated_analyst", "google"): "gemini-3.6-flash",
            ("consolidated_analyst", "openai"): "gpt-5.6-terra",
            ("objection_handler", "google"): "gemini-3.5-flash-lite",
            ("objection_handler", "openai"): "gpt-5.6-luna",
            ("synthesizer", "google"): "gemini-3.6-flash",
            ("synthesizer", "openai"): "gpt-5.6-terra",
            ("opportunity_specialist", "google"): "gemini-3.6-flash",
            ("opportunity_specialist", "openai"): "gpt-5.6-luna",
            ("strategic_signals", "google"): "gemini-3.6-flash",
            ("strategic_signals", "openai"): "gpt-5.6-terra",
            ("brief_meeting_lens", "google"): "gemini-3.6-flash",
            ("brief_meeting_lens", "openai"): "gpt-5.6-terra",
            ("brief_discovery_lens", "google"): "gemini-3.6-flash",
            ("brief_discovery_lens", "openai"): "gpt-5.6-terra",
            ("brief_arbiter", "google"): "gemini-3.6-flash",
            ("brief_arbiter", "openai"): "gpt-5.6-sol",
            ("live_ask", "google"): "gemini-3.6-flash",
            ("live_ask", "openai"): "gpt-5.6-terra",
            ("batch_transcription", "google"): "gemini-3.5-flash-lite",
            ("batch_transcription", "openai"): "gpt-4o-mini-transcribe",
        }
        self.assertEqual(expected, actual)
        self.assertEqual(
            {"objection_handler", "batch_transcription"},
            {item["role"] for item in by_id["gemini-3.5-flash-lite"]["recommendations"]},
        )
        self.assertIn(
            "strategic_signals",
            {item["role"] for item in by_id["gemini-3.6-flash"]["recommendations"]},
        )
        self.assertEqual(
            {"brief_arbiter"},
            {item["role"] for item in by_id["gpt-5.6-sol"]["recommendations"]},
        )
        self.assertEqual(
            "high",
            by_id["gpt-5.6-sol"]["recommendations"][0]["reasoning_effort"],
        )
        for model_id, model in by_id.items():
            models.ModelOut.model_validate(model)
            for recommendation in model["recommendations"]:
                if recommendation.get("reasoning_effort") == "high":
                    self.assertEqual(("gpt-5.6-sol", "brief_arbiter"), (
                        model_id,
                        recommendation["role"],
                    ))

    async def test_local_fit_metadata_is_merged_without_changing_availability(self):
        local_model = {
            "id": "endpoint:box:qwen",
            "name": "qwen",
            "provider": "Box",
            "description": "local",
            "tier": "stable",
            "requires_key": None,
            "key_available": True,
            "supports_text": True,
            "supports_batch_audio": False,
            "supports_live_audio": False,
            "runs_locally": True,
            "endpoint_id": "box",
        }
        recommendation = {
            "role": "consolidated_analyst",
            "provider": "local",
            "recommended": True,
            "source": "local_fit",
            "interval_seconds": 40,
        }
        with (
            patch.object(models, "provider_key_availability", AsyncMock(return_value={})),
            patch.object(models, "legacy_endpoint_configured", AsyncMock(return_value=False)),
            patch.object(models, "endpoint_models", AsyncMock(return_value=[local_model])),
            patch.object(
                models,
                "local_model_recommendations",
                AsyncMock(return_value={local_model["id"]: [recommendation]}),
            ),
        ):
            listed = await models.list_models(SimpleNamespace())

        entry = next(model for model in listed if model["id"] == local_model["id"])
        self.assertTrue(entry["key_available"])
        self.assertEqual([recommendation], entry["recommendations"])


class LocalRecommendationTests(unittest.TestCase):
    def test_only_current_green_winners_are_recommended(self):
        fit = {
            "validity": CURRENT,
            "contention": 1.5,
            "text_models": [
                _text_measurement("endpoint:box:fast", short=1.0, long=2.0),
                _text_measurement("endpoint:box:slow", short=40.0, long=200.0),
                _text_measurement(
                    "endpoint:box:stale",
                    short=0.1,
                    long=0.1,
                    validity={"status": "aged"},
                ),
            ],
            "asr": {
                "asr_models": [
                    _asr_measurement("local-whisper-base", 0.2, 0.2),
                    _asr_measurement("local-parakeet-tdt-0.6b", 0.3, 0.1),
                ]
            },
        }

        recommendations = local_recommendations_from_fit(fit)

        fast_roles = {
            item["role"]: item
            for item in recommendations["endpoint:box:fast"]
        }
        self.assertIn("consolidated_analyst", fast_roles)
        self.assertEqual(40, fast_roles["consolidated_analyst"]["interval_seconds"])
        self.assertNotIn(
            "interval_seconds",
            fast_roles["brief_arbiter"],
        )
        self.assertNotIn("endpoint:box:slow", recommendations)
        self.assertNotIn("endpoint:box:stale", recommendations)
        self.assertEqual(
            ["batch_transcription"],
            [item["role"] for item in recommendations["local-whisper-base"]],
        )
        self.assertEqual(
            ["audio_gateway"],
            [item["role"] for item in recommendations["local-parakeet-live"]],
        )

    def test_aged_whole_result_or_nonfeasible_live_asr_yields_no_badges(self):
        aged = {
            "validity": {"status": "aged"},
            "text_models": [_text_measurement("endpoint:box:fast", 0.1, 0.1)],
        }
        self.assertEqual({}, local_recommendations_from_fit(aged))

        current = {
            "validity": CURRENT,
            "contention": 1.5,
            "text_models": [],
            "asr": {
                "asr_models": [
                    _asr_measurement(
                        "local-parakeet-tdt-0.6b",
                        real_time_factor=0.2,
                        short_real_time_factor=0.5,
                    )
                ]
            },
        }
        recommendations = local_recommendations_from_fit(current)
        self.assertNotIn("local-parakeet-live", recommendations)

    def test_equal_latency_winner_is_stable_by_model_id(self):
        fit = {
            "validity": CURRENT,
            "contention": 1.5,
            "text_models": [
                _text_measurement("endpoint:box:z", 1.0, 2.0),
                _text_measurement("endpoint:box:a", 1.0, 2.0),
            ],
        }

        recommendations = local_recommendations_from_fit(fit)

        self.assertIn("endpoint:box:a", recommendations)
        self.assertNotIn("endpoint:box:z", recommendations)


def _text_measurement(model_id, short, long, validity=CURRENT):
    roles = [
        {"slug": "objection_handler", "budget_seconds": 10},
        {"slug": "opportunity_specialist", "budget_seconds": 55},
        {"slug": "consolidated_analyst", "budget_seconds": 40},
        {"slug": "strategic_signals", "budget_seconds": 45},
        {"slug": "synthesizer", "budget_seconds": 75},
    ]
    return {
        "model_id": model_id,
        "model_name": model_id,
        "status": "ok",
        "short": {"latency_seconds": short},
        "long": {"latency_seconds": long},
        "roles": roles,
        "validity": validity,
    }


def _asr_measurement(
    model_id,
    real_time_factor,
    short_real_time_factor,
    validity=CURRENT,
):
    return {
        "model_id": model_id,
        "status": "ok",
        "real_time_factor": real_time_factor,
        "short_real_time_factor": short_real_time_factor,
        "validity": validity,
    }


if __name__ == "__main__":
    unittest.main()

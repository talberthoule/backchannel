"""Parakeet TDT 0.6B v3 and language-aware local ASR recommendations (ALP-405).

v3 joins the local batch models and gets its own on-device live captioner.
Registry entries say which languages each local ASR model covers, and the
fit-test recommendations only badge a model that suits the workspace
meeting language.
"""

import os
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.config import MODEL_REGISTRY, PARAKEET_V3_LANGUAGES  # noqa: E402
from app.routers.models import ModelOut  # noqa: E402
from app.services import local_fit  # noqa: E402
from app.services.local_fit import local_recommendations_from_fit  # noqa: E402
from app.services.local_live_captioner import LOCAL_LIVE_MODEL_MAP, LocalLiveCaptioner  # noqa: E402
from app.services.local_transcriber import LOCAL_MODEL_MAP, LOCAL_MODEL_QUANTIZATION  # noqa: E402
from app.services.privacy import is_local_model  # noqa: E402
from app.services.transcription_language import (  # noqa: E402
    SETTING_TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_LANGUAGES,
    is_english_only,
    model_languages,
    recommendable_for_language,
)

V2 = "local-parakeet-tdt-0.6b"
V3 = "local-parakeet-tdt-0.6b-v3"
V2_LIVE = "local-parakeet-live"
V3_LIVE = "local-parakeet-v3-live"
WHISPER = "local-whisper-base"
CURRENT = {"status": "current", "reason": "", "age_days": 0}


def _entry(model_id):
    return next(m for m in MODEL_REGISTRY if m["id"] == model_id)


def _asr(model_id, rtf, short_rtf):
    return {
        "model_id": model_id,
        "status": "ok",
        "real_time_factor": rtf,
        "short_real_time_factor": short_rtf,
        "validity": CURRENT,
    }


def _fit():
    # All three GREEN and live-feasible; v2 fastest, then v3, then Whisper.
    return {
        "validity": CURRENT,
        "contention": 1.0,
        "text_models": [],
        "asr": {"asr_models": [_asr(WHISPER, 0.25, 0.30), _asr(V2, 0.10, 0.10), _asr(V3, 0.12, 0.12)]},
    }


def _badged(recommendations, role):
    return sorted(
        model_id
        for model_id, items in recommendations.items()
        if any(item["role"] == role for item in items)
    )


class RegistryTests(unittest.TestCase):
    def test_v3_batch_and_live_are_local_and_list_their_languages(self):
        for model_id, batch, live in ((V3, True, False), (V3_LIVE, False, True)):
            entry = _entry(model_id)
            self.assertEqual("Local", entry["provider"])
            self.assertEqual(batch, entry["supports_batch_audio"])
            self.assertEqual(live, entry["supports_live_audio"])
            self.assertEqual(list(PARAKEET_V3_LANGUAGES), entry["languages"])
            self.assertTrue(is_local_model(model_id))

    def test_v2_is_english_only_and_whisper_is_unrestricted(self):
        self.assertTrue(is_english_only(V2))
        self.assertTrue(is_english_only(V2_LIVE))
        self.assertFalse(is_english_only(V3))
        self.assertIsNone(model_languages(WHISPER))

    def test_v3_languages_are_all_offered_in_the_picker(self):
        self.assertEqual(25, len(PARAKEET_V3_LANGUAGES))
        self.assertTrue(set(PARAKEET_V3_LANGUAGES) <= set(TRANSCRIPTION_LANGUAGES))

    def test_v3_loads_int8_through_the_existing_onnx_asr_path(self):
        self.assertEqual("nemo-parakeet-tdt-0.6b-v3", LOCAL_MODEL_MAP[V3])
        self.assertEqual("int8", LOCAL_MODEL_QUANTIZATION[V3])
        self.assertNotIn(V2, LOCAL_MODEL_QUANTIZATION)

    def test_v3_live_captioner_runs_the_v3_batch_model(self):
        self.assertEqual(V3, LOCAL_LIVE_MODEL_MAP[V3_LIVE])
        self.assertEqual(V3, LocalLiveCaptioner(model_override=V3_LIVE)._asr_model_id)
        self.assertEqual(V2, LocalLiveCaptioner(model_override=V2_LIVE)._asr_model_id)

    def test_models_endpoint_schema_carries_languages(self):
        entry = {**_entry(V3), "runs_locally": True}
        self.assertEqual(list(PARAKEET_V3_LANGUAGES), ModelOut(**entry).languages)
        self.assertIsNone(ModelOut(**{**_entry(WHISPER), "runs_locally": True}).languages)


class LanguageRuleTests(unittest.TestCase):
    def test_set_language_must_be_covered(self):
        self.assertTrue(recommendable_for_language(V3, "de"))
        self.assertFalse(recommendable_for_language(V2, "de"))
        self.assertFalse(recommendable_for_language(V3, "ja"))
        self.assertTrue(recommendable_for_language(WHISPER, "ja"))

    def test_auto_passes_over_english_only_models(self):
        self.assertFalse(recommendable_for_language(V2, "auto"))
        self.assertTrue(recommendable_for_language(V3, "auto"))
        self.assertTrue(recommendable_for_language(WHISPER, "auto"))

    def test_english_keeps_every_model(self):
        for model_id in (V2, V3, WHISPER, V2_LIVE, V3_LIVE):
            self.assertTrue(recommendable_for_language(model_id, "en"), model_id)


class RecommendationTests(unittest.TestCase):
    def test_without_a_language_the_fastest_models_win(self):
        recommendations = local_recommendations_from_fit(_fit())
        self.assertEqual([V2], _badged(recommendations, "batch_transcription"))
        self.assertEqual([V2_LIVE], _badged(recommendations, "audio_gateway"))

    def test_english_keeps_the_english_only_winners(self):
        recommendations = local_recommendations_from_fit(_fit(), language="en")
        self.assertEqual([V2], _badged(recommendations, "batch_transcription"))
        self.assertEqual([V2_LIVE], _badged(recommendations, "audio_gateway"))

    def test_german_never_badges_english_only_models(self):
        recommendations = local_recommendations_from_fit(_fit(), language="de")
        self.assertEqual([V3], _badged(recommendations, "batch_transcription"))
        self.assertEqual([V3_LIVE], _badged(recommendations, "audio_gateway"))
        self.assertNotIn(V2, recommendations)
        self.assertNotIn(V2_LIVE, recommendations)

    def test_auto_prefers_multilingual_models(self):
        recommendations = local_recommendations_from_fit(_fit(), language="auto")
        self.assertEqual([V3], _badged(recommendations, "batch_transcription"))
        self.assertEqual([V3_LIVE], _badged(recommendations, "audio_gateway"))

    def test_a_language_no_parakeet_covers_falls_back_to_whisper_and_no_live_badge(self):
        recommendations = local_recommendations_from_fit(_fit(), language="ja")
        self.assertEqual([WHISPER], _badged(recommendations, "batch_transcription"))
        self.assertEqual([], _badged(recommendations, "audio_gateway"))


class RecommendationSettingTests(unittest.IsolatedAsyncioTestCase):
    async def test_models_endpoint_recommendations_use_the_stored_language(self):
        async def fake_setting(_db, key, default=""):
            return "de" if key == SETTING_TRANSCRIPTION_LANGUAGE else default

        with mock.patch.object(local_fit, "get_app_setting", fake_setting), \
             mock.patch.object(local_fit, "load_local_fit_result", AsyncMock(return_value=_fit())):
            recommendations = await local_fit.local_model_recommendations(MagicMock())
        self.assertEqual([V3], _badged(recommendations, "batch_transcription"))


if __name__ == "__main__":
    unittest.main()

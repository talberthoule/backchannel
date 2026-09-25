"""Whisper large-v3-turbo as a local batch model, and the recommendation rule
that lets it win for languages no Parakeet covers (ALP-406)."""

import math
import os
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.config import MODEL_REGISTRY  # noqa: E402
from app.services import local_transcriber  # noqa: E402
from app.services.local_fit import local_recommendations_from_fit  # noqa: E402
from app.services.local_transcriber import (  # noqa: E402
    LOCAL_MODEL_MAP,
    LOCAL_MODEL_QUANTIZATION,
    create_transcriber,
)
from app.services.privacy import is_local_model  # noqa: E402
from app.services.transcription_language import (  # noqa: E402
    model_languages,
    multilingual_rank,
    recommendable_for_language,
)

TURBO = "local-whisper-large-v3-turbo"
BASE = "local-whisper-base"
V2 = "local-parakeet-tdt-0.6b"
V3 = "local-parakeet-tdt-0.6b-v3"
CURRENT = {"status": "current", "reason": "", "age_days": 0}


def _speech_pcm(sample_rate: int = 16000) -> bytes:
    samples = [int(0.25 * 32767 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(sample_rate)]
    return np.array(samples, dtype=np.int16).tobytes()


def _asr(model_id, rtf, short_rtf):
    return {
        "model_id": model_id,
        "status": "ok",
        "real_time_factor": rtf,
        "short_real_time_factor": short_rtf,
        "validity": CURRENT,
    }


def _fit(*measurements):
    return {"validity": CURRENT, "contention": 1.0, "text_models": [], "asr": {"asr_models": list(measurements)}}


def _batch_pick(recommendations):
    picks = [m for m, items in recommendations.items() if any(i["role"] == "batch_transcription" for i in items)]
    assert len(picks) <= 1, picks
    return picks[0] if picks else None


# Base is always fastest; turbo keeps up (GREEN) but is slower; Parakeet fastest of all.
ALL_GREEN = _fit(_asr(BASE, 0.08, 0.2), _asr(TURBO, 0.30, 0.9), _asr(V2, 0.05, 0.1), _asr(V3, 0.06, 0.1))


class TurboRegistryTests(unittest.TestCase):
    def test_turbo_is_a_local_multilingual_batch_model(self):
        entry = next(m for m in MODEL_REGISTRY if m["id"] == TURBO)
        self.assertEqual("Local", entry["provider"])
        self.assertTrue(entry["supports_batch_audio"])
        self.assertFalse(entry["supports_live_audio"])
        self.assertIsNone(model_languages(TURBO))
        self.assertTrue(is_local_model(TURBO))
        self.assertGreater(multilingual_rank(TURBO), multilingual_rank(BASE))

    def test_turbo_loads_the_uint8_onnx_community_export(self):
        self.assertEqual("onnx-community/whisper-large-v3-turbo", LOCAL_MODEL_MAP[TURBO])
        self.assertEqual("uint8", LOCAL_MODEL_QUANTIZATION[TURBO])

    def test_turbo_is_never_ruled_out_by_language(self):
        for language in ("auto", "en", "de", "ja", "ar"):
            self.assertTrue(recommendable_for_language(TURBO, language), language)


class TurboLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def test_turbo_gets_the_meeting_language(self):
        model = MagicMock()
        model.recognize.return_value = "kyou wa ii tenki desu ne"
        with patch.object(local_transcriber, "_load_model", return_value=model):
            await create_transcriber(TURBO, language="ja").transcribe_segment(_speech_pcm())
        self.assertEqual({"language": "ja"}, model.recognize.call_args.kwargs)


class RecommendationRankTests(unittest.TestCase):
    def test_a_language_no_parakeet_lists_prefers_turbo_when_it_keeps_up(self):
        self.assertEqual(TURBO, _batch_pick(local_recommendations_from_fit(ALL_GREEN, language="ja")))

    def test_base_is_the_fallback_when_turbo_is_too_slow(self):
        slow_turbo = _fit(_asr(BASE, 0.08, 0.2), _asr(TURBO, 5.0, 9.0))
        self.assertEqual(BASE, _batch_pick(local_recommendations_from_fit(slow_turbo, language="ja")))

    def test_a_model_that_lists_the_language_beats_a_general_one(self):
        self.assertEqual(V3, _batch_pick(local_recommendations_from_fit(ALL_GREEN, language="de")))
        self.assertEqual(V2, _batch_pick(local_recommendations_from_fit(ALL_GREEN, language="en")))

    def test_auto_and_no_language_keep_the_fastest_choice(self):
        self.assertEqual(V3, _batch_pick(local_recommendations_from_fit(ALL_GREEN, language="auto")))
        self.assertEqual(V2, _batch_pick(local_recommendations_from_fit(ALL_GREEN)))


if __name__ == "__main__":
    unittest.main()

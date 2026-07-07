import asyncio
import unittest

from app.models import AppSetting
from app.services.diarization_diagnostics import SortformerEnvironment
from app.services.diarizer_runtime import (
    SETTING_SPEAKER_SIMILARITY_THRESHOLD,
    get_diarizer_runtime_config,
    set_speaker_similarity_threshold,
)


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
    )


class DiarizerRuntimeTests(unittest.TestCase):
    def test_runtime_config_reads_stored_speaker_similarity_threshold(self):
        db = FakeDb({
            SETTING_SPEAKER_SIMILARITY_THRESHOLD: AppSetting(
                key=SETTING_SPEAKER_SIMILARITY_THRESHOLD,
                value="0.68",
            )
        })

        runtime = asyncio.run(get_diarizer_runtime_config(db, environment=_environment()))

        self.assertAlmostEqual(0.68, runtime.speaker_similarity_threshold)

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


if __name__ == "__main__":
    unittest.main()

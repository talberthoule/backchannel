import unittest

from app.services.privacy import (
    DEFAULT_LOCAL_BATCH_MODEL,
    is_local_model,
    local_models,
    privacy_impact,
)


class TestLocalModelDetection(unittest.TestCase):
    def test_registry_local_models_detected(self):
        self.assertTrue(is_local_model("local-whisper-base"))
        self.assertTrue(is_local_model("local-parakeet-tdt-0.6b"))

    def test_cloud_models_not_local(self):
        self.assertFalse(is_local_model("gemini-3.5-flash"))
        self.assertFalse(is_local_model("gpt-5.5"))
        self.assertFalse(is_local_model("gemini-3.1-flash-live-preview"))

    def test_unknown_ids_fall_back_to_prefix(self):
        self.assertTrue(is_local_model("local-future-model"))
        self.assertFalse(is_local_model("some-unknown-model"))

    def test_default_local_batch_model_is_local_and_batch_capable(self):
        self.assertTrue(is_local_model(DEFAULT_LOCAL_BATCH_MODEL))
        batch_ids = [m["id"] for m in local_models("supports_batch_audio")]
        self.assertIn(DEFAULT_LOCAL_BATCH_MODEL, batch_ids)


class TestPrivacyImpact(unittest.TestCase):
    def test_impact_reflects_current_registry(self):
        impact = privacy_impact()
        disabled = [item["feature"] for item in impact["disabled"]]
        # No local text or live-audio models exist today, so cloud-only
        # features must be listed as disabled.
        self.assertIn("Live interim captions (audio gateway)", disabled)
        self.assertIn("AI analysis agents", disabled)
        self.assertIn("Meeting chat", disabled)
        self.assertIn("Document upload & summarization", disabled)

    def test_impact_items_are_complete(self):
        impact = privacy_impact()
        for item in impact["available"] + impact["disabled"]:
            self.assertTrue(item["feature"])
            self.assertTrue(item["detail"])

    def test_local_transcription_listed_as_available(self):
        impact = privacy_impact()
        features = [item["feature"] for item in impact["available"]]
        self.assertTrue(any("Transcription" in f for f in features))


if __name__ == "__main__":
    unittest.main()

import unittest

from app.config import MODEL_REGISTRY, Settings, settings
from app.services.transcription_runtime import is_supported_transcription_model


class TranscriptionRuntimeTests(unittest.TestCase):
    def test_current_batch_transcriber_default_is_supported(self):
        self.assertEqual("gemini-3.5-flash", Settings.model_fields["BATCH_TRANSCRIBER_MODEL"].default)
        self.assertTrue(is_supported_transcription_model(settings.BATCH_TRANSCRIBER_MODEL))

    def test_live_only_model_is_not_supported_for_batch_transcription(self):
        self.assertFalse(is_supported_transcription_model("gemini-3.1-flash-live-preview"))

    def test_nonexistent_model_is_not_supported(self):
        self.assertFalse(is_supported_transcription_model("not-a-model"))

    def test_supported_batch_models_are_registry_models(self):
        registry_ids = {model["id"] for model in MODEL_REGISTRY}
        self.assertIn("gemini-3.5-flash", registry_ids)
        self.assertIn("gemini-3.1-flash-lite", registry_ids)
        self.assertIn("gemini-2.5-flash", registry_ids)
        self.assertNotIn("gemini-2.0-flash", registry_ids)
        self.assertNotIn("gemini-2.5-flash-preview-05-20", registry_ids)
        self.assertNotIn("gemini-2.5-pro-preview-05-06", registry_ids)


if __name__ == "__main__":
    unittest.main()

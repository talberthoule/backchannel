import unittest
from types import SimpleNamespace
from unittest import mock

from app.config import MODEL_REGISTRY, Settings, settings
from app.services import transcription_runtime
from app.services.transcription_runtime import (
    SETTING_BATCH_TRANSCRIBER_MODEL,
    get_transcription_runtime_config,
    is_supported_live_model,
    is_supported_transcription_model,
)


class TranscriptionRuntimeTests(unittest.TestCase):
    def test_current_batch_transcriber_default_is_supported(self):
        self.assertEqual("local-whisper-base", Settings.model_fields["BATCH_TRANSCRIBER_MODEL"].default)
        self.assertTrue(is_supported_transcription_model(settings.BATCH_TRANSCRIBER_MODEL))
        self.assertEqual("Local", next(
            model["provider"]
            for model in MODEL_REGISTRY
            if model["id"] == settings.BATCH_TRANSCRIBER_MODEL
        ))

    def test_live_only_model_is_not_supported_for_batch_transcription(self):
        self.assertFalse(is_supported_transcription_model("gemini-3.1-flash-live-preview"))

    def test_nonexistent_model_is_not_supported(self):
        self.assertFalse(is_supported_transcription_model("not-a-model"))

    def test_supported_batch_models_are_registry_models(self):
        registry_ids = {model["id"] for model in MODEL_REGISTRY}
        self.assertIn("gemini-3.5-flash", registry_ids)
        self.assertIn("gemini-3.7-flash", registry_ids)
        self.assertIn("gemini-3.5-flash-lite", registry_ids)
        self.assertIn("gemini-3.1-flash-lite", registry_ids)
        self.assertIn("gemini-2.5-flash", registry_ids)
        self.assertNotIn("gemini-2.0-flash", registry_ids)
        self.assertNotIn("gemini-2.5-flash-preview-05-20", registry_ids)
        self.assertNotIn("gemini-2.5-pro-preview-05-06", registry_ids)

    def test_latest_gemini_models_support_batch_not_live_audio(self):
        for model_id in ("gemini-3.7-flash", "gemini-3.5-flash-lite"):
            self.assertTrue(is_supported_transcription_model(model_id))
            self.assertFalse(is_supported_live_model(model_id))


class TranscriptionRuntimeSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_invalid_or_blank_choices_do_not_fall_back_to_cloud(self):
        db = _RuntimeDB(
            settings={SETTING_BATCH_TRANSCRIBER_MODEL: "not-a-model"},
            gateway=SimpleNamespace(model_id=""),
        )

        runtime = await get_transcription_runtime_config(db)

        self.assertEqual("not-a-model", runtime.batch_model_id)
        self.assertEqual("", runtime.live_preview_model_id)

    async def test_transcription_pickers_can_explicitly_clear_a_selection(self):
        db = SimpleNamespace(commit=mock.AsyncMock())
        runtime = transcription_runtime.TranscriptionRuntimeConfig("", "", "")
        gateway = SimpleNamespace(model_id="gemini-3.1-flash-live-preview")
        with (
            mock.patch.object(
                transcription_runtime,
                "set_app_setting",
                mock.AsyncMock(),
            ) as set_setting,
            mock.patch.object(
                transcription_runtime,
                "get_transcription_runtime_config",
                mock.AsyncMock(return_value=runtime),
            ),
            mock.patch.object(
                transcription_runtime,
                "_get_audio_gateway_config",
                mock.AsyncMock(return_value=gateway),
            ),
        ):
            await transcription_runtime.set_batch_transcriber_model(db, "")
            await transcription_runtime.set_live_preview_model(db, "")

        set_setting.assert_awaited_once_with(db, SETTING_BATCH_TRANSCRIBER_MODEL, "")
        self.assertEqual("", gateway.model_id)
        self.assertEqual(2, db.commit.await_count)


class _RuntimeDB:
    def __init__(self, *, settings, gateway):
        self.settings = {
            key: SimpleNamespace(value=value)
            for key, value in settings.items()
        }
        self.gateway = gateway

    async def get(self, _model, key):
        return self.settings.get(key)

    async def execute(self, _query):
        return SimpleNamespace(scalar_one_or_none=lambda: self.gateway)


if __name__ == "__main__":
    unittest.main()

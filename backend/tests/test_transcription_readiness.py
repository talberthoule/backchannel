import unittest
from unittest import mock

from app.services.transcription_runtime import TranscriptionRuntimeConfig


def _runtime(batch_model_id: str) -> TranscriptionRuntimeConfig:
    return TranscriptionRuntimeConfig(
        batch_model_id=batch_model_id,
        live_preview_model_id="gemini-3.1-flash-live-preview",
        description="",
    )


def _provider_status(
    provider: str,
    key_available: bool,
    configured: bool = False,
    env_fallback: bool = False,
) -> dict:
    return {
        "provider": provider,
        "configured": configured,
        "env_fallback": env_fallback,
        "masked": "sk-...1234" if (configured or env_fallback) else "",
        "connected": False,
        "key_available": key_available,
    }


class TranscriptionReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app.services import transcription_readiness

        self.readiness = transcription_readiness
        self.db = object()
        self.provider_status_calls: list[str] = []
        self.provider_status_result = _provider_status("google", key_available=True)
        self.runtime_result = _runtime("gemini-3.5-flash-lite")
        self.local_available = True

        async def fake_runtime_config(db):
            return self.runtime_result

        async def fake_provider_status(db, provider):
            self.provider_status_calls.append(provider)
            return self.provider_status_result

        self.patches = [
            mock.patch.object(
                transcription_readiness,
                "get_transcription_runtime_config",
                fake_runtime_config,
            ),
            mock.patch.object(
                transcription_readiness, "get_provider_status", fake_provider_status
            ),
            mock.patch.object(
                transcription_readiness,
                "local_asr_available",
                lambda: self.local_available,
            ),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    async def test_local_model_ready_when_runtime_available(self):
        self.runtime_result = _runtime("local-whisper-base")
        self.local_available = True

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertTrue(result.ready)
        self.assertEqual("local", result.provider)
        self.assertEqual("local-whisper-base", result.model_id)
        self.assertEqual("", result.reason)
        self.assertEqual([], self.provider_status_calls)

    async def test_local_model_blocked_without_local_runtime(self):
        self.runtime_result = _runtime("local-whisper-base")
        self.local_available = False

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertFalse(result.ready)
        self.assertEqual("local", result.provider)
        self.assertIn("local-whisper-base", result.reason)
        self.assertIn("onnx-asr", result.reason)

    async def test_cloud_model_ready_with_available_key(self):
        self.runtime_result = _runtime("gemini-3.5-flash-lite")
        self.provider_status_result = _provider_status(
            "google", key_available=True, configured=True
        )

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertTrue(result.ready)
        self.assertEqual("google", result.provider)
        self.assertEqual(["google"], self.provider_status_calls)

    async def test_unselected_or_unknown_model_needs_selection(self):
        for model_id in ("", "not-a-model"):
            with self.subTest(model_id=model_id):
                self.runtime_result = _runtime(model_id)
                self.provider_status_calls.clear()

                result = await self.readiness.get_transcription_readiness(self.db)

                self.assertFalse(result.ready)
                self.assertEqual("", result.provider)
                self.assertIn(
                    "select a batch transcription model", result.reason.lower()
                )
                self.assertEqual([], self.provider_status_calls)

    async def test_cloud_model_blocked_without_any_key(self):
        self.runtime_result = _runtime("gemini-3.5-flash-lite")
        self.provider_status_result = _provider_status("google", key_available=False)

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertFalse(result.ready)
        self.assertIn("Google", result.reason)
        self.assertIn("API key", result.reason)
        self.assertIn("Admin", result.reason)
        self.assertIn("gemini-3.5-flash-lite", result.reason)

    async def test_cloud_model_blocked_when_key_failed_its_test(self):
        self.runtime_result = _runtime("gemini-3.5-flash-lite")
        self.provider_status_result = _provider_status(
            "google", key_available=False, configured=True
        )

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertFalse(result.ready)
        self.assertIn("connection test", result.reason)

    async def test_openai_batch_model_checks_openai_key(self):
        self.runtime_result = _runtime("gpt-4o-transcribe")
        self.provider_status_result = _provider_status("openai", key_available=True)

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertTrue(result.ready)
        self.assertEqual("openai", result.provider)
        self.assertEqual(["openai"], self.provider_status_calls)

    async def test_openai_batch_model_blocked_without_openai_key(self):
        self.runtime_result = _runtime("gpt-4o-transcribe")
        self.provider_status_result = _provider_status("openai", key_available=False)

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertFalse(result.ready)
        self.assertEqual("openai", result.provider)
        self.assertEqual(["openai"], self.provider_status_calls)
        self.assertIn("OpenAI", result.reason)
        self.assertIn("API key", result.reason)
        self.assertIn("Admin", result.reason)
        self.assertIn("gpt-4o-transcribe", result.reason)

    async def test_openai_batch_model_blocked_when_key_failed_its_test(self):
        self.runtime_result = _runtime("gpt-4o-mini-transcribe")
        self.provider_status_result = _provider_status(
            "openai", key_available=False, configured=True
        )

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertFalse(result.ready)
        self.assertEqual("openai", result.provider)
        self.assertIn("connection test", result.reason)

    async def test_to_dict_shape(self):
        self.runtime_result = _runtime("local-whisper-base")
        self.local_available = True

        result = await self.readiness.get_transcription_readiness(self.db)

        self.assertEqual(
            {
                "ready": True,
                "model_id": "local-whisper-base",
                "provider": "local",
                "reason": "",
            },
            result.to_dict(),
        )


if __name__ == "__main__":
    unittest.main()

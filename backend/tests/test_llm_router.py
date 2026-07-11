import unittest
from unittest import mock

from app.services import llm


class LLMRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        local_only = mock.patch.object(
            llm,
            "is_local_only",
            mock.AsyncMock(return_value=False),
        )
        local_only.start()
        self.addCleanup(local_only.stop)

    async def test_openai_model_dispatches_to_openai(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k")), \
             mock.patch.object(llm, "_call_openai", mock.AsyncMock(return_value="openai says")) as call:
            reply = await llm.generate_text("gpt-5.4-mini", "hello")
        self.assertEqual("openai says", reply)
        call.assert_awaited_once()

    async def test_gemini_model_dispatches_to_google(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k")), \
             mock.patch.object(llm, "_call_google", mock.AsyncMock(return_value="gemini says")) as call:
            reply = await llm.generate_text("gemini-3.5-flash", "hello")
        self.assertEqual("gemini says", reply)
        call.assert_awaited_once()

    async def test_unknown_model_defaults_to_google(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k")), \
             mock.patch.object(llm, "_call_google", mock.AsyncMock(return_value="ok")) as call:
            await llm.generate_text("gemini-9.9-legacy-preview", "hello")
        call.assert_awaited_once()

    async def test_missing_key_raises_with_admin_hint(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="")):
            with self.assertRaises(llm.LLMKeyMissing) as ctx:
                await llm.generate_text("gpt-5.5", "hello")
        self.assertIn("openai", str(ctx.exception))
        self.assertIn("Admin -> API Keys", str(ctx.exception))

    def test_provider_for(self):
        self.assertEqual("openai", llm.provider_for("gpt-5.5"))
        self.assertEqual("google", llm.provider_for("gemini-3.5-flash"))
        self.assertEqual("google", llm.provider_for("something-unknown"))

    def test_provider_for_infers_openai_for_legacy_ids(self):
        # Ids removed from the registry but possibly stored in agent_configs
        self.assertEqual("openai", llm.provider_for("gpt-5"))
        self.assertEqual("openai", llm.provider_for("gpt-5-mini"))
        self.assertEqual("openai", llm.provider_for("openai-realtime"))

    def test_registry_has_key_requirements(self):
        from app.config import MODEL_REGISTRY

        for entry in MODEL_REGISTRY:
            self.assertIn("requires_key", entry, f"{entry['id']} missing requires_key")
        ids = {m["id"] for m in MODEL_REGISTRY}
        self.assertIn("gpt-5.5", ids)
        self.assertIn("gpt-5.4", ids)
        self.assertIn("gpt-5.4-mini", ids)
        self.assertIn("gpt-5.4-nano", ids)
        self.assertIn("gpt-5.2", ids)
        self.assertIn("gpt-realtime-whisper", ids)
        self.assertIn("gpt-4o-transcribe", ids)
        self.assertIn("gpt-4o-mini-transcribe", ids)

    def test_openai_realtime_entries_are_live_audio_only(self):
        from app.config import MODEL_REGISTRY

        realtime_ids = {"gpt-realtime-whisper", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"}
        for entry in MODEL_REGISTRY:
            if entry["id"] in realtime_ids:
                self.assertTrue(entry["supports_live_audio"], entry["id"])
                self.assertFalse(entry["supports_text"], entry["id"])
                self.assertFalse(entry["supports_batch_audio"], entry["id"])
                self.assertEqual("openai", entry["requires_key"], entry["id"])


if __name__ == "__main__":
    unittest.main()

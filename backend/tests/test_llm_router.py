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
             mock.patch.object(llm, "_call_openai", mock.AsyncMock(return_value=("openai says", {"total_tokens": 3}))) as call:
            reply = await llm.generate_text("gpt-5.4-mini", "hello")
        self.assertEqual("openai says", reply)
        call.assert_awaited_once()

    async def test_gemini_model_dispatches_to_google(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k")), \
             mock.patch.object(llm, "_call_google", mock.AsyncMock(return_value=("gemini says", None))) as call:
            reply = await llm.generate_text("gemini-3.5-flash", "hello")
        self.assertEqual("gemini says", reply)
        call.assert_awaited_once()

    async def test_unknown_model_defaults_to_google(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k")), \
             mock.patch.object(llm, "_call_google", mock.AsyncMock(return_value=("ok", None))) as call:
            await llm.generate_text("gemini-9.9-legacy-preview", "hello")
        call.assert_awaited_once()

    async def test_attributed_call_records_provider_usage(self):
        usage = {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k")), \
             mock.patch.object(llm, "_call_openai", mock.AsyncMock(return_value=("reply", usage))), \
             mock.patch.object(llm, "record_token_usage", mock.AsyncMock()) as record:
            reply = await llm.generate_text(
                "gpt-5.4-mini",
                "hello",
                session_id="d3e8467e-6ba7-4692-9aa5-bfc4c0ab1f2e",
                source="session_chat",
            )
        self.assertEqual("reply", reply)
        record.assert_awaited_once_with(
            "d3e8467e-6ba7-4692-9aa5-bfc4c0ab1f2e",
            "session_chat",
            "gpt-5.4-mini",
            usage,
        )

    async def test_missing_key_raises_with_admin_hint(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="")):
            with self.assertRaises(llm.LLMKeyMissing) as ctx:
                await llm.generate_text("gpt-5.5", "hello")
        self.assertIn("openai", str(ctx.exception))
        self.assertIn("Admin -> Connections", str(ctx.exception))

    async def test_unselected_model_fails_before_provider_or_key_resolution(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock()) as resolve:
            with self.assertRaises(llm.LLMModelNotSelected) as ctx:
                await llm.generate_text("", "hello", source="consolidated_analyst")

        self.assertIn("consolidated_analyst", str(ctx.exception))
        self.assertIn("Admin -> Agents", str(ctx.exception))
        resolve.assert_not_awaited()

    async def test_unselected_model_http_handler_returns_actionable_conflict(self):
        from app.main import model_not_selected_handler

        response = await model_not_selected_handler(
            None,
            llm.LLMModelNotSelected("analyze"),
        )

        self.assertEqual(409, response.status_code)
        self.assertIn(b"Admin -> Agents", response.body)

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
        self.assertIn("gpt-5.6-sol", ids)
        self.assertIn("gpt-5.6-terra", ids)
        self.assertIn("gpt-5.6-luna", ids)
        self.assertIn("gpt-5.5", ids)
        self.assertIn("gpt-5.4", ids)
        self.assertIn("gpt-5.4-mini", ids)
        self.assertIn("gpt-5.4-nano", ids)
        self.assertNotIn("gpt-5.2", ids)  # superseded; removed from the lineup
        self.assertIn("gpt-live-transcribe", ids)
        self.assertIn("gpt-4o-transcribe", ids)
        self.assertIn("gpt-4o-mini-transcribe", ids)
        self.assertIn("gpt-audio-1.5", ids)
        self.assertIn("gpt-audio-mini", ids)

    def test_latest_gemini_models_are_selectable_for_text_and_batch_audio(self):
        from app.config import MODEL_REGISTRY

        by_id = {model["id"]: model for model in MODEL_REGISTRY}
        for model_id in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"):
            model = by_id[model_id]
            self.assertEqual("Google", model["provider"])
            self.assertEqual("stable", model["tier"])
            self.assertEqual("google", model["requires_key"])
            self.assertTrue(model["supports_text"])
            self.assertTrue(model["supports_batch_audio"])
            self.assertFalse(model["supports_live_audio"])

    def test_gpt56_family_is_selectable_for_text_only(self):
        from app.config import MODEL_REGISTRY

        by_id = {model["id"]: model for model in MODEL_REGISTRY}
        for model_id in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
            model = by_id[model_id]
            self.assertEqual("OpenAI", model["provider"], model_id)
            self.assertEqual("stable", model["tier"], model_id)
            self.assertEqual("openai", model["requires_key"], model_id)
            self.assertTrue(model["supports_text"], model_id)
            self.assertFalse(model["supports_batch_audio"], model_id)
            self.assertFalse(model["supports_live_audio"], model_id)

    def test_openai_speech_entries_have_expected_capabilities(self):
        from app.config import MODEL_REGISTRY

        by_id = {model["id"]: model for model in MODEL_REGISTRY}
        # Streaming-only realtime gateway model: live audio, nothing else.
        live_transcribe = by_id["gpt-live-transcribe"]
        self.assertTrue(live_transcribe["supports_live_audio"])
        self.assertFalse(live_transcribe["supports_text"])
        self.assertFalse(live_transcribe["supports_batch_audio"])
        self.assertEqual("openai", live_transcribe["requires_key"])
        # gpt-4o transcribe models serve both the realtime gateway and the
        # REST /v1/audio/transcriptions batch path.
        for model_id in ("gpt-4o-transcribe", "gpt-4o-mini-transcribe"):
            entry = by_id[model_id]
            self.assertTrue(entry["supports_live_audio"], model_id)
            self.assertTrue(entry["supports_batch_audio"], model_id)
            self.assertFalse(entry["supports_text"], model_id)
            self.assertEqual("openai", entry["requires_key"], model_id)
        # Audio-capable chat models: batch-only via the Chat Completions
        # input_audio path (no realtime gateway or text-agent wiring here).
        for model_id in ("gpt-audio-1.5", "gpt-audio-mini"):
            entry = by_id[model_id]
            self.assertTrue(entry["supports_batch_audio"], model_id)
            self.assertFalse(entry["supports_live_audio"], model_id)
            self.assertFalse(entry["supports_text"], model_id)
            self.assertEqual("openai", entry["requires_key"], model_id)

    def test_gpt56_family_lacks_audio_input_so_batch_stays_off(self):
        # Verified 2026-07-23 against the OpenAI per-model docs: every
        # GPT-5.6/5.5/5.4 page lists audio as "Not supported". Flipping
        # supports_batch_audio on them produces runtime 400s, so this guard
        # pins the whole text lineup off the batch dropdown.
        from app.config import MODEL_REGISTRY

        by_id = {model["id"]: model for model in MODEL_REGISTRY}
        for model_id in (
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-5.5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
        ):
            self.assertFalse(by_id[model_id]["supports_batch_audio"], model_id)


if __name__ == "__main__":
    unittest.main()

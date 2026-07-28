import unittest
from unittest import mock

from app.services import privacy as privacy_mod
from app.services.custom_endpoints import EndpointError, EndpointTarget
from app.services.privacy import (
    DEFAULT_LOCAL_BATCH_MODEL,
    allows_local_only,
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
        available = [item["feature"] for item in impact["available"]]
        disabled = [item["feature"] for item in impact["disabled"]]
        # A local live-caption model exists (local-parakeet-live), so live captions
        # are available on-device; text analysis is still cloud-only by default.
        self.assertIn("Live interim captions (on-device)", available)
        self.assertNotIn("Live interim captions (audio gateway)", disabled)
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

    def test_a_self_hosted_text_model_re_enables_the_analysis_features(self):
        impact = privacy_impact([{"id": "endpoint:lm-studio:antares-1b", "name": "antares-1b"}])
        available = [item["feature"] for item in impact["available"]]
        disabled = [item["feature"] for item in impact["disabled"]]
        self.assertTrue(any("AI analysis agents" in f for f in available))
        self.assertNotIn("AI analysis agents", disabled)
        self.assertNotIn("Meeting chat", disabled)
        # Interim captions now have a local option (the on-device captioner).
        self.assertIn("Live interim captions (on-device)", available)
        self.assertNotIn("Live interim captions (audio gateway)", disabled)
        self.assertIn("antares-1b", "".join(i["detail"] for i in impact["available"]))


class TestPrivacyAllowsSelfHostedModels(unittest.IsolatedAsyncioTestCase):
    """Privacy First is about where data goes, not which vendor serves it."""

    def _patch_target(self, target):
        patcher = mock.patch.object(
            privacy_mod, "resolve_target_standalone", mock.AsyncMock(return_value=target)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _target(self, on_prem: bool):
        return EndpointTarget(
            endpoint_id="lm-studio",
            name="LM Studio",
            base_url="http://localhost:1234/v1" if on_prem else "https://api.together.xyz/v1",
            model="antares-1b",
            api_key="",
            on_prem=on_prem,
            enabled=True,
        )

    async def test_bundled_local_models_are_allowed(self):
        self.assertTrue(await allows_local_only("local-whisper-base"))

    async def test_cloud_models_are_not_allowed(self):
        self.assertFalse(await allows_local_only("gemini-3.5-flash"))
        self.assertFalse(await allows_local_only("gpt-5.4-mini"))

    async def test_a_model_on_this_network_is_allowed(self):
        self._patch_target(self._target(on_prem=True))
        self.assertTrue(await allows_local_only("endpoint:lm-studio:antares-1b"))

    async def test_a_model_on_a_public_endpoint_is_not_allowed(self):
        self._patch_target(self._target(on_prem=False))
        self.assertFalse(await allows_local_only("endpoint:lm-studio:antares-1b"))

    async def test_a_missing_endpoint_is_not_allowed(self):
        self._patch_target(None)
        self.assertFalse(await allows_local_only("endpoint:gone:antares-1b"))

    async def test_a_deleted_endpoint_is_not_allowed(self):
        patcher = mock.patch.object(
            privacy_mod,
            "resolve_target_standalone",
            mock.AsyncMock(side_effect=EndpointError("endpoint was deleted")),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertFalse(await allows_local_only("endpoint:gone:antares-1b"))


if __name__ == "__main__":
    unittest.main()

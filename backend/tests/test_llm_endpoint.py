import unittest
from unittest import mock

from app.config import MODEL_REGISTRY
from app.services import llm, llm_endpoint
from app.services.llm_endpoint import (
    DEFAULT_OPENAI_BASE_URL,
    OPENAI_COMPATIBLE_MODEL,
    OPENAI_COMPATIBLE_PROVIDER,
    OpenAIEndpoint,
    TextEndpointNotConfigured,
    auth_headers,
    is_openai_shaped,
    requires_api_key,
    resolve_base_url,
    resolve_endpoint,
    resolve_wire_model,
    validate_base_url,
)


class _FakeSettings:
    """Stand-in for app.config.settings covering only the endpoint fields."""

    def __init__(self, base_url: str = DEFAULT_OPENAI_BASE_URL, model_id: str = ""):
        self.OPENAI_BASE_URL = base_url
        self.OPENAI_COMPATIBLE_MODEL_ID = model_id


class _FakeDB:
    """Minimal stand-in for the app_settings table."""

    def __init__(self, values: dict | None = None):
        self.values = values or {}


async def _fake_get_app_setting(db, key: str, default: str = "") -> str:
    return db.values.get(key, default)


class BaseUrlPrecedenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.object(
            llm_endpoint, "get_app_setting", mock.AsyncMock(side_effect=_fake_get_app_setting)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_default_is_the_previously_hardcoded_openai_url(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            url = await resolve_base_url(_FakeDB(), OPENAI_COMPATIBLE_PROVIDER)
        self.assertEqual(DEFAULT_OPENAI_BASE_URL, url)

    async def test_env_var_overrides_the_default(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings("http://localhost:11434/v1")):
            url = await resolve_base_url(_FakeDB(), OPENAI_COMPATIBLE_PROVIDER)
        self.assertEqual("http://localhost:11434/v1", url)

    async def test_app_setting_overrides_the_env_var(self):
        db = _FakeDB({llm_endpoint.SETTING_BASE_URL: "http://localhost:1234/v1"})
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings("http://localhost:11434/v1")):
            url = await resolve_base_url(db, OPENAI_COMPATIBLE_PROVIDER)
        self.assertEqual("http://localhost:1234/v1", url)

    async def test_blank_app_setting_falls_back_to_the_env_var(self):
        db = _FakeDB({llm_endpoint.SETTING_BASE_URL: "   "})
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings("http://vllm.internal:8000/v1")):
            url = await resolve_base_url(db, OPENAI_COMPATIBLE_PROVIDER)
        self.assertEqual("http://vllm.internal:8000/v1", url)

    async def test_trailing_slash_is_stripped_so_paths_join_cleanly(self):
        db = _FakeDB({llm_endpoint.SETTING_BASE_URL: "http://localhost:11434/v1/"})
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            url = await resolve_base_url(db, OPENAI_COMPATIBLE_PROVIDER)
        self.assertEqual("http://localhost:11434/v1", url)

    async def test_hosted_openai_provider_ignores_the_app_setting(self):
        # A local Ollama URL saved for the compatible provider must never
        # redirect calls to real OpenAI models.
        db = _FakeDB({llm_endpoint.SETTING_BASE_URL: "http://localhost:11434/v1"})
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            url = await resolve_base_url(db, "openai")
        self.assertEqual(DEFAULT_OPENAI_BASE_URL, url)

    def test_validate_base_url_rejects_non_http_schemes(self):
        with self.assertRaises(ValueError):
            validate_base_url("localhost:11434/v1")
        self.assertEqual("http://localhost:11434/v1", validate_base_url(" http://localhost:11434/v1/ "))
        self.assertEqual("", validate_base_url(""))


class WireModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.object(
            llm_endpoint, "get_app_setting", mock.AsyncMock(side_effect=_fake_get_app_setting)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_other_providers_send_their_registry_id_unchanged(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            model = await resolve_wire_model(_FakeDB(), "openai", "gpt-5.4-mini")
        self.assertEqual("gpt-5.4-mini", model)

    async def test_app_setting_beats_env_var(self):
        db = _FakeDB({llm_endpoint.SETTING_MODEL_ID: "qwen2.5-coder"})
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings(model_id="llama3.1:8b")):
            model = await resolve_wire_model(db, OPENAI_COMPATIBLE_PROVIDER, OPENAI_COMPATIBLE_MODEL)
        self.assertEqual("qwen2.5-coder", model)

    async def test_env_var_used_when_nothing_is_persisted(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings(model_id="llama3.1:8b")):
            model = await resolve_wire_model(_FakeDB(), OPENAI_COMPATIBLE_PROVIDER, OPENAI_COMPATIBLE_MODEL)
        self.assertEqual("llama3.1:8b", model)

    async def test_unconfigured_model_raises_an_actionable_error(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            with self.assertRaises(TextEndpointNotConfigured) as ctx:
                await resolve_wire_model(_FakeDB(), OPENAI_COMPATIBLE_PROVIDER, OPENAI_COMPATIBLE_MODEL)
        self.assertIn("Admin -> Connections", str(ctx.exception))
        # ValueError, so routers already translate it into a 400 rather than a 500.
        self.assertIsInstance(ctx.exception, ValueError)


class KeylessPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        local_only = mock.patch.object(llm, "is_local_only", mock.AsyncMock(return_value=False))
        local_only.start()
        self.addCleanup(local_only.stop)

    def test_only_the_compatible_provider_tolerates_a_missing_key(self):
        self.assertFalse(requires_api_key(OPENAI_COMPATIBLE_PROVIDER))
        self.assertTrue(requires_api_key("openai"))
        self.assertTrue(requires_api_key("google"))

    def test_auth_header_is_omitted_without_a_key(self):
        self.assertEqual({}, auth_headers(""))
        self.assertEqual({"Authorization": "Bearer sk-x"}, auth_headers("sk-x"))

    def test_both_openai_dialects_use_the_openai_request_shape(self):
        self.assertTrue(is_openai_shaped("openai"))
        self.assertTrue(is_openai_shaped(OPENAI_COMPATIBLE_PROVIDER))
        self.assertFalse(is_openai_shaped("google"))

    async def test_generate_text_runs_without_a_key_for_the_local_endpoint(self):
        endpoint = OpenAIEndpoint(base_url="http://localhost:11434/v1", model="llama3.1:8b")
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="")), \
             mock.patch.object(llm, "resolve_endpoint", mock.AsyncMock(return_value=endpoint)), \
             mock.patch.object(llm, "record_token_usage", mock.AsyncMock()), \
             mock.patch.object(llm, "_call_openai", mock.AsyncMock(return_value=("local reply", None))) as call:
            reply = await llm.generate_text(OPENAI_COMPATIBLE_MODEL, "hello")
        self.assertEqual("local reply", reply)
        self.assertEqual(endpoint, call.await_args.args[0])
        self.assertEqual("", call.await_args.args[4])

    async def test_hosted_openai_still_requires_a_key(self):
        with mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="")):
            with self.assertRaises(llm.LLMKeyMissing):
                await llm.generate_text("gpt-5.4-mini", "hello")

    async def test_hosted_openai_default_endpoint_is_unchanged(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            endpoint = await resolve_endpoint("openai", "gpt-5.4-mini")
        self.assertEqual(DEFAULT_OPENAI_BASE_URL, endpoint.base_url)
        self.assertEqual("gpt-5.4-mini", endpoint.model)


class EndpointModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    """An "endpoint:..." model must reach its own server with its own key."""

    def _target(self, **overrides):
        from app.services.custom_endpoints import EndpointTarget

        fields = {
            "endpoint_id": "lm-studio",
            "name": "LM Studio",
            "base_url": "http://localhost:1234/v1",
            "model": "antares-1b",
            "api_key": "",
            "on_prem": True,
            "enabled": True,
        }
        fields.update(overrides)
        return EndpointTarget(**fields)

    async def test_endpoint_model_uses_its_own_base_url_and_wire_name(self):
        with mock.patch.object(
            llm_endpoint, "resolve_target", mock.AsyncMock(return_value=self._target())
        ):
            endpoint = await llm_endpoint.resolve_endpoint_with(
                _FakeDB(), OPENAI_COMPATIBLE_PROVIDER, "endpoint:lm-studio:antares-1b"
            )
        self.assertEqual("http://localhost:1234/v1", endpoint.base_url)
        self.assertEqual("antares-1b", endpoint.model)
        # "" not None: an endpoint answers for its own key, keyless included,
        # so the provider-wide OpenAI-compatible key is never consulted.
        self.assertEqual("", endpoint.api_key)

    async def test_endpoint_key_overrides_the_provider_key(self):
        with mock.patch.object(
            llm_endpoint, "resolve_target", mock.AsyncMock(return_value=self._target(api_key="sk-endpoint"))
        ):
            endpoint = await llm_endpoint.resolve_endpoint_with(
                _FakeDB(), OPENAI_COMPATIBLE_PROVIDER, "endpoint:lm-studio:antares-1b"
            )
        self.assertEqual("sk-endpoint", endpoint.api_key)

    async def test_a_removed_endpoint_reports_an_actionable_error(self):
        with mock.patch.object(llm_endpoint, "resolve_target", mock.AsyncMock(return_value=None)):
            with self.assertRaises(llm_endpoint.EndpointUnavailable) as ctx:
                await llm_endpoint.resolve_endpoint_with(
                    _FakeDB(), OPENAI_COMPATIBLE_PROVIDER, "endpoint:gone:some-model"
                )
        self.assertIn("no longer exists", str(ctx.exception))
        # ValueError, so routers translate it into a 400 rather than a 500.
        self.assertIsInstance(ctx.exception, ValueError)

    async def test_a_disabled_endpoint_is_not_silently_used(self):
        with mock.patch.object(
            llm_endpoint, "resolve_target", mock.AsyncMock(return_value=self._target(enabled=False))
        ):
            with self.assertRaises(llm_endpoint.EndpointUnavailable) as ctx:
                await llm_endpoint.resolve_endpoint_with(
                    _FakeDB(), OPENAI_COMPATIBLE_PROVIDER, "endpoint:lm-studio:antares-1b"
                )
        self.assertIn("turned off", str(ctx.exception))

    def test_endpoint_models_route_to_the_openai_compatible_dialect(self):
        self.assertEqual(
            OPENAI_COMPATIBLE_PROVIDER, llm.provider_for("endpoint:lm-studio:antares-1b")
        )
        # Even when the served name looks like another provider's model.
        self.assertEqual(
            OPENAI_COMPATIBLE_PROVIDER, llm.provider_for("endpoint:proxy:gpt-4o-mini")
        )

    async def test_a_keyless_endpoint_model_needs_no_provider_key(self):
        endpoint = OpenAIEndpoint(
            base_url="http://localhost:1234/v1", model="antares-1b", api_key=""
        )
        with mock.patch.object(llm, "is_local_only", mock.AsyncMock(return_value=False)), \
             mock.patch.object(llm, "resolve_endpoint", mock.AsyncMock(return_value=endpoint)), \
             mock.patch.object(llm, "_resolve_key", mock.AsyncMock(side_effect=AssertionError)), \
             mock.patch.object(llm, "record_token_usage", mock.AsyncMock()), \
             mock.patch.object(llm, "_call_openai", mock.AsyncMock(return_value=("hi", None))) as call:
            reply = await llm.generate_text("endpoint:lm-studio:antares-1b", "hello")
        self.assertEqual("hi", reply)
        self.assertEqual(endpoint, call.await_args.args[0])
        self.assertEqual("", call.await_args.args[4])


class LegacyEndpointRetirementTests(unittest.IsolatedAsyncioTestCase):
    """The placeholder model only exists while the old settings are in use."""

    def setUp(self):
        patcher = mock.patch.object(
            llm_endpoint, "get_app_setting", mock.AsyncMock(side_effect=_fake_get_app_setting)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_unconfigured_legacy_endpoint_is_not_advertised(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            self.assertFalse(await llm_endpoint.legacy_endpoint_configured(_FakeDB()))

    async def test_a_persisted_base_url_keeps_it_advertised(self):
        db = _FakeDB({llm_endpoint.SETTING_BASE_URL: "http://localhost:1234/v1"})
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings()):
            self.assertTrue(await llm_endpoint.legacy_endpoint_configured(db))

    async def test_an_env_configured_install_keeps_it_advertised(self):
        with mock.patch.object(llm_endpoint, "settings", _FakeSettings(model_id="llama3.1:8b")):
            self.assertTrue(await llm_endpoint.legacy_endpoint_configured(_FakeDB()))


class RegistryEntryTests(unittest.TestCase):
    def test_compatible_entry_is_a_keyless_text_model(self):
        entry = next(m for m in MODEL_REGISTRY if m["id"] == OPENAI_COMPATIBLE_MODEL)
        self.assertEqual("OpenAI-Compatible", entry["provider"])
        self.assertIsNone(entry["requires_key"])
        self.assertTrue(entry["supports_text"])
        self.assertFalse(entry["supports_batch_audio"])
        self.assertFalse(entry["supports_live_audio"])

    def test_provider_for_routes_the_entry_to_the_compatible_provider(self):
        self.assertEqual(OPENAI_COMPATIBLE_PROVIDER, llm.provider_for(OPENAI_COMPATIBLE_MODEL))


if __name__ == "__main__":
    unittest.main()

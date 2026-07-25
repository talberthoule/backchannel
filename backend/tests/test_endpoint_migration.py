"""Promotion of the single pre-endpoints text endpoint to a named endpoint.

An install that had configured one OpenAI-compatible server must come back
identical after the upgrade, except that its model is now visible by name in
the pickers instead of hiding behind a placeholder entry.
"""

import unittest
from unittest import mock

from app.services import llm_endpoint
from app.services.llm_endpoint import OPENAI_COMPATIBLE_MODEL


class _FakeDB:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)

    async def commit(self):
        pass


class LegacyEndpointMigrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings_store = {}
        self.created = []
        self.existing = []

        async def fake_get(db, key, default=""):
            return self.settings_store.get(key, default)

        async def fake_set(db, key, value):
            self.settings_store[key] = value

        async def fake_create(db, **kwargs):
            self.created.append(kwargs)
            return mock.Mock(id="lm-studio", name=kwargs["name"])

        self.patches = [
            mock.patch.object(llm_endpoint, "get_app_setting", fake_get),
            mock.patch.object(llm_endpoint, "set_app_setting", fake_set),
            mock.patch.object(llm_endpoint, "create_endpoint", fake_create),
            mock.patch.object(
                llm_endpoint, "list_endpoints", mock.AsyncMock(side_effect=lambda db: self.existing)
            ),
            mock.patch.object(llm_endpoint, "get_secret", mock.AsyncMock(return_value="")),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _configure(self, base_url="http://localhost:1234/v1", model_id="antares-1b"):
        self.settings_store[llm_endpoint.SETTING_BASE_URL] = base_url
        self.settings_store[llm_endpoint.SETTING_MODEL_ID] = model_id

    async def test_configured_endpoint_becomes_a_named_endpoint(self):
        self._configure()
        new_model_id = await llm_endpoint.migrate_legacy_endpoint(_FakeDB())
        self.assertEqual("endpoint:lm-studio:antares-1b", new_model_id)
        self.assertEqual(1, len(self.created))
        self.assertEqual("http://localhost:1234/v1", self.created[0]["base_url"])
        self.assertEqual([{"id": "antares-1b"}], self.created[0]["models"])

    async def test_the_server_is_named_from_its_port(self):
        self._configure(base_url="http://localhost:11434/v1", model_id="llama3.1:8b")
        await llm_endpoint.migrate_legacy_endpoint(_FakeDB())
        self.assertEqual("Ollama", self.created[0]["name"])

    async def test_an_unrecognized_port_gets_a_neutral_name(self):
        self._configure(base_url="http://gpu-box:9999/v1")
        await llm_endpoint.migrate_legacy_endpoint(_FakeDB())
        self.assertEqual("Custom endpoint", self.created[0]["name"])

    async def test_agents_are_repointed_at_the_migrated_model(self):
        self._configure()
        db = _FakeDB()
        await llm_endpoint.migrate_legacy_endpoint(db)
        self.assertEqual(1, len(db.statements))
        compiled = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("UPDATE agent_configs", compiled)
        self.assertIn("endpoint:lm-studio:antares-1b", compiled)
        self.assertIn(OPENAI_COMPATIBLE_MODEL, compiled)

    async def test_the_old_settings_are_cleared_so_the_placeholder_retires(self):
        self._configure()
        await llm_endpoint.migrate_legacy_endpoint(_FakeDB())
        self.assertEqual("", self.settings_store[llm_endpoint.SETTING_BASE_URL])
        self.assertEqual("", self.settings_store[llm_endpoint.SETTING_MODEL_ID])

    async def test_an_existing_key_carries_over_to_the_endpoint(self):
        self._configure()
        with mock.patch.object(llm_endpoint, "get_secret", mock.AsyncMock(return_value="sk-proxy")):
            await llm_endpoint.migrate_legacy_endpoint(_FakeDB())
        self.assertEqual("sk-proxy", self.created[0]["api_key"])

    async def test_nothing_happens_when_the_old_config_is_incomplete(self):
        # A base URL with no model was never usable; leave it for the user.
        self.settings_store[llm_endpoint.SETTING_BASE_URL] = "http://localhost:1234/v1"
        self.assertIsNone(await llm_endpoint.migrate_legacy_endpoint(_FakeDB()))
        self.assertEqual([], self.created)

    async def test_nothing_happens_on_an_unconfigured_install(self):
        self.assertIsNone(await llm_endpoint.migrate_legacy_endpoint(_FakeDB()))
        self.assertEqual([], self.created)

    async def test_it_does_not_run_twice(self):
        self._configure()
        self.existing = [mock.Mock(id="lm-studio")]
        self.assertIsNone(await llm_endpoint.migrate_legacy_endpoint(_FakeDB()))
        self.assertEqual([], self.created)


if __name__ == "__main__":
    unittest.main()

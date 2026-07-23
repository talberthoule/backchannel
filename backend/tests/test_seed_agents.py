import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.agents.prompts import OPPORTUNITY_SPECIALIST_PROMPT
from app.services.seed_agents import (
    DEFAULT_MODEL_VERSION,
    DEFAULT_MODEL_VERSION_KEY,
    FORCED_DEFAULT_MODELS,
    SEED_CONFIGS,
    apply_default_model_version,
    _should_refresh_seeded_model,
    _should_refresh_seeded_prompt,
)
from app.services.transcription_runtime import SETTING_BATCH_TRANSCRIBER_MODEL


class SeedAgentConfigTests(unittest.TestCase):
    def test_strategic_signals_is_a_configurable_live_agent(self):
        cfg = _seed_config("strategic_signals")

        self.assertEqual("Strategic Signals", cfg["name"])
        self.assertEqual("meta", cfg["agent_type"])
        self.assertEqual("gemini-3.6-flash", cfg["model_id"])
        self.assertEqual(45, cfg["interval_seconds"])
        self.assertTrue(cfg["enabled"])
        self.assertIn("{insights_text}", cfg["prompt"])
        self.assertIn("evidence_refs", cfg["prompt"])

    def test_v025_seed_model_defaults(self):
        expected = {
            "consolidated_analyst": "gemini-3.6-flash",
            "opportunity_specialist": "gemini-3.6-flash",
            "brief_meeting_lens": "gemini-3.6-flash",
            "brief_discovery_lens": "gemini-3.6-flash",
            "brief_arbiter": "gemini-3.6-flash",
            "objection_handler": "gemini-3.5-flash-lite",
        }

        self.assertEqual(
            expected,
            {slug: _seed_config(slug)["model_id"] for slug in expected},
        )

    def test_nonobsolete_old_default_is_preserved_after_versioned_migration(self):
        cfg = _seed_config("consolidated_analyst")
        existing = SimpleNamespace(slug="consolidated_analyst", model_id="gemini-3-flash-preview")

        self.assertFalse(_should_refresh_seeded_model(existing, cfg))

    def test_current_seed_default_does_not_refresh(self):
        cfg = _seed_config("consolidated_analyst")
        existing = SimpleNamespace(slug="consolidated_analyst", model_id=cfg["model_id"])

        self.assertFalse(_should_refresh_seeded_model(existing, cfg))

    def test_obsolete_model_refreshes(self):
        cfg = _seed_config("brief_arbiter")
        existing = SimpleNamespace(slug="brief_arbiter", model_id="gemini-2.5-pro-preview-05-06")

        self.assertTrue(_should_refresh_seeded_model(existing, cfg))

    def test_nondefault_current_preview_model_is_preserved(self):
        cfg = _seed_config("brief_arbiter")
        existing = SimpleNamespace(slug="brief_arbiter", model_id="gemini-3-flash-preview")

        self.assertFalse(_should_refresh_seeded_model(existing, cfg))


class SeedPromptRefreshTests(unittest.TestCase):
    def test_stale_offerings_placeholder_prompt_refreshes(self):
        cfg = _seed_config("opportunity_specialist")
        existing = SimpleNamespace(
            slug="opportunity_specialist",
            prompt="Match these opportunities.\n{offerings_catalog}\n{opportunities_json}",
        )

        self.assertTrue(_should_refresh_seeded_prompt(existing, cfg))

    def test_new_default_prompt_does_not_refresh(self):
        cfg = _seed_config("opportunity_specialist")
        existing = SimpleNamespace(slug="opportunity_specialist", prompt=cfg["prompt"])

        self.assertFalse(_should_refresh_seeded_prompt(existing, cfg))

    def test_default_prompt_uses_knowledge_context_placeholder(self):
        self.assertIn("{knowledge_context}", OPPORTUNITY_SPECIALIST_PROMPT)
        self.assertIn("{opportunities_json}", OPPORTUNITY_SPECIALIST_PROMPT)
        self.assertNotIn("{offerings_catalog}", OPPORTUNITY_SPECIALIST_PROMPT)
        # Must format without KeyError (braces in JSON examples are escaped)
        OPPORTUNITY_SPECIALIST_PROMPT.format(knowledge_context="ctx", opportunities_json="[]")


class DefaultModelVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_version_forces_all_requested_defaults_once(self):
        agents = [SimpleNamespace(slug=slug, model_id="custom") for slug in FORCED_DEFAULT_MODELS]
        db = _FakeSession(agents=agents)

        changed = await apply_default_model_version(db)

        self.assertTrue(changed)
        self.assertEqual(
            FORCED_DEFAULT_MODELS,
            {agent.slug: agent.model_id for agent in agents},
        )
        self.assertEqual(
            "gemini-3.5-flash-lite",
            db.settings[SETTING_BATCH_TRANSCRIBER_MODEL].value,
        )
        self.assertEqual(DEFAULT_MODEL_VERSION, db.settings[DEFAULT_MODEL_VERSION_KEY].value)
        db.commit.assert_awaited_once()

    async def test_current_version_preserves_later_user_selections(self):
        marker = SimpleNamespace(key=DEFAULT_MODEL_VERSION_KEY, value=DEFAULT_MODEL_VERSION)
        agent = SimpleNamespace(slug="consolidated_analyst", model_id="gemini-2.5-pro")
        db = _FakeSession(agents=[agent], settings={DEFAULT_MODEL_VERSION_KEY: marker})

        changed = await apply_default_model_version(db)

        self.assertFalse(changed)
        self.assertEqual("gemini-2.5-pro", agent.model_id)
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()


def _seed_config(slug: str) -> dict:
    return next(cfg for cfg in SEED_CONFIGS if cfg["slug"] == slug)


class _FakeSession:
    def __init__(self, *, agents, settings=None):
        self.agents = agents
        self.settings = dict(settings or {})
        self.execute = mock.AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: self.agents)
        )
        self.flush = mock.AsyncMock()
        self.commit = mock.AsyncMock()

    async def get(self, _model, key):
        return self.settings.get(key)

    def add(self, setting):
        self.settings[setting.key] = setting


if __name__ == "__main__":
    unittest.main()

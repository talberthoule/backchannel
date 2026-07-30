import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.agents.prompts import OPPORTUNITY_SPECIALIST_PROMPT
from app.models import AgentConfig
from app.services.seed_agents import (
    SEED_CONFIGS,
    seed_agent_configs,
)
from app.services.transcription_runtime import SETTING_BATCH_TRANSCRIBER_MODEL


class SeedAgentConfigTests(unittest.TestCase):
    def test_strategic_signals_is_a_configurable_live_agent(self):
        cfg = _seed_config("strategic_signals")

        self.assertEqual("Strategic Signals", cfg["name"])
        self.assertEqual("meta", cfg["agent_type"])
        self.assertEqual("", cfg["model_id"])
        self.assertEqual(45, cfg["interval_seconds"])
        self.assertTrue(cfg["enabled"])
        self.assertIn("{insights_text}", cfg["prompt"])
        self.assertIn("evidence_refs", cfg["prompt"])

    def test_every_fresh_agent_starts_unselected(self):
        self.assertTrue(SEED_CONFIGS)
        self.assertEqual({""}, {cfg["model_id"] for cfg in SEED_CONFIGS})


class SeedPromptTests(unittest.TestCase):
    def test_default_prompt_uses_knowledge_context_placeholder(self):
        self.assertIn("{knowledge_context}", OPPORTUNITY_SPECIALIST_PROMPT)
        self.assertIn("{opportunities_json}", OPPORTUNITY_SPECIALIST_PROMPT)
        self.assertNotIn("{offerings_catalog}", OPPORTUNITY_SPECIALIST_PROMPT)
        # Must format without KeyError (braces in JSON examples are escaped)
        OPPORTUNITY_SPECIALIST_PROMPT.format(knowledge_context="ctx", opportunities_json="[]")


class SeedPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_model_prompt_interval_and_batch_choice_are_preserved(self):
        agents = [_existing_agent(cfg) for cfg in SEED_CONFIGS]
        analyst = next(agent for agent in agents if agent.slug == "consolidated_analyst")
        analyst.model_id = "gpt-5.6-terra"
        analyst.prompt = "My saved prompt"
        analyst.interval_seconds = 45
        batch = SimpleNamespace(
            key=SETTING_BATCH_TRANSCRIBER_MODEL,
            value="gpt-4o-mini-transcribe",
        )
        db = _FakeSession(agents=agents, settings={batch.key: batch})

        await seed_agent_configs(db)

        self.assertEqual("gpt-5.6-terra", analyst.model_id)
        self.assertEqual("My saved prompt", analyst.prompt)
        self.assertEqual(45, analyst.interval_seconds)
        self.assertEqual("gpt-4o-mini-transcribe", batch.value)
        db.commit.assert_awaited_once()

    async def test_missing_rows_are_blank_and_missing_batch_setting_is_keyless(self):
        db = _FakeSession(agents=[])

        await seed_agent_configs(db)

        added_agents = [item for item in db.added if isinstance(item, AgentConfig)]
        self.assertEqual(len(SEED_CONFIGS), len(added_agents))
        self.assertEqual({""}, {agent.model_id for agent in added_agents})
        self.assertEqual(
            "local-whisper-base",
            db.settings[SETTING_BATCH_TRANSCRIBER_MODEL].value,
        )


def _seed_config(slug: str) -> dict:
    return next(cfg for cfg in SEED_CONFIGS if cfg["slug"] == slug)


class _FakeSession:
    def __init__(self, *, agents, settings=None):
        self.agents = agents
        self.settings = dict(settings or {})
        self._results = iter(
            SimpleNamespace(scalar_one_or_none=lambda agent=agent: agent)
            for agent in agents
        )
        self.execute = mock.AsyncMock(side_effect=self._execute)
        self.flush = mock.AsyncMock()
        self.commit = mock.AsyncMock()
        self.added = []

    async def get(self, _model, key):
        return self.settings.get(key)

    def add(self, item):
        self.added.append(item)
        if hasattr(item, "key"):
            self.settings[item.key] = item

    def _execute(self, _statement):
        return next(
            self._results,
            SimpleNamespace(scalar_one_or_none=lambda: None),
        )


def _existing_agent(cfg: dict):
    values = dict(cfg)
    values.setdefault("lenses", "")
    values.setdefault("sub_types", "")
    values.setdefault("interval_seconds", 0)
    return SimpleNamespace(**values)


if __name__ == "__main__":
    unittest.main()

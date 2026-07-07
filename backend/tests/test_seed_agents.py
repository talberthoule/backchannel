import unittest
from types import SimpleNamespace

from app.services.agents.prompts import OPPORTUNITY_SPECIALIST_PROMPT
from app.services.seed_agents import (
    SEED_CONFIGS,
    _should_refresh_seeded_model,
    _should_refresh_seeded_prompt,
)


class SeedAgentConfigTests(unittest.TestCase):
    def test_old_default_model_refreshes_to_seed_default(self):
        cfg = _seed_config("consolidated_analyst")
        existing = SimpleNamespace(slug="consolidated_analyst", model_id="gemini-3-flash-preview")

        self.assertTrue(_should_refresh_seeded_model(existing, cfg))

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


def _seed_config(slug: str) -> dict:
    return next(cfg for cfg in SEED_CONFIGS if cfg["slug"] == slug)


if __name__ == "__main__":
    unittest.main()

"""Static-first prompt ordering (ALP-285).

A prompt cache can only reuse a stable *prefix*. Any static instruction sitting
after a volatile placeholder is content that can never be cached, because
everything downstream of a changed byte is re-read. PRINCIPAL_AGENT_PROMPT used
to keep 41 percent of its instructions after {insights_json}, so no cacheable
prefix could ever form.

This is a structural guard, not a style rule: it fails the moment someone
appends an instruction to the bottom of a template.
"""

import re
import unittest
from types import SimpleNamespace

from app.services import seed_agents
from app.services.agents import prompts
from app.services.agents.consolidated_analyst import (
    SPEAKER_ATTRIBUTION_APPENDIX,
    ConsolidatedAnalystAgent,
)

# Templates whose placeholders are filled per cycle from live call state.
ORDERED_TEMPLATES = [
    "PRINCIPAL_AGENT_PROMPT",
    "CONSOLIDATED_ANALYST_BASE_PROMPT",
    "OBJECTION_HANDLER_PROMPT",
    "OPPORTUNITY_SPECIALIST_PROMPT",
    "STRATEGIC_SIGNALS_PROMPT",
]

# A doubled brace is a literal brace in JSON examples, not a placeholder.
PLACEHOLDER_RE = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")

# Room for a closing sentence or heading, not a whole instruction block.
MAX_TRAILING_STATIC_CHARS = 120


def trailing_static(template: str) -> str:
    matches = list(PLACEHOLDER_RE.finditer(template))
    if not matches:
        return ""
    return template[matches[-1].end():].strip()


class PromptOrderingTests(unittest.TestCase):
    def test_no_instruction_block_follows_the_last_volatile_placeholder(self):
        for name in ORDERED_TEMPLATES:
            template = getattr(prompts, name)
            with self.subTest(prompt=name):
                tail = trailing_static(template)
                self.assertLessEqual(
                    len(tail),
                    MAX_TRAILING_STATIC_CHARS,
                    f"{name} keeps {len(tail)} chars of static text after its last "
                    f"placeholder; move it above the volatile sections so a prefix "
                    f"can form. Tail begins: {tail[:120]!r}",
                )

    def test_every_ordered_template_actually_has_placeholders(self):
        # Guards the guard: a template with no placeholders would pass vacuously.
        for name in ORDERED_TEMPLATES:
            with self.subTest(prompt=name):
                self.assertTrue(PLACEHOLDER_RE.search(getattr(prompts, name)))

    def test_the_default_analyst_prompt_does_not_get_its_speaker_block_appended(self):
        # The appendix is added only when a prompt lacks the section, and it
        # lands at the very end -- after the transcript. The default prompt now
        # carries the section in a static-first position so that never fires.
        self.assertIn(
            "## Speaker Attribution Requirements",
            prompts.CONSOLIDATED_ANALYST_BASE_PROMPT,
        )
        agent = ConsolidatedAnalystAgent()
        # Assert placement, not absence: the baked-in section is byte-identical
        # to the appendix constant, so a substring check would match the
        # correctly-placed copy too. What matters is that it appears once and
        # that nothing static trails the transcript.
        self.assertEqual(1, agent._prompt_template.count("## Speaker Attribution Requirements"))
        self.assertFalse(agent._prompt_template.rstrip().endswith(SPEAKER_ATTRIBUTION_APPENDIX.rstrip()))
        self.assertLessEqual(len(trailing_static(agent._prompt_template)), MAX_TRAILING_STATIC_CHARS)

    def test_a_custom_prompt_without_the_section_still_gets_it(self):
        agent = ConsolidatedAnalystAgent(prompt_override="Custom prompt {transcript_window}")
        self.assertIn("## Speaker Attribution Requirements", agent._prompt_template)


class StoredPromptsOverrideTheReorderTests(unittest.TestCase):
    """The reorder above only reaches an install whose stored prompt is refreshed.

    LegacyOrderingMigrationTests used to live here and asserted that a stale
    stored prompt was rewritten on startup via seed_agents._should_refresh_
    seeded_prompt and LEGACY_ORDERING_MARKERS. v0.5.0 deleted that entire
    migration path: seed_agent_configs now only inserts missing rows, syncs
    seed-owned descriptions, and backfills lenses. It never rewrites a stored
    prompt.

    The consequence is worth keeping visible rather than deleting silently.
    agent_configs.prompt wins over the module constant at runtime, so on any
    install whose rows predate this commit the static-first ordering - and the
    cacheable prefix it exists to create - is inert until the operator resets
    that agent's prompt to default. The reset path is
    routers/agents.py, which serves DEFAULT_PROMPTS.
    """

    def test_seeding_no_longer_rewrites_a_stored_prompt(self):
        # Pins the upstream behavior this warning depends on: if a future change
        # reintroduces prompt refreshing, this fails and the note above is stale.
        self.assertFalse(hasattr(seed_agents, "_should_refresh_seeded_prompt"))
        self.assertFalse(hasattr(seed_agents, "LEGACY_ORDERING_MARKERS"))

    def test_a_stored_prompt_beats_the_module_default(self):
        agent = ConsolidatedAnalystAgent(prompt_override="MY STORED PROMPT {lens_sections}")
        self.assertIn("MY STORED PROMPT", agent._prompt_template)
        self.assertNotIn("You are a multi-disciplinary analyst", agent._prompt_template)


if __name__ == "__main__":
    unittest.main()

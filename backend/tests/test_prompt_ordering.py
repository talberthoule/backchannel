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
from app.services.agents import prompt_layout, prompts
from app.services.meeting_context import format_prompt_layers
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

# Post-call templates. Already correctly ordered when ALP-285 was written, and
# held to the same invariant so they stay that way.
LENS_TEMPLATES = [
    "BRIEF_MEETING_LENS_PROMPT",
    "BRIEF_DISCOVERY_LENS_PROMPT",
    "BRIEF_ARBITER_PROMPT",
]

# A doubled brace is a literal brace in JSON examples, not a placeholder.
PLACEHOLDER_RE = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")

# Room for a closing sentence or heading, not a whole instruction block.
MAX_TRAILING_STATIC_CHARS = 120


# The tail check lives in the module the seam uses, so the guard and the
# runtime read the same definition of a placeholder.
trailing_static = prompt_layout.trailing_static


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


class NoStaticBlockAfterTheFirstVolatileSectionTests(unittest.TestCase):
    """The stronger invariant, and the one that was still being broken.

    The trailing check above only sees text after the LAST placeholder, so a
    template could pass it while stranding a whole Output Format block in the
    middle - which is exactly what OBJECTION_HANDLER_PROMPT did: about 1,014
    chars of contract, rules and directives sat below {recent_objections} and
    above {transcript_window}, invisible to a tail check and uncacheable all
    the same.
    """

    def test_no_shipped_template_strands_instructions_mid_prompt(self):
        for name in ORDERED_TEMPLATES + LENS_TEMPLATES:
            template = getattr(prompts, name)
            with self.subTest(prompt=name):
                stranded = prompt_layout.static_after_volatile(template)
                self.assertEqual(
                    [],
                    stranded,
                    f"{name} keeps {sum(len(part) for part in stranded)} chars of static "
                    f"text after its first volatile section, which no prefix cache can "
                    f"reach. First stranded heading: "
                    f"{stranded[0].splitlines()[0] if stranded else ''!r}",
                )

    def test_the_enhancement_template_is_ordered_too(self):
        # Not in prompts.py, and it runs once per batch of a revalidation run.
        from app.services.speaker_context_enhancer import ENHANCEMENT_PROMPT_TEMPLATE

        self.assertEqual([], prompt_layout.static_after_volatile(
            prompt_layout.stable_first(ENHANCEMENT_PROMPT_TEMPLATE)
        ))

    def test_the_reorder_is_a_no_op_on_an_already_ordered_template(self):
        # A stored prompt that is already correct must come back byte-identical,
        # or every install would see a one-time cache miss for no reason.
        for name in ORDERED_TEMPLATES + LENS_TEMPLATES:
            template = getattr(prompts, name)
            with self.subTest(prompt=name):
                self.assertEqual(template, prompt_layout.stable_first(template))


class LayoutTransformTests(unittest.TestCase):
    TEMPLATE = (
        "You are an agent.\n\n"
        "## Meeting Context\n{meeting_context_text}\n\n"
        "## Recent Transcript\n{transcript_window}\n\n"
        "## Output Format\nReturn JSON.\n\n"
        "## Call Directives\n{directives_text}\n"
    )

    def test_static_sections_are_hoisted_and_relative_order_is_kept(self):
        reordered = prompt_layout.stable_first(self.TEMPLATE)
        self.assertLess(reordered.index("## Output Format"), reordered.index("## Recent Transcript"))
        self.assertLess(reordered.index("## Call Directives"), reordered.index("## Recent Transcript"))
        # Order within each group survives: preamble, then context, then the
        # contract, then directives.
        self.assertLess(reordered.index("You are an agent."), reordered.index("## Meeting Context"))
        self.assertLess(reordered.index("## Output Format"), reordered.index("## Call Directives"))

    def test_the_reorder_moves_text_and_never_changes_it(self):
        reordered = prompt_layout.stable_first(self.TEMPLATE)
        self.assertEqual(
            sorted(prompt_layout.sections(self.TEMPLATE)),
            sorted(prompt_layout.sections(reordered)),
        )

    def test_the_split_cuts_at_the_first_volatile_section(self):
        system, user = prompt_layout.split_layers(self.TEMPLATE)
        self.assertIn("You are an agent.", system)
        self.assertIn("## Output Format", system)
        self.assertIn("{directives_text}", system)
        self.assertNotIn("{transcript_window}", system)
        self.assertIn("{transcript_window}", user)
        self.assertNotIn("## Output Format", user)

    def test_a_template_with_no_headings_is_passed_through_whole(self):
        plain = "Just do the thing with {transcript_window}."
        self.assertEqual(plain, prompt_layout.stable_first(plain))
        system, user = prompt_layout.split_layers(plain)
        self.assertEqual("", system)
        self.assertEqual(plain, user)

    def test_a_template_with_nothing_volatile_stays_in_the_user_turn(self):
        # An empty request would be worse than an unsplit one.
        static = "## A\nOne.\n\n## B\n{speakers_text}\n"
        system, user = prompt_layout.split_layers(static)
        self.assertEqual("", system)
        self.assertEqual(static, user)

    def test_a_json_example_brace_is_not_read_as_a_placeholder(self):
        section = '## Output Format\n{{"op": "answer", "id": "x"}}\n'
        self.assertEqual(set(), prompt_layout.placeholders(section))
        self.assertFalse(prompt_layout.is_volatile(section))

    def test_format_layers_renders_both_halves_from_one_value_set(self):
        system, user = prompt_layout.format_layers(
            self.TEMPLATE,
            meeting_context_text="A sales call",
            transcript_window="Hello there",
            directives_text="- Ask about budget",
        )
        self.assertIn("A sales call", system)
        self.assertIn("- Ask about budget", system)
        self.assertIn("Hello there", user)
        self.assertNotIn("A sales call", user)

    def test_format_layers_returns_none_when_there_was_nothing_to_lift(self):
        system, user = prompt_layout.format_layers(
            "All one piece: {transcript_window}", transcript_window="Hi"
        )
        self.assertIsNone(system, "None, not empty string: the caller sends no system turn")
        self.assertEqual("All one piece: Hi", user)


class TheSeamReachesAStoredPromptTests(unittest.TestCase):
    """Editing prompts.py reaches a fresh install and nobody else.

    agent_configs.prompt holds a user-editable copy that wins at runtime, and
    seeding has never rewritten one. So the reorder has to happen at format
    time, and it has to work on a prompt whose order a user made worse.
    """

    def test_a_badly_ordered_stored_prompt_is_normalized_at_format_time(self):
        stored = (
            "You are an agent.\n\n"
            "## Meeting Context\n{meeting_context_text}\n\n"
            "## Recent Transcript\n{transcript_window}\n\n"
            "## Rules\nBe brief.\n"
        )
        system, user = format_prompt_layers(
            stored, "An internal check-in", transcript_window="Some speech"
        )
        self.assertIn("Be brief.", system)
        self.assertNotIn("Be brief.", user)
        self.assertIn("Some speech", user)

    def test_a_prompt_missing_the_meeting_context_placeholder_still_gets_one(self):
        system, user = format_prompt_layers(
            "## Rules\nBe brief.\n\n## Transcript\n{transcript_window}\n",
            "An internal check-in",
            transcript_window="Some speech",
        )
        self.assertIn("An internal check-in", system)
        self.assertIn("Some speech", user)


if __name__ == "__main__":
    unittest.main()

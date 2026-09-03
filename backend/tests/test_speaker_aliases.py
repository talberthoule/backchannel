"""Short speaker aliases, and the round-trip that keeps attribution honest.

Every transcript line used to carry the speaker's full 36-character UUID. On a
measured 57-minute meeting that was 48 percent of the formatted transcript
payload, and the window is re-read seven to nine times per utterance across
the live agents, so the overhead was multiplied rather than paid once (ALP-282).

Three properties matter more than the saving:

* The map is derived, never stored, so a fresh orchestrator on a resumed call
  produces the same one. Nothing persisted depends on it.
* An alias resolves back to the canonical UUID before anything is saved, and a
  raw UUID still resolves too, so a prompt a user customized before aliases
  existed keeps working.
* No alias reaches text a person reads.
"""

import unittest
import uuid

from app.services.agents.base import TranscriptBuffer
from app.services.agents.consolidated_analyst import _normalize_speaker_id
from app.services.agents.objection_handler import (
    _normalize_speaker_id as _objection_normalize,
)
from app.services.agents.speaker_context import (
    build_speaker_aliases,
    format_speaker_context,
    format_speakers_list,
    format_transcript_segment,
    resolve_speaker_reference,
)
from app.services.speaker_name_rewriter import replace_speaker_labels

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"
C = "33333333-3333-3333-3333-333333333333"


def _roster():
    return [
        {"id": A, "name": "Account Manager", "role": "AE", "speaker_type": "team"},
        {"id": B, "name": "Remote Participant 5", "role": "CISO", "speaker_type": "external"},
        {"id": C, "name": "Remote Participant 6", "role": "", "speaker_type": "external"},
    ]


class AliasMapTests(unittest.TestCase):
    def test_aliases_follow_the_roster_order(self):
        self.assertEqual({A: "S1", B: "S2", C: "S3"}, build_speaker_aliases(_roster()))

    def test_the_map_is_identical_when_rebuilt_from_the_same_roster(self):
        # The resume property, and the reason nothing has to be stored: a new
        # orchestrator loads the roster in the same created_at order and
        # derives the same tags, so a buffered line and a legend still agree.
        self.assertEqual(build_speaker_aliases(_roster()), build_speaker_aliases(_roster()))

    def test_appending_a_speaker_mid_call_never_moves_an_existing_alias(self):
        # audio_handler only ever appends to the live roster, which is what
        # makes an alias stable for the whole call.
        before = build_speaker_aliases(_roster()[:2])
        after = build_speaker_aliases(_roster())
        for speaker_id, alias in before.items():
            self.assertEqual(alias, after[speaker_id])

    def test_a_rename_changes_the_legend_and_not_the_alias(self):
        roster = _roster()
        renamed = [dict(s) for s in roster]
        renamed[1]["display_name"] = "Dana Client"
        renamed[1]["display_name_enabled"] = True
        self.assertEqual(build_speaker_aliases(roster), build_speaker_aliases(renamed))
        self.assertIn("Dana Client", format_speakers_list(renamed, build_speaker_aliases(renamed)))

    def test_a_repeated_id_does_not_consume_a_second_tag(self):
        # A stale in-memory roster can hold the same id twice after a merge.
        doubled = _roster() + [_roster()[0]]
        self.assertEqual({A: "S1", B: "S2", C: "S3"}, build_speaker_aliases(doubled))

    def test_a_speaker_with_no_id_is_skipped_rather_than_numbered(self):
        self.assertEqual({A: "S1"}, build_speaker_aliases([{"id": A, "name": "X"}, {"name": "No id"}]))


class TranscriptRenderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_line_with_an_alias_carries_the_tag_alone(self):
        buffer = TranscriptBuffer()
        await buffer.add("We need to follow up.", "Account Manager", speaker_id=A)

        window = await buffer.get_window(aliases=build_speaker_aliases(_roster()))
        self.assertEqual("[S1]: We need to follow up.", window)
        self.assertNotIn(A, window)

    async def test_a_speaker_the_map_does_not_know_falls_back_to_the_name_form(self):
        # A stale id after a merge, or a line captured before the roster caught
        # up. Falling back beats printing a tag nothing in the legend defines.
        buffer = TranscriptBuffer()
        unknown = str(uuid.uuid4())
        await buffer.add("Who said this?", "Someone", speaker_id=unknown)

        window = await buffer.get_window(aliases=build_speaker_aliases(_roster()))
        self.assertIn("Someone", window)
        self.assertIn(f"speaker_id={unknown}", window)

    async def test_without_a_map_the_old_shape_is_unchanged(self):
        # A caller with no roster order to derive from still produces
        # something the model can attribute.
        buffer = TranscriptBuffer()
        await buffer.add("Still works.", "Account Manager", speaker_id=A)
        self.assertIn(f"speaker_id={A}", await buffer.get_window())

    def test_the_legend_binds_each_tag_to_a_name_a_side_and_a_role(self):
        legend = format_speakers_list(_roster(), build_speaker_aliases(_roster()))
        self.assertIn("- S1 = Account Manager [team] (AE)", legend)
        self.assertIn("- S2 = Remote Participant 5 [external] (CISO)", legend)
        # No role, no empty parentheses.
        self.assertIn("- S3 = Remote Participant 6 [external]", legend)
        self.assertNotIn("()", legend)
        # The UUID appears nowhere: nothing reads it back off this line.
        for speaker_id in (A, B, C):
            self.assertNotIn(speaker_id, legend)

    def test_the_legend_keeps_its_old_shape_without_aliases(self):
        legend = format_speaker_context(_roster()[1])
        self.assertIn(f"speaker_id={B}", legend)
        self.assertIn("speaker_type=external", legend)


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.aliases = build_speaker_aliases(_roster())
        self.valid = {A, B, C}

    def test_an_alias_resolves_to_the_canonical_uuid(self):
        self.assertEqual(B, resolve_speaker_reference("S2", self.aliases, self.valid))

    def test_an_alias_resolves_case_insensitively(self):
        self.assertEqual(B, resolve_speaker_reference("s2", self.aliases, self.valid))
        self.assertEqual(B, resolve_speaker_reference("  S2 ", self.aliases, self.valid))

    def test_a_raw_uuid_is_still_accepted(self):
        # Backward compatibility with a prompt the user customized before
        # aliases existed and which still asks for UUIDs.
        self.assertEqual(B, resolve_speaker_reference(B, self.aliases, self.valid))

    def test_an_unknown_alias_returns_none(self):
        # The same failure mode an unknown UUID always had: the insight is
        # saved with no speaker rather than the wrong one.
        self.assertIsNone(resolve_speaker_reference("S9", self.aliases, self.valid))
        self.assertIsNone(resolve_speaker_reference("Speaker 1", self.aliases, self.valid))
        self.assertIsNone(resolve_speaker_reference("", self.aliases, self.valid))
        self.assertIsNone(resolve_speaker_reference(None, self.aliases, self.valid))

    def test_a_uuid_outside_the_roster_returns_none(self):
        self.assertIsNone(resolve_speaker_reference(str(uuid.uuid4()), self.aliases, self.valid))

    def test_a_merged_away_id_resolves_to_the_surviving_speaker(self):
        # A merge re-points rows at the survivor but a stale in-memory roster
        # can still list the retired id. Both ids then share a tag, and the
        # tag resolves to the one the legend named.
        merged = {A: "S1", B: "S1"}
        self.assertEqual(A, resolve_speaker_reference("S1", merged, {A, B}))

    def test_both_agent_parsers_take_an_alias(self):
        self.assertEqual(B, _normalize_speaker_id("S2", self.valid, self.aliases))
        self.assertEqual(B, _objection_normalize("S2", self.valid, self.aliases))
        # And both still take a UUID with no map at all.
        self.assertEqual(B, _normalize_speaker_id(B, self.valid))
        self.assertEqual(B, _objection_normalize(B, self.valid))


class ProseContaminationTests(unittest.TestCase):
    """The correctness risk aliases introduce, and the deterministic backstop.

    Insight text already carries speaker names - a real action item from the
    reference meeting reads "Remote Participant 5 to schedule a recurring
    monthly meeting cadence" - so the model will be tempted to write "S5"
    instead. The prompts forbid it; this is what makes it impossible.
    """

    def test_a_tag_in_insight_text_is_replaced_with_the_name(self):
        scrub = {"S1": "Account Manager", "S2": "Remote Participant 5"}
        self.assertEqual(
            "Remote Participant 5 to schedule a monthly cadence with Account Manager",
            replace_speaker_labels("S2 to schedule a monthly cadence with S1", scrub),
        )

    def test_the_scrub_respects_word_boundaries(self):
        # A tag inside another token is not a participant tag.
        self.assertEqual(
            "The AS1000 appliance",
            replace_speaker_labels("The AS1000 appliance", {"S1": "Account Manager"}),
        )
        self.assertEqual("S10 is not Dana", replace_speaker_labels("S10 is not S1", {"S1": "Dana"}))


class PayloadSizeTests(unittest.TestCase):
    """The saving, characterized so a regression is visible.

    Measured on the reference meeting the alias form was 44.6 percent smaller.
    The floor here is deliberately lower than that: the ratio depends on line
    length, and this asserts the mechanism is working, not the exact figure.
    """

    LINES = [
        (A, "The client told us this is why we are here and we should move fast."),
        (B, "We still need to validate that with the client before committing."),
        (C, "Honestly this quarter's money is already spent on the data centre move."),
    ] * 12

    def test_the_alias_form_is_at_least_forty_percent_smaller(self):
        aliases = build_speaker_aliases(_roster())
        names = {s["id"]: s["name"] for s in _roster()}
        old = "\n".join(
            format_transcript_segment(text, names[sid], speaker_id=sid) for sid, text in self.LINES
        )
        new = "\n".join(
            format_transcript_segment(text, names[sid], speaker_id=sid, alias=aliases[sid])
            for sid, text in self.LINES
        )
        saving = 1 - len(new) / len(old)
        self.assertGreaterEqual(
            saving,
            0.40,
            f"alias form is only {saving:.1%} smaller; the speaker plumbing is back",
        )

    def test_the_legend_grows_by_far_less_than_the_lines_shrink(self):
        roster = _roster()
        old_legend = format_speakers_list(roster)
        new_legend = format_speakers_list(roster, build_speaker_aliases(roster))
        self.assertLess(len(new_legend), len(old_legend))


class OrchestratorScrubTests(unittest.TestCase):
    """The orchestrator builds the scrub map from its own live roster."""

    def test_the_scrub_map_pairs_each_tag_with_the_displayed_name(self):
        from app.services.agents.orchestrator import AgentOrchestrator

        orchestrator = object.__new__(AgentOrchestrator)
        orchestrator.speakers = [
            {"id": A, "name": "Account Manager", "speaker_type": "team"},
            {
                "id": B,
                "name": "Remote Participant 5",
                "display_name": "Dana Client",
                "display_name_enabled": True,
                "speaker_type": "external",
            },
        ]
        self.assertEqual(
            {"S1": "Account Manager", "S2": "Dana Client"},
            orchestrator._alias_prose_scrub(),
        )

    def test_an_empty_roster_produces_no_scrub_and_no_crash(self):
        from app.services.agents.orchestrator import AgentOrchestrator

        orchestrator = object.__new__(AgentOrchestrator)
        orchestrator.speakers = []
        self.assertEqual({}, orchestrator._alias_prose_scrub())
        self.assertEqual({}, orchestrator.speaker_aliases())


if __name__ == "__main__":
    unittest.main()

"""Strategic signals as live insight rows (ALP-308).

The panel shows the few signals that matter right now; everything else the
agent produced has to survive as an ordinary insight rather than being dropped
on the floor.
"""

import unittest

from app.services.agents.signal_insights import (
    LIVE_SIGNAL_PANEL_SIZE,
    SIGNAL_HISTORY_ITEM_TYPE,
    SIGNAL_ITEM_TYPE,
    ordered_signal_items,
    signal_identity,
)
from app.services.briefing_synthesis import BriefArbiterOutput, BriefItem


def _output(**sections) -> BriefArbiterOutput:
    return BriefArbiterOutput(
        **{
            section: [BriefItem(**item) for item in items]
            for section, items in sections.items()
        }
    )


class OrderedSignalItemsTests(unittest.TestCase):
    def test_model_ranking_beats_section_order(self):
        # Section order alone would put the signal first and the action cue
        # last. The model says otherwise, and the model wins.
        output = _output(
            strategic_signals=[{"title": "Routine signal", "priority": 4}],
            risks_blockers=[{"title": "Decisive risk", "priority": 1}],
            unresolved_discovery_questions=[{"title": "Nice to know", "priority": 5}],
            top_opportunities=[{"title": "Live opportunity", "priority": 3}],
            action_plan=[{"title": "Do this now", "priority": 2}],
        )

        self.assertEqual(
            [entry["title"] for entry in ordered_signal_items(output)],
            [
                "Decisive risk",
                "Do this now",
                "Live opportunity",
                "Routine signal",
                "Nice to know",
            ],
        )

    def test_unranked_items_sort_behind_every_ranked_one(self):
        output = _output(
            strategic_signals=[{"title": "Unranked signal"}],
            risks_blockers=[{"title": "Ranked risk", "priority": 9}],
        )

        self.assertEqual(
            [entry["title"] for entry in ordered_signal_items(output)],
            ["Ranked risk", "Unranked signal"],
        )

    def test_unranked_items_fall_back_to_section_order(self):
        output = _output(
            action_plan=[{"title": "An action"}],
            strategic_signals=[{"title": "A signal"}],
            risks_blockers=[{"title": "A risk"}],
        )

        self.assertEqual(
            [entry["title"] for entry in ordered_signal_items(output)],
            ["A signal", "A risk", "An action"],
        )

    def test_the_same_observation_in_two_sections_is_one_entry(self):
        output = _output(
            strategic_signals=[{"title": "Security review is the gate", "priority": 2}],
            risks_blockers=[{"title": "security review is the gate.", "priority": 1}],
        )

        entries = ordered_signal_items(output)
        self.assertEqual(1, len(entries))
        # The higher-ranked copy is the one that survives.
        self.assertEqual("risks_blockers", entries[0]["section"])

    def test_items_without_text_are_skipped(self):
        output = _output(
            strategic_signals=[{"title": "", "summary": ""}, {"title": "Real one"}],
        )

        self.assertEqual(
            [entry["title"] for entry in ordered_signal_items(output)],
            ["Real one"],
        )

    def test_summary_stands_in_for_a_missing_title(self):
        output = _output(strategic_signals=[{"summary": "Only a summary"}])

        self.assertEqual(
            [entry["title"] for entry in ordered_signal_items(output)],
            ["Only a summary"],
        )

    def test_each_entry_carries_its_section_label_for_the_card_badge(self):
        output = _output(
            risks_blockers=[{"title": "A risk"}],
            unresolved_discovery_questions=[{"title": "A question"}],
        )

        self.assertEqual(
            [entry["label"] for entry in ordered_signal_items(output)],
            ["Risk", "Next Question"],
        )


class SignalIdentityTests(unittest.TestCase):
    def test_identity_ignores_case_spacing_and_trailing_punctuation(self):
        # Matches _signal_identity in briefing_synthesis and signalIdentity in
        # the frontend, so one signal stays one row across all three.
        self.assertEqual(
            signal_identity("Budget owner  changed."),
            signal_identity("budget owner changed"),
        )
        self.assertEqual(
            signal_identity("Who chairs the board?"),
            signal_identity("who chairs the board"),
        )

    def test_identity_of_nothing_is_empty(self):
        self.assertEqual("", signal_identity(None))
        self.assertEqual("", signal_identity("   "))


class PanelContractTests(unittest.TestCase):
    def test_panel_size_matches_the_client(self):
        # LIVE_SIGNAL_CARD_LIMIT in SynthesisSignals.tsx must agree: both
        # sides draw the same top three, listed alongside their panel cards.
        self.assertEqual(3, LIVE_SIGNAL_PANEL_SIZE)

    def test_the_two_lifecycle_types_are_distinct(self):
        self.assertNotEqual(SIGNAL_ITEM_TYPE, SIGNAL_HISTORY_ITEM_TYPE)


class RowPayloadTests(unittest.TestCase):
    """Retirement stamps updated_at so the client can rank recent history."""

    @staticmethod
    def _row(**overrides):
        import uuid as uuid_module
        from datetime import datetime, timezone

        from app.models import Question

        defaults = dict(
            id=uuid_module.uuid4(),
            session_id=uuid_module.uuid4(),
            item_type=SIGNAL_HISTORY_ITEM_TYPE,
            lens_label="Risk",
            question="Security review is the gate",
            rationale="",
            source_context="",
            agent_source="strategic_signals",
            created_at=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
            updated_at=None,
        )
        defaults.update(overrides)
        return Question(**defaults)

    def test_payload_carries_the_retirement_stamp(self):
        from datetime import datetime, timezone

        from app.services.agents.signal_insights import _row_payload

        payload = _row_payload(
            self._row(updated_at=datetime(2026, 8, 31, 10, 30, tzinfo=timezone.utc))
        )
        self.assertEqual("2026-08-31T10:30:00+00:00", payload["updated_at"])

    def test_payload_updated_at_is_null_before_any_change(self):
        from app.services.agents.signal_insights import _row_payload

        self.assertIsNone(_row_payload(self._row())["updated_at"])


if __name__ == "__main__":
    unittest.main()

"""Guards on what the synthesizer is allowed to do to an insight (ALP-297).

Three defects found while analysing why this agent costs 43 percent of a
session. None was observed firing, so these pin behaviour rather than
reproducing an incident - but the merge case is silent and destructive, which
is exactly the kind that reaches production unnoticed.
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import insight_refiner
from app.services.agents.synthesizer import _truncate, _truncate_tail

NOW = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


def question(**overrides):
    row = SimpleNamespace(
        id=uuid.uuid4(),
        item_type="observation",
        question="The client is consolidating vendors",
        rationale="",
        source_context="",
        answered=False,
        answer_summary="",
        dismissed=False,
        starred=False,
        needs_followup=False,
        followup_question="",
        enrichment_notes="",
        revision_count=0,
        agent_source="observer",
        offering_match="",
        created_at=NOW,
        updated_at=None,
        # Everything _question_ws_payload serializes on the success path. A
        # real Question row always carries these, so the fixture does too.
        lens_label="",
        enhanced=False,
        vote=0,
        speaker_id=None,
        directive_id=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class _Db:
    """Minimal stand-in: these appliers only ever get() a Question by id."""

    def __init__(self, rows):
        self._rows = {str(r.id): r for r in rows}
        self.flush = AsyncMock()

    async def get(self, _model, item_id):
        return self._rows.get(str(item_id))


class SelfMergeTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_self_merge_is_refused_rather_than_deleting_the_insight(self):
        row = question()
        rid = str(row.id)
        applied = await insight_refiner._apply_merge_operation(
            _Db([row]),
            uuid.uuid4(),
            {"op": "merge", "keep_id": rid, "remove_id": rid, "merged_text": "combined"},
            {rid: row},
            "synthesizer",
            False,
            NOW,
        )
        self.assertEqual([], applied)
        # Without the guard both ids resolve to this row: it is rewritten to
        # merged_text and then dismissed, so the user's insight disappears.
        self.assertFalse(row.dismissed)
        self.assertEqual("The client is consolidating vendors", row.question)

    async def test_a_genuine_merge_still_applies(self):
        keep, remove = question(), question(question="Vendors are being consolidated")
        q_map = {str(keep.id): keep, str(remove.id): remove}
        applied = await insight_refiner._apply_merge_operation(
            _Db([keep, remove]),
            uuid.uuid4(),
            {
                "op": "merge",
                "keep_id": str(keep.id),
                "remove_id": str(remove.id),
                "merged_text": "combined",
            },
            q_map,
            "synthesizer",
            False,
            NOW,
        )
        self.assertTrue(applied)
        self.assertTrue(remove.dismissed)
        self.assertEqual("combined", keep.question)


class SameTypeElevateTests(unittest.IsolatedAsyncioTestCase):
    async def test_elevating_to_the_type_it_already_has_is_a_no_op(self):
        row = question(item_type="observation")
        applied = await insight_refiner._apply_elevate_operation(
            _Db([row]),
            uuid.uuid4(),
            {"op": "elevate", "id": str(row.id), "new_type": "observation"},
            {str(row.id): row},
            "synthesizer",
            False,
            NOW,
        )
        self.assertEqual([], applied)
        # Otherwise this bumps the revision count, lights the "Refined" badge,
        # and writes "Elevated from observation to observation" into the notes
        # the model reads back next cycle.
        self.assertEqual(0, row.revision_count)
        self.assertEqual("", row.enrichment_notes)

    async def test_a_real_type_change_still_applies(self):
        row = question(item_type="observation")
        applied = await insight_refiner._apply_elevate_operation(
            _Db([row]),
            uuid.uuid4(),
            {"op": "elevate", "id": str(row.id), "new_type": "opportunity"},
            {str(row.id): row},
            "synthesizer",
            False,
            NOW,
        )
        self.assertTrue(applied)
        self.assertEqual("opportunity", row.item_type)


class EnrichmentNoteTruncationTests(unittest.TestCase):
    """_append_note writes to the tail, so the prompt must read the tail."""

    def test_the_newest_notes_survive_truncation(self):
        notes = "\n".join(f"note {i}" for i in range(1, 60))
        kept = _truncate_tail(notes, 200)
        self.assertIn("note 59", kept)
        self.assertNotIn("note 1\n", kept)
        self.assertTrue(kept.startswith("..."))

    def test_short_notes_are_untouched(self):
        self.assertEqual("just one note", _truncate_tail("just one note", 200))
        self.assertEqual("", _truncate_tail(None, 200))

    def test_insight_text_still_truncates_from_the_head(self):
        # The opening words identify an insight, so the stub keeps those.
        text = "Consolidating three vendors into one contract by Q3, pending legal"
        self.assertTrue(_truncate(text, 30).startswith("Consolidating"))

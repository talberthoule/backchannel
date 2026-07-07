import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.models import Question
from app.services.insight_refiner import _apply_operations


class FakeSessionContext:
    def __init__(self, questions):
        self.questions = {str(q.id): q for q in questions}
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, item_id):
        return self.questions.get(str(item_id))

    async def commit(self):
        self.commits += 1

    def add(self, item):
        self.questions[str(item.id)] = item

    async def flush(self):
        return None


class EnhancedDismissOperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_enhanced_elevate_preserves_original_item_type(self):
        session_id = uuid4()
        question = _question(session_id, "Validate managed SIEM fit")
        fake_session = FakeSessionContext([question])

        with patch("app.services.insight_refiner.async_session", return_value=fake_session):
            applied = await _apply_operations(
                session_id,
                [{
                    "op": "elevate",
                    "id": str(question.id),
                    "new_type": "observation",
                    "reason": "Corrected speaker context shows this was account-team framing.",
                }],
                [question],
                agent_source="speaker_context_enhancer",
                enhanced=True,
            )

        self.assertEqual(1, len(applied))
        self.assertEqual("opportunity", question.item_type)
        self.assertTrue(question.enhanced)
        self.assertEqual("opportunity", applied[0]["ws_data"]["item_type"])
        self.assertEqual("observation", applied[0]["suggested_type"])
        self.assertTrue(applied[0]["type_preserved"])
        self.assertIn("preserved original type opportunity", question.enrichment_notes)

    async def test_enhanced_dismiss_marks_insight_traceably_dismissed(self):
        session_id = uuid4()
        question = _question(session_id, "Outdated opportunity")
        fake_session = FakeSessionContext([question])

        with patch("app.services.insight_refiner.async_session", return_value=fake_session):
            applied = await _apply_operations(
                session_id,
                [{
                    "op": "dismiss",
                    "id": str(question.id),
                    "reason": "Corrected speaker context shows this was internal framing.",
                }],
                [question],
                agent_source="speaker_context_enhancer",
                enhanced=True,
            )

        self.assertEqual(1, len(applied))
        self.assertTrue(question.dismissed)
        self.assertTrue(question.enhanced)
        self.assertIsNotNone(question.updated_at)
        self.assertEqual(1, question.revision_count)
        self.assertIn("Dismissed by enhancement", question.enrichment_notes)
        self.assertIn("internal framing", question.enrichment_notes)
        self.assertTrue(applied[0]["ws_data"]["dismissed"])
        self.assertTrue(applied[0]["ws_data"]["enhanced"])

    async def test_adjust_updates_supporting_card_fields(self):
        session_id = uuid4()
        question = _question(session_id, "Participant 1 to revise the document")
        question.rationale = "Participant 1 owns the action."
        question.source_context = "Context: Participant 1 stated the commitment."
        fake_session = FakeSessionContext([question])

        with patch("app.services.insight_refiner.async_session", return_value=fake_session):
            applied = await _apply_operations(
                session_id,
                [{
                    "op": "adjust",
                    "id": str(question.id),
                    "new_text": "Michael to revise the document",
                    "new_rationale": "Michael owns the action.",
                    "new_source_context": "Context: Michael stated the commitment.",
                    "reason": "Speaker name was corrected.",
                }],
                [question],
                agent_source="speaker_context_enhancer",
                enhanced=True,
            )

        self.assertEqual(1, len(applied))
        self.assertEqual("Michael to revise the document", question.question)
        self.assertEqual("Michael owns the action.", question.rationale)
        self.assertEqual("Context: Michael stated the commitment.", question.source_context)
        self.assertTrue(question.enhanced)
        self.assertEqual("Michael owns the action.", applied[0]["ws_data"]["rationale"])
        self.assertEqual("Context: Michael stated the commitment.", applied[0]["ws_data"]["source_context"])

    async def test_enhanced_merge_marks_removed_insight_traceably_dismissed(self):
        session_id = uuid4()
        keep = _question(session_id, "Keep this insight")
        remove = _question(session_id, "Duplicate insight")
        fake_session = FakeSessionContext([keep, remove])

        with patch("app.services.insight_refiner.async_session", return_value=fake_session):
            applied = await _apply_operations(
                session_id,
                [{
                    "op": "merge",
                    "keep_id": str(keep.id),
                    "remove_id": str(remove.id),
                    "merged_text": "Merged insight",
                    "reason": "Corrected speaker context makes these duplicates.",
                }],
                [keep, remove],
                agent_source="speaker_context_enhancer",
                enhanced=True,
            )

        self.assertEqual(2, len(applied))
        self.assertTrue(keep.enhanced)
        self.assertTrue(remove.dismissed)
        self.assertTrue(remove.enhanced)
        self.assertIsNotNone(remove.updated_at)
        self.assertEqual(1, remove.revision_count)
        self.assertIn("Dismissed by enhancement merge", remove.enrichment_notes)
        dismissed_payload = applied[1]["ws_data"]
        self.assertTrue(dismissed_payload["dismissed"])
        self.assertTrue(dismissed_payload["enhanced"])


def _question(session_id, text):
    return Question(
        id=uuid4(),
        session_id=session_id,
        item_type="opportunity",
        question=text,
        rationale="",
        source_context="",
        created_at=datetime.now(timezone.utc),
        dismissed=False,
        enhanced=False,
        revision_count=0,
        enrichment_notes="",
    )


if __name__ == "__main__":
    unittest.main()

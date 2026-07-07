import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.models import Question, Speaker
from app.services.speaker_merge import merge_speakers


class SpeakerMergeTests(unittest.IsolatedAsyncioTestCase):
    async def test_merge_reassigns_rows_preserves_profile_and_deletes_source(self):
        session_id = uuid4()
        source_id = uuid4()
        target_id = uuid4()
        source = Speaker(
            id=source_id,
            session_id=session_id,
            name="Speaker 7",
            role="Consultant",
            color="#e74c3c",
            is_user=True,
            display_name="Mark",
            display_name_enabled=True,
        )
        target = Speaker(
            id=target_id,
            session_id=session_id,
            name="Speaker 1",
            role="",
            color="#0d9488",
            is_user=False,
            display_name="",
            display_name_enabled=False,
        )

        db = AsyncMock()
        db.get.side_effect = [source, target]
        db.execute.side_effect = [
            _ScalarResult(3),
            _ScalarResult(2),
            _QuestionResult([]),
        ]

        result = await merge_speakers(db, session_id, source_id, target_id)

        self.assertEqual(result.transcript_entries_updated, 3)
        self.assertEqual(result.questions_updated, 2)
        self.assertTrue(target.is_user)
        self.assertEqual(target.role, "Consultant")
        self.assertEqual(target.display_name, "Mark")
        self.assertTrue(target.display_name_enabled)
        db.delete.assert_awaited_once_with(source)
        db.commit.assert_awaited_once()

    async def test_merge_rewrites_source_speaker_labels_in_insights(self):
        session_id = uuid4()
        source_id = uuid4()
        target_id = uuid4()
        source = Speaker(
            id=source_id,
            session_id=session_id,
            name="Participant 1",
            role="",
            color="#e74c3c",
            is_user=False,
            display_name="",
            display_name_enabled=False,
        )
        target = Speaker(
            id=target_id,
            session_id=session_id,
            name="Participant 2",
            role="",
            color="#0d9488",
            is_user=False,
            display_name="Michael",
            display_name_enabled=True,
        )
        question = Question(
            id=uuid4(),
            session_id=session_id,
            question="Participant 1 to revise the file.",
            rationale="Participant 1 owns the next step.",
            source_context="Context: Participant 1 stated the commitment.",
            enrichment_notes="",
            revision_count=0,
            enhanced=False,
        )

        db = AsyncMock()
        db.get.side_effect = [source, target]
        db.execute.side_effect = [
            _ScalarResult(0),
            _ScalarResult(1),
            _QuestionResult([question]),
        ]

        result = await merge_speakers(db, session_id, source_id, target_id)

        self.assertEqual(result.questions_updated, 1)
        self.assertEqual("Michael to revise the file.", question.question)
        self.assertEqual("Michael owns the next step.", question.rationale)
        self.assertEqual("Context: Michael stated the commitment.", question.source_context)
        self.assertTrue(question.enhanced)
        self.assertEqual(1, question.revision_count)


class _ScalarResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _QuestionResult:
    def __init__(self, questions):
        self._questions = questions

    def scalars(self):
        return self

    def all(self):
        return self._questions


if __name__ == "__main__":
    unittest.main()

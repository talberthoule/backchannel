import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.ask import ASK_AGENT_SOURCE, ASK_ITEM_TYPE, AskIn, ask, build_asked_row


class AskInTests(unittest.TestCase):
    def test_rejects_an_empty_question(self):
        with self.assertRaises(ValidationError):
            AskIn(model_id="gemini-flash", question="")

    def test_rejects_an_overlong_question(self):
        with self.assertRaises(ValidationError):
            AskIn(model_id="gemini-flash", question="x" * 2001)

    def test_accepts_a_normal_question(self):
        body = AskIn(model_id="gemini-flash", question="what budget did they mention?")
        self.assertEqual(body.question, "what budget did they mention?")


class AskedRowTests(unittest.TestCase):
    def setUp(self):
        self.row = build_asked_row(
            session_id="33333333-3333-3333-3333-333333333333",
            question="what budget did they mention?",
            answer="They said 180K.",
            model_name="Flash 3.1",
            elapsed_seconds=1.94,
        )

    def test_caption_names_the_model_and_the_latency(self):
        self.assertEqual(self.row.rationale, "Answered by Flash 3.1 in 1.9s")

    def test_uses_the_asked_item_type(self):
        self.assertEqual(self.row.item_type, ASK_ITEM_TYPE)
        self.assertEqual(ASK_ITEM_TYPE, "asked")

    def test_is_starred_on_creation(self):
        self.assertTrue(self.row.starred)

    def test_records_the_live_chat_source(self):
        self.assertEqual(self.row.agent_source, ASK_AGENT_SOURCE)
        self.assertEqual(ASK_AGENT_SOURCE, "live_chat")

    def test_stores_the_question_and_the_answer(self):
        self.assertEqual(self.row.question, "what budget did they mention?")
        self.assertEqual(self.row.answer_summary, "They said 180K.")
        self.assertTrue(self.row.answered)


def _db_mock():
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(
        name="Session",
        meeting_type="discovery",
        meeting_context="",
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    return db


class AskEmptyAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_model_reply_is_rejected_instead_of_saved(self):
        body = AskIn(model_id="gemini-3.5-flash", question="what budget did they mention?")
        with patch("app.routers.ask.is_local_only", new=AsyncMock(return_value=False)), \
                patch("app.routers.ask.generate_text", new=AsyncMock(return_value="")):
            with self.assertRaises(HTTPException) as ctx:
                await ask(uuid4(), body, db=_db_mock())
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("empty answer", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.ask import (
    ANSWER_TRUNCATION_MARKER,
    ASK_AGENT_SOURCE,
    ASK_ITEM_TYPE,
    MAX_ANSWER_CHARS,
    AskIn,
    ask,
    build_asked_row,
    clamp_answer,
    load_live_context,
)
from app.services.privacy import LocalOnlyModeError


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


class ClampAnswerTests(unittest.TestCase):
    """ALP-178: a runaway reply must not fill the live feed with one card."""

    def test_a_short_answer_is_unchanged(self):
        self.assertEqual("They said 180K.", clamp_answer("They said 180K."))

    def test_an_answer_exactly_at_the_limit_is_unchanged(self):
        answer = "x" * MAX_ANSWER_CHARS
        self.assertEqual(answer, clamp_answer(answer))

    def test_an_overlong_answer_is_truncated_with_a_marker(self):
        answer = "x" * (MAX_ANSWER_CHARS + 500)
        clamped = clamp_answer(answer)
        self.assertEqual(MAX_ANSWER_CHARS + len(ANSWER_TRUNCATION_MARKER), len(clamped))
        self.assertTrue(clamped.startswith("x" * MAX_ANSWER_CHARS))
        self.assertTrue(clamped.endswith(ANSWER_TRUNCATION_MARKER))


class AskOverlongAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_runaway_reply_is_stored_clamped(self):
        overlong = "y" * (MAX_ANSWER_CHARS + 200)
        body = AskIn(model_id="gemini-3.5-flash", question="what budget did they mention?")
        with patch("app.routers.ask.is_local_only", new=AsyncMock(return_value=False)), \
                patch("app.routers.ask.generate_text", new=AsyncMock(return_value=overlong)):
            row = await ask(uuid4(), body, db=_db_mock())
        self.assertEqual(MAX_ANSWER_CHARS + len(ANSWER_TRUNCATION_MARKER), len(row.answer_summary))
        self.assertTrue(row.answer_summary.endswith(ANSWER_TRUNCATION_MARKER))


class LiveContextSignalsTests(unittest.IsolatedAsyncioTestCase):
    """ALP-178: the strategic-signals rendering path in load_live_context.

    Previously a dict-repr bug rendered signal rows with a bare str(item),
    which ate the prompt budget on Python dict reprs (fixed in ebe7857).
    Covers the dict path, dicts missing a field, and a non-dict entry.
    """

    async def _signals_for(self, signal_rows):
        db = _db_mock()
        db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(
            strategic_signals=signal_rows
        )
        context = await load_live_context(uuid4(), db)
        return context["signals"]

    async def test_dict_with_title_and_summary(self):
        signals = await self._signals_for([{"title": "Budget", "summary": "180K mentioned"}])
        self.assertEqual("- Budget: 180K mentioned", signals)

    async def test_dict_missing_summary_renders_title_only(self):
        signals = await self._signals_for([{"title": "Budget"}])
        self.assertEqual("- Budget", signals)

    async def test_dict_missing_title_renders_summary_only(self):
        signals = await self._signals_for([{"summary": "180K mentioned"}])
        self.assertEqual("- 180K mentioned", signals)

    async def test_dict_with_no_usable_text_is_dropped(self):
        signals = await self._signals_for([{"title": "", "summary": "   "}])
        self.assertEqual("", signals)

    async def test_non_dict_entry_falls_back_to_str(self):
        signals = await self._signals_for(["Budget risk flagged"])
        self.assertEqual("- Budget risk flagged", signals)


class AskPrivacyFirstTests(unittest.IsolatedAsyncioTestCase):
    """Spec Testing section: Privacy First rejects a cloud model and admits
    a local endpoint model."""

    async def test_privacy_first_rejects_a_cloud_model(self):
        body = AskIn(model_id="gemini-3.5-flash", question="what budget did they mention?")
        with patch("app.routers.ask.is_local_only", new=AsyncMock(return_value=True)), \
                patch("app.routers.ask.allows_local_only", new=AsyncMock(return_value=False)):
            with self.assertRaises(LocalOnlyModeError):
                await ask(uuid4(), body, db=_db_mock())

    async def test_privacy_first_admits_a_local_endpoint_model(self):
        body = AskIn(
            model_id="endpoint:lm-studio:antares-1b",
            question="what budget did they mention?",
        )
        with patch(
            "app.routers.ask.endpoint_model_entry",
            new=AsyncMock(return_value={"supports_text": True, "name": "antares-1b"}),
        ), patch("app.routers.ask.is_local_only", new=AsyncMock(return_value=True)), \
                patch("app.routers.ask.allows_local_only", new=AsyncMock(return_value=True)), \
                patch("app.routers.ask.generate_text", new=AsyncMock(return_value="They said 180K.")):
            row = await ask(uuid4(), body, db=_db_mock())
        self.assertEqual(row.item_type, ASK_ITEM_TYPE)
        self.assertEqual(row.answer_summary, "They said 180K.")


if __name__ == "__main__":
    unittest.main()

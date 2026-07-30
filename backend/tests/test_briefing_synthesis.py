import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import llm
from app.services import briefing_synthesis
from app.services.briefing_synthesis import (
    BRIEF_ARBITER_SLUG,
    BriefArbiterOutput,
    BriefLensOutput,
    _build_context,
    _format_insights,
    _format_signal_history,
    _question_dict,
    agent_config_enabled,
    _response_contract,
)
from app.services.llm import parse_json_response


class FakeGoogleClient:
    """Async genai.Client stand-in that fails the schema call once."""

    def __init__(self):
        self.calls = []
        self.models = self
        self.aio = SimpleNamespace(models=self)

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise ValueError("schema rejected")
        return SimpleNamespace(
            parsed=None,
            text='{"top_outcomes":[{"title":"Outcome","summary":"Client confirmed priority."}]}',
            usage_metadata=None,
        )


class BriefingSynthesisTests(unittest.TestCase):
    def test_parse_json_response_handles_fenced_json(self):
        parsed = parse_json_response(
            """```json
{"top_outcomes":[{"title":"Outcome","summary":"Client confirmed priority."}],"arbiter_notes":"Both lenses agree."}
```""",
            BriefArbiterOutput,
        )

        self.assertEqual("Outcome", parsed.top_outcomes[0].title)
        self.assertEqual("Both lenses agree.", parsed.arbiter_notes)

    def test_agent_config_enabled_requires_present_enabled_agent(self):
        self.assertFalse(agent_config_enabled({}, BRIEF_ARBITER_SLUG))
        self.assertFalse(agent_config_enabled({BRIEF_ARBITER_SLUG: MagicMock(enabled=False)}, BRIEF_ARBITER_SLUG))
        self.assertTrue(agent_config_enabled({BRIEF_ARBITER_SLUG: MagicMock(enabled=True)}, BRIEF_ARBITER_SLUG))

    def test_asked_insight_includes_query_response_and_full_state(self):
        insight_id = uuid.uuid4()
        item = SimpleNamespace(
            id=insight_id,
            item_type="asked",
            question="What did they say about timing?",
            rationale="Operator asked during the call",
            source_context="Recent transcript",
            answered=True,
            answer_summary="They need a decision by Friday.",
            needs_followup=True,
            followup_question="Who owns the decision?",
            offering_match="Delivery acceleration",
            vote=2,
            agent_source="live_chat",
        )

        rendered = json.loads(_format_insights([_question_dict(item)]))

        self.assertFalse(rendered["truncated"])
        self.assertEqual(
            {
                "id",
                "item_type",
                "question",
                "rationale",
                "source_context",
                "answered",
                "answer_summary",
                "needs_followup",
                "followup_question",
                "offering_match",
                "vote",
                "agent_source",
            },
            set(rendered["items"][0]),
        )
        asked = rendered["items"][0]
        self.assertEqual(str(insight_id), asked["id"])
        self.assertEqual("What did they say about timing?", asked["question"])
        self.assertEqual("They need a decision by Friday.", asked["answer_summary"])
        self.assertEqual("Who owns the decision?", asked["followup_question"])
        self.assertEqual(2, asked["vote"])

    def test_insight_and_history_budgets_keep_newest_and_mark_truncation(self):
        insights = [
            {
                "id": str(index),
                "item_type": "observation",
                "question": f"Insight {index}",
                "rationale": "x" * 160,
            }
            for index in range(3)
        ]
        insight_budget = len(_format_insights(insights[-2:], budget=10000))

        rendered_insights = _format_insights(insights, budget=insight_budget)
        insight_payload = json.loads(rendered_insights)

        self.assertLessEqual(len(rendered_insights), insight_budget)
        self.assertTrue(insight_payload["truncated"])
        self.assertEqual(["1", "2"], [item["id"] for item in insight_payload["items"]])
        self.assertNotIn('": ', rendered_insights)

        history = [
            {
                "section": "strategic_signals",
                "title": f"Signal {index}",
                "summary": "y" * 160,
                "last_seen": f"2026-07-30T10:0{index}:00+00:00",
                "count": index + 1,
            }
            for index in range(3)
        ]
        history_budget = len(_format_signal_history(history[-2:], budget=10000))

        rendered_history = _format_signal_history(history, budget=history_budget)
        history_payload = json.loads(rendered_history)

        self.assertLessEqual(len(rendered_history), history_budget)
        self.assertTrue(history_payload["truncated"])
        self.assertEqual(
            ["Signal 1", "Signal 2"],
            [item["title"] for item in history_payload["items"]],
        )
        self.assertNotIn('": ', rendered_history)

    def test_single_oversized_item_is_clipped_instead_of_blank(self):
        rendered_insight = _format_insights(
            [
                {
                    "id": "newest-insight",
                    "item_type": "observation",
                    "question": "Newest insight",
                    "source_context": "x" * 5000,
                }
            ],
            budget=500,
        )
        insight_payload = json.loads(rendered_insight)

        self.assertLessEqual(len(rendered_insight), 500)
        self.assertTrue(insight_payload["truncated"])
        self.assertEqual(1, len(insight_payload["items"]))
        self.assertEqual("newest-insight", insight_payload["items"][0]["id"])
        self.assertEqual("Newest insight", insight_payload["items"][0]["question"])
        self.assertTrue(insight_payload["items"][0]["source_context"].endswith("..."))

        rendered_history = _format_signal_history(
            [
                {
                    "section": "strategic_signals",
                    "title": "Newest signal",
                    "summary": "y" * 5000,
                    "last_seen": "2026-07-30T10:00:00+00:00",
                    "count": 1,
                }
            ],
            budget=400,
        )
        history_payload = json.loads(rendered_history)

        self.assertLessEqual(len(rendered_history), 400)
        self.assertTrue(history_payload["truncated"])
        self.assertEqual(1, len(history_payload["items"]))
        self.assertEqual("Newest signal", history_payload["items"][0]["title"])
        self.assertTrue(history_payload["items"][0]["summary"].endswith("..."))


class _ContextResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ContextSession:
    def __init__(self, history):
        self.history = history

    async def get(self, model, session_id):
        del model, session_id
        return SimpleNamespace(
            meeting_type="general",
            meeting_context="Operator context",
            notes="",
        )

    async def execute(self, statement):
        del statement
        return _ContextResult(self.history)


class _ContextManager:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback


class BriefingSynthesisAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for target, value in (
            ("is_local_only", AsyncMock(return_value=False)),
            ("_resolve_key", AsyncMock(return_value="k")),
        ):
            patcher = patch.object(llm, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_generate_json_google_retries_with_json_contract(self):
        client = FakeGoogleClient()
        with (
            patch.object(llm.genai, "Client", return_value=client),
            patch.object(llm, "record_token_usage", new=AsyncMock()),
        ):
            parsed = await llm.generate_json(
                "gemini-3.5-flash",
                "Base prompt",
                BriefLensOutput,
                schema_hint=_response_contract(BriefLensOutput),
            )

        self.assertEqual("Outcome", parsed.top_outcomes[0].title)
        self.assertEqual(2, len(client.calls))
        retry_prompt = client.calls[1]["contents"]
        self.assertIn("Required JSON Contract", retry_prompt)
        self.assertIn("top_outcomes", retry_prompt)

    async def test_generate_json_records_usage_for_its_source(self):
        usage = SimpleNamespace(prompt_token_count=4, candidates_token_count=1, total_token_count=5)
        response = SimpleNamespace(parsed=BriefLensOutput(), text="", usage_metadata=usage)
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content=AsyncMock(return_value=response),
        )))
        session_id = uuid.uuid4()
        with (
            patch.object(llm.genai, "Client", return_value=client),
            patch.object(llm, "record_token_usage", new=AsyncMock()) as record,
        ):
            await llm.generate_json(
                "gemini-3.5-flash",
                "Base prompt",
                BriefLensOutput,
                session_id=session_id,
                source="brief_meeting_lens",
            )
        record.assert_awaited_once_with(session_id, "brief_meeting_lens", "gemini-3.5-flash", usage)

    async def test_post_call_context_includes_live_signal_history(self):
        history = [
            {
                "section": "strategic_signals",
                "title": "Recurring signal",
                "summary": "Repeated three times",
                "last_seen": "2026-07-30T10:00:00+00:00",
                "count": 3,
            }
        ]
        db = _ContextSession(history)

        with patch.object(
            briefing_synthesis,
            "async_session",
            return_value=_ContextManager(db),
        ):
            context = await _build_context(
                uuid.uuid4(),
                mode="post_call",
                transcript_window="transcript",
                directives=[],
                doc_summaries="documents",
                speakers=[],
                active_questions=[],
            )

        self.assertIn("Live strategic signal history", context.insights_text)
        self.assertIn(
            "count means observed card occurrences, not completed cycles",
            context.insights_text,
        )
        self.assertIn("Recurring signal", context.insights_text)

    async def test_live_context_keeps_bounded_rich_insight_json(self):
        db = _ContextSession([])

        with patch.object(
            briefing_synthesis,
            "async_session",
            return_value=_ContextManager(db),
        ):
            context = await _build_context(
                uuid.uuid4(),
                mode="live",
                transcript_window="transcript",
                directives=[],
                doc_summaries="documents",
                speakers=[],
                active_questions=[
                    {
                        "id": "live-insight",
                        "item_type": "question",
                        "question": "What is the deadline?",
                        "source_context": "Client timing discussion",
                        "answered": False,
                        "needs_followup": True,
                    }
                ],
            )

        payload = json.loads(context.insights_text)
        self.assertFalse(payload["truncated"])
        self.assertEqual("live-insight", payload["items"][0]["id"])
        self.assertEqual(
            "Client timing discussion",
            payload["items"][0]["source_context"],
        )
        self.assertNotIn("Live strategic signal history", context.insights_text)


if __name__ == "__main__":
    unittest.main()

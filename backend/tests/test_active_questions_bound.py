"""The active_questions accumulator and the idle-window skips (ALP-287).

The list of open questions is carried into the consolidated analyst and
strategic signals prompts on every cycle. It was only ever pruned when the
synthesizer answered a question, so on a measured 57-minute meeting it reached
45 entries and never shrank -- unbounded in call length, and billed to two
agents on every cycle.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.agents.orchestrator import _MAX_ACTIVE_QUESTIONS, AgentOrchestrator
from app.services.briefing_synthesis import _format_insights


def make_orchestrator():
    with patch("app.services.agents.orchestrator.GeminiLiveSession", return_value=AsyncMock()):
        return AgentOrchestrator(
            session_id=uuid4(),
            websocket=AsyncMock(),
            directives=[],
            doc_summaries="",
            active_questions=[],
            speakers=[],
            agent_configs={},
        )


class ActiveQuestionBoundTests(unittest.TestCase):
    def setUp(self):
        self.orchestrator = make_orchestrator()

    def test_list_never_grows_past_the_cap(self):
        for index in range(_MAX_ACTIVE_QUESTIONS * 3):
            self.orchestrator._remember_active_question(f"id-{index}", f"question {index}")
        self.assertEqual(_MAX_ACTIVE_QUESTIONS, len(self.orchestrator.active_questions))

    def test_the_oldest_questions_are_the_ones_dropped(self):
        for index in range(_MAX_ACTIVE_QUESTIONS + 3):
            self.orchestrator._remember_active_question(f"id-{index}", f"question {index}")
        ids = [aq["id"] for aq in self.orchestrator.active_questions]
        self.assertNotIn("id-0", ids)
        self.assertIn(f"id-{_MAX_ACTIVE_QUESTIONS + 2}", ids)

    def test_entries_carry_their_item_type(self):
        self.orchestrator._remember_active_question("id-1", "Who signs off?")
        self.assertEqual("question", self.orchestrator.active_questions[0]["item_type"])

    def test_forgetting_removes_exactly_one_question(self):
        self.orchestrator._remember_active_question("id-1", "first")
        self.orchestrator._remember_active_question("id-2", "second")
        self.orchestrator._forget_active_question("id-1")
        self.assertEqual(["id-2"], [aq["id"] for aq in self.orchestrator.active_questions])

    def test_forgetting_an_unknown_or_missing_id_is_harmless(self):
        self.orchestrator._remember_active_question("id-1", "first")
        self.orchestrator._forget_active_question("nope")
        self.orchestrator._forget_active_question(None)
        self.assertEqual(1, len(self.orchestrator.active_questions))


class InsightFormattingTests(unittest.TestCase):
    """v0.5.0 replaced the line renderer these covered with a budget-bounded
    JSON payload, so the original empty-"()" assertion no longer has anything to
    describe. The two assertions that still mean something - identity survives,
    and a non-question is not relabelled as a question - are kept against the
    new shape."""

    @staticmethod
    def _items(rendered: str) -> list[dict]:
        return json.loads(rendered)["items"]

    def test_identity_and_type_survive_the_render(self):
        [item] = self._items(
            _format_insights([{"id": "abc", "question": "Who signs off?", "item_type": "question"}])
        )
        self.assertEqual("abc", item["id"])
        self.assertEqual("question", item["item_type"])

    def test_rationale_is_still_carried_when_present(self):
        [item] = self._items(
            _format_insights([
                {"id": "abc", "question": "Who signs off?", "item_type": "question", "rationale": "budget owner unclear"}
            ])
        )
        self.assertEqual("budget owner unclear", item["rationale"])

    def test_a_non_question_entry_is_not_mislabelled(self):
        [item] = self._items(
            _format_insights([{"id": "abc", "text": "They are consolidating vendors", "item_type": "observation"}])
        )
        self.assertEqual("observation", item["item_type"])


class IdleWindowSkipTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyst_skips_a_cycle_when_nobody_spoke(self):
        orchestrator = make_orchestrator()
        orchestrator._get_interval = MagicMock(return_value=0.01)
        orchestrator.consolidated_agent = MagicMock(run_cycle=AsyncMock(return_value=[]))
        orchestrator.transcript_buffer.get_window = AsyncMock(return_value="[S1]: same words")

        import asyncio

        task = asyncio.create_task(orchestrator._consolidated_agent_loop())
        await asyncio.sleep(0.08)
        orchestrator._stopped = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Many ticks elapsed over an unchanging window; only the first runs.
        self.assertEqual(1, orchestrator.consolidated_agent.run_cycle.await_count)


class BoardStubTests(unittest.TestCase):
    """Non-question insights feed the analyst's already-on-the-board context.

    The emission-time dedup only reaches back five minutes and active_questions
    only carries item_type question, so nothing stopped the analyst from
    re-proposing a minute-12 observation at minute 40 in fresh words.
    """

    def setUp(self):
        self.orchestrator = make_orchestrator()

    def test_non_question_insights_are_stubbed_and_capped(self):
        from app.services.agents.orchestrator import _MAX_BOARD_STUBS

        for index in range(_MAX_BOARD_STUBS * 2):
            self.orchestrator._remember_board_stub("observation", f"observation {index}")
        self.assertEqual(_MAX_BOARD_STUBS, len(self.orchestrator._board_stubs))
        # The newest survive; the oldest are the ones dropped.
        self.assertEqual(
            f"observation {_MAX_BOARD_STUBS * 2 - 1}",
            self.orchestrator._board_stubs[-1]["text"],
        )

    def test_long_text_is_cut_to_the_stub_budget(self):
        from app.services.agents.orchestrator import _BOARD_STUB_CHARS

        self.orchestrator._remember_board_stub("opportunity", "x" * 500)
        stub = self.orchestrator._board_stubs[0]["text"]
        self.assertLessEqual(len(stub), _BOARD_STUB_CHARS + 3)
        self.assertTrue(stub.endswith("..."))

    def test_empty_text_is_ignored(self):
        self.orchestrator._remember_board_stub("observation", "   ")
        self.assertEqual([], self.orchestrator._board_stubs)

    def test_seeded_stubs_pass_through_the_same_budget_and_cap(self):
        from app.services.agents.orchestrator import _MAX_BOARD_STUBS

        seeds = [
            {"item_type": "observation", "text": f"seed {index}"}
            for index in range(_MAX_BOARD_STUBS + 10)
        ]
        with patch("app.services.agents.orchestrator.GeminiLiveSession", return_value=AsyncMock()):
            orchestrator = AgentOrchestrator(
                session_id=uuid4(),
                websocket=AsyncMock(),
                directives=[],
                doc_summaries="",
                active_questions=[],
                speakers=[],
                agent_configs={},
                board_stubs=seeds,
            )
        self.assertEqual(_MAX_BOARD_STUBS, len(orchestrator._board_stubs))


class AnalystBoardContextTests(unittest.IsolatedAsyncioTestCase):
    """The stub list reaches the analyst prompt through {active_questions}, so
    installs whose stored prompt predates the heading change still get it."""

    async def _prompt_for(self, **cycle_kwargs) -> str:
        from app.services.agents.consolidated_analyst import (
            ConsolidatedAnalystAgent,
            ConsolidatedAnalystOutput,
        )

        captured = {}

        async def fake_generate_json(model, prompt, schema, **kwargs):
            captured["prompt"] = prompt
            return ConsolidatedAnalystOutput(items=[])

        agent = ConsolidatedAnalystAgent()
        with patch(
            "app.services.agents.consolidated_analyst.generate_json",
            fake_generate_json,
        ):
            await agent.run_cycle(
                transcript_window="[S1]: words",
                directives=[],
                doc_summaries="",
                speakers=[],
                **cycle_kwargs,
            )
        return captured["prompt"]

    async def test_board_notes_render_into_the_prompt(self):
        prompt = await self._prompt_for(
            active_questions=[{"question": "Who owns DR?"}],
            board_notes=[{"item_type": "observation", "text": "Budget froze in Q3"}],
        )
        self.assertIn('- "Who owns DR?"', prompt)
        self.assertIn("- [observation] Budget froze in Q3", prompt)
        self.assertIn("do not restate", prompt)

    async def test_without_notes_the_board_section_is_absent(self):
        prompt = await self._prompt_for(active_questions=[], board_notes=[])
        self.assertIn("(No questions suggested yet)", prompt)
        self.assertNotIn("Other insights already captured", prompt)


if __name__ == "__main__":
    unittest.main()

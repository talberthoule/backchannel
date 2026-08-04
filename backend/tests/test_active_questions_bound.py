"""The active_questions accumulator and the idle-window skips (ALP-287).

The list of open questions is carried into the consolidated analyst and
strategic signals prompts on every cycle. It was only ever pruned when the
synthesizer answered a question, so on a measured 57-minute meeting it reached
45 entries and never shrank -- unbounded in call length, and billed to two
agents on every cycle.
"""

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
    def test_live_entries_render_without_an_empty_rationale(self):
        # The live path supplies no rationale; every entry used to end in "()".
        line = _format_insights([{"id": "abc", "question": "Who signs off?", "item_type": "question"}])
        self.assertNotIn("()", line)
        self.assertIn("insight_id=abc", line)
        self.assertIn("type=question", line)

    def test_rationale_is_still_rendered_when_present(self):
        line = _format_insights([
            {"id": "abc", "question": "Who signs off?", "item_type": "question", "rationale": "budget owner unclear"}
        ])
        self.assertIn("(budget owner unclear)", line)

    def test_a_non_question_entry_is_not_mislabelled(self):
        line = _format_insights([{"id": "abc", "text": "They are consolidating vendors", "item_type": "observation"}])
        self.assertIn("type=observation", line)


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


if __name__ == "__main__":
    unittest.main()

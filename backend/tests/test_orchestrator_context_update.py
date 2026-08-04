import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.agents.orchestrator import (
    AgentOrchestrator,
    _live_orchestrators,
    get_live_orchestrator,
)


def make_orchestrator(meeting_type="general", meeting_context="initial context"):
    with patch("app.services.agents.orchestrator.GeminiLiveSession", return_value=AsyncMock()):
        return AgentOrchestrator(
            session_id=uuid4(),
            websocket=AsyncMock(),
            directives=[],
            doc_summaries="",
            active_questions=[],
            speakers=[],
            agent_configs={
                "opportunity_specialist": MagicMock(
                    enabled=True, model_id="opp-model", prompt="", interval_seconds=5
                ),
            },
            meeting_type=meeting_type,
            meeting_context=meeting_context,
        )


class UpdateMeetingContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_health_check_does_not_reconnect_inline(self):
        orchestrator = object.__new__(AgentOrchestrator)
        orchestrator._is_enabled = MagicMock(return_value=True)

        async def fail_gateway():
            raise RuntimeError("gateway ended")

        task = asyncio.create_task(fail_gateway())
        with self.assertRaises(RuntimeError):
            await task
        orchestrator._gateway_task = task
        orchestrator._reconnect_gateway = AsyncMock()

        healthy = await orchestrator.check_health()

        self.assertFalse(healthy)
        orchestrator._reconnect_gateway.assert_not_awaited()

    async def test_gateway_health_recovers_after_initial_connect_failure(self):
        orchestrator = object.__new__(AgentOrchestrator)
        orchestrator._is_enabled = MagicMock(return_value=True)
        orchestrator._gateway_task = None

        self.assertFalse(await orchestrator.check_health())

        release = asyncio.Event()

        async def receive_gateway_responses():
            await release.wait()

        orchestrator.audio_gateway = MagicMock(
            close=AsyncMock(),
            connect=AsyncMock(),
        )
        orchestrator._handle_gateway_responses = receive_gateway_responses

        self.assertTrue(await orchestrator._reconnect_gateway())
        self.assertTrue(await orchestrator.check_health())

        release.set()
        await orchestrator._gateway_task

    async def test_update_pushes_new_context_to_running_agents(self):
        orchestrator = make_orchestrator()
        orchestrator.objection_agent._last_window = "Speaker 1: old text"

        orchestrator.update_meeting_context(meeting_context="we pivoted to renewals")

        self.assertIn("we pivoted to renewals", orchestrator.meeting_context_text)
        self.assertEqual(
            orchestrator.consolidated_agent.meeting_context_text,
            orchestrator.meeting_context_text,
        )
        self.assertEqual(
            orchestrator.objection_agent.meeting_context_text,
            orchestrator.meeting_context_text,
        )
        # Unchanged-window skip is cleared so the next scan uses the new context.
        self.assertEqual(orchestrator.objection_agent._last_window, "")
        # Type not passed -> unchanged.
        self.assertEqual(orchestrator.meeting_type, "general")

    async def test_type_change_updates_type_and_wires_offering_matching(self):
        orchestrator = make_orchestrator(meeting_type="general")
        self.assertFalse(orchestrator._offering_matching_enabled)
        self.assertIsNone(orchestrator._opp_specialist_subscriber)

        orchestrator.update_meeting_context(meeting_type="client_sales")
        await asyncio.sleep(0)

        self.assertEqual(orchestrator.meeting_type, "client_sales")
        self.assertTrue(orchestrator._offering_matching_enabled)
        self.assertIsNotNone(orchestrator._opp_specialist_subscriber)
        self.assertIn("Client or prospect", orchestrator.meeting_context_text)
        activity = {
            record["slug"]: record
            for record in orchestrator.activity.snapshot()["agents"]
        }
        self.assertEqual("waiting", activity["opportunity_specialist"]["state"])
        # Context not passed -> original context retained.
        self.assertIn("initial context", orchestrator.meeting_context_text)

    async def test_opportunity_lens_is_suppressed_when_offering_matching_is_off(self):
        orchestrator = make_orchestrator(meeting_type="internal_checkin")

        self.assertFalse(orchestrator._offering_matching_enabled)
        self.assertEqual({"opportunity"}, orchestrator._suppressed_analyst_types())
        agent = orchestrator.consolidated_agent
        self.assertNotIn("opportunity", agent.enabled_types)
        # Suppression removes the lens from the prompt, not just from the output.
        # (Match the tag line, not the word: other lenses mention "opportunity"
        # in their prose.)
        self.assertNotIn('"item_type": "opportunity"', agent._lens_sections)
        self.assertIn('"item_type": "question"', agent._lens_sections)
        self.assertNotIn("opportunity", agent._item_type_values)

    async def test_opportunity_lens_runs_when_offering_matching_is_on(self):
        orchestrator = make_orchestrator(meeting_type="client_sales")

        self.assertTrue(orchestrator._offering_matching_enabled)
        self.assertEqual(set(), orchestrator._suppressed_analyst_types())
        self.assertIn("opportunity", orchestrator.consolidated_agent.enabled_types)

    async def test_type_change_recomposes_the_analyst_lenses_mid_call(self):
        orchestrator = make_orchestrator(meeting_type="internal_checkin")
        self.assertNotIn("opportunity", orchestrator.consolidated_agent.enabled_types)

        orchestrator.update_meeting_context(meeting_type="client_sales")

        agent = orchestrator.consolidated_agent
        self.assertIn("opportunity", agent.enabled_types)
        self.assertIn("opportunity", agent._item_type_values)

        orchestrator.update_meeting_context(meeting_type="internal_checkin")

        self.assertNotIn("opportunity", agent.enabled_types)

    async def test_invalid_type_normalizes_to_general(self):
        orchestrator = make_orchestrator(meeting_type="client_sales")

        orchestrator.update_meeting_context(meeting_type="nonsense")

        self.assertEqual(orchestrator.meeting_type, "general")

    async def test_close_all_unregisters_live_orchestrator(self):
        orchestrator = make_orchestrator()
        _live_orchestrators[orchestrator.session_id] = orchestrator
        self.assertIs(get_live_orchestrator(orchestrator.session_id), orchestrator)

        await orchestrator.close_all()

        self.assertIsNone(get_live_orchestrator(orchestrator.session_id))


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.agents.orchestrator import AgentOrchestrator


class FakeSessionContext:
    def __init__(self):
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def refresh(self, item):
        if item.created_at is None:
            from datetime import datetime, timezone

            item.created_at = datetime.now(timezone.utc)


class AgentOrchestratorGracefulDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_graceful_drain_runs_final_agent_passes(self):
        websocket = AsyncMock()
        consolidated_agent = MagicMock()
        consolidated_agent.enabled_types = {"question", "opportunity"}
        consolidated_agent.run_cycle = AsyncMock()

        with (
            patch("app.services.agents.orchestrator.GeminiLiveSession", return_value=AsyncMock()),
            patch(
                "app.services.agents.orchestrator.ConsolidatedAnalystAgent",
                return_value=consolidated_agent,
            ),
        ):
            orchestrator = AgentOrchestrator(
                session_id=uuid4(),
                websocket=websocket,
                directives=[],
                doc_summaries="",
                active_questions=[],
                speakers=[],
                meeting_type="client_sales",
                agent_configs={
                    "consolidated_analyst": MagicMock(
                        enabled=True,
                        model_id="test-model",
                        prompt="",
                        interval_seconds=15,
                        sub_types="question,opportunity",
                        lenses="",
                    ),
                    "synthesizer": MagicMock(enabled=True, model_id="synth-model", prompt=""),
                    "opportunity_specialist": MagicMock(enabled=True, model_id="opp-model", prompt=""),
                },
            )
        orchestrator.transcript_buffer.get_window = AsyncMock(return_value="Speaker 1: We need EDR coverage.")
        orchestrator.consolidated_agent.run_cycle = AsyncMock(
            return_value=[
                {
                    "item_type": "opportunity",
                    "question": "Evaluate EDR coverage for this account.",
                    "rationale": "The customer raised endpoint coverage.",
                    "source_context": "We need EDR coverage.",
                    "agent_source": "consolidated_analyst",
                }
            ]
        )
        orchestrator._save_and_send_insight = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.agents.orchestrator.run_synthesizer_cycle",
                new=AsyncMock(return_value=[{"op": "answer"}]),
            ) as synth,
            patch(
                "app.services.agents.orchestrator.run_opportunity_specialist_cycle",
                new=AsyncMock(return_value=[{"op": "offering_match"}]),
            ) as opp,
        ):
            result = await orchestrator.graceful_drain()

        self.assertEqual(
            result,
            {
                "transcript_available": True,
                "insights_saved": 1,
                "synthesizer_ops": 1,
                "opportunity_ops": 1,
            },
        )
        orchestrator.consolidated_agent.run_cycle.assert_awaited_once()
        orchestrator._save_and_send_insight.assert_awaited_once()
        synth.assert_awaited_once()
        opp.assert_awaited_once()

    async def test_graceful_drain_reports_progress_stages(self):
        websocket = AsyncMock()
        consolidated_agent = MagicMock()
        consolidated_agent.enabled_types = {"question", "opportunity"}
        consolidated_agent.run_cycle = AsyncMock(return_value=[])

        with (
            patch("app.services.agents.orchestrator.GeminiLiveSession", return_value=AsyncMock()),
            patch(
                "app.services.agents.orchestrator.ConsolidatedAnalystAgent",
                return_value=consolidated_agent,
            ),
        ):
            orchestrator = AgentOrchestrator(
                session_id=uuid4(),
                websocket=websocket,
                directives=[],
                doc_summaries="",
                active_questions=[],
                speakers=[],
                meeting_type="client_sales",
                agent_configs={
                    "consolidated_analyst": MagicMock(
                        enabled=True,
                        model_id="test-model",
                        prompt="",
                        interval_seconds=15,
                        sub_types="question,opportunity",
                        lenses="",
                    ),
                    "synthesizer": MagicMock(enabled=True, model_id="synth-model", prompt=""),
                    "opportunity_specialist": MagicMock(enabled=True, model_id="opp-model", prompt=""),
                },
            )

        orchestrator.transcript_buffer.get_window = AsyncMock(return_value="Speaker 1: We need EDR coverage.")

        progress_events = []

        async def record_progress(event):
            progress_events.append(event)

        with (
            patch(
                "app.services.agents.orchestrator.run_synthesizer_cycle",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.agents.orchestrator.run_opportunity_specialist_cycle",
                new=AsyncMock(return_value=[]),
            ),
        ):
            await orchestrator.graceful_drain(progress_callback=record_progress)

        self.assertEqual(
            ["final_insights", "insight_reconciliation", "opportunity_matching"],
            [event["stage"] for event in progress_events],
        )
        self.assertEqual([2, 3, 4], [event["current_step"] for event in progress_events])
        self.assertTrue(all(event["total_steps"] == 5 for event in progress_events))

    async def test_save_and_send_insight_keeps_saved_result_when_websocket_is_closed(self):
        websocket = AsyncMock()
        websocket.send_json.side_effect = RuntimeError("Cannot call send once closed")
        fake_session = FakeSessionContext()

        with (
            patch("app.services.agents.orchestrator.GeminiLiveSession", return_value=AsyncMock()),
            patch("app.services.agents.orchestrator.ConsolidatedAnalystAgent", return_value=MagicMock(enabled_types={"question"})),
            patch("app.services.agents.orchestrator.async_session", return_value=fake_session),
        ):
            orchestrator = AgentOrchestrator(
                session_id=uuid4(),
                websocket=websocket,
                directives=[],
                doc_summaries="",
                active_questions=[],
                speakers=[],
                agent_configs={},
            )

            saved = await orchestrator._save_and_send_insight(
                {
                    "item_type": "question",
                    "question": "Who owns the final approval?",
                    "rationale": "The call mentioned funding gates.",
                    "source_context": "There are funding gates.",
                },
                agent_source="question_hunter",
            )

        self.assertTrue(saved)
        self.assertEqual(1, fake_session.commits)
        self.assertEqual(1, len(fake_session.added))
        self.assertEqual([{"id": str(fake_session.added[0].id), "question": "Who owns the final approval?"}], orchestrator.active_questions)
        websocket.send_json.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

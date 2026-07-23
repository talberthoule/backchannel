import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.agents.orchestrator import AgentOrchestrator, drain_progress_percent


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

    def _build_orchestrator(self, include_briefing: bool = False) -> AgentOrchestrator:
        websocket = AsyncMock()
        consolidated_agent = MagicMock()
        consolidated_agent.enabled_types = {"question", "opportunity"}
        consolidated_agent.run_cycle = AsyncMock(return_value=[])

        agent_configs = {
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
        }
        if include_briefing:
            agent_configs["brief_arbiter"] = MagicMock(enabled=True, model_id="brief-model", prompt="")

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
                agent_configs=agent_configs,
            )
        orchestrator.transcript_buffer.get_window = AsyncMock(return_value="Speaker 1: We need EDR coverage.")
        return orchestrator

    async def test_drain_stage_plans_reflect_mode(self):
        orchestrator = self._build_orchestrator(include_briefing=True)

        self.assertEqual(
            ["final_insights", "insight_reconciliation", "opportunity_matching", "call_briefing"],
            orchestrator.drain_stages("full"),
        )
        self.assertEqual(6, orchestrator.drain_total_steps("full"))
        self.assertEqual(
            ["final_insights", "insight_reconciliation"],
            orchestrator.drain_stages("skip_analysis"),
        )
        self.assertEqual(4, orchestrator.drain_total_steps("skip_analysis"))
        self.assertEqual([], orchestrator.drain_stages("minimal"))
        self.assertEqual(2, orchestrator.drain_total_steps("minimal"))

        no_briefing = self._build_orchestrator(include_briefing=False)
        self.assertEqual(
            ["final_insights", "insight_reconciliation", "opportunity_matching"],
            no_briefing.drain_stages("full"),
        )
        self.assertEqual(5, no_briefing.drain_total_steps("full"))

    async def test_drain_progress_percent_covers_overlay_band(self):
        self.assertEqual(15, drain_progress_percent(1, 6))
        self.assertEqual(95, drain_progress_percent(6, 6))
        self.assertEqual(15, drain_progress_percent(1, 2))
        self.assertEqual(95, drain_progress_percent(2, 2))
        self.assertEqual(42, drain_progress_percent(2, 4))

    async def test_live_cycle_calls_only_strategic_signals(self):
        orchestrator = self._build_orchestrator(include_briefing=True)
        orchestrator._agent_configs["strategic_signals"] = MagicMock(
            enabled=True,
            model_id="signal-model",
            prompt="signal-prompt",
            interval_seconds=45,
        )

        with (
            patch(
                "app.services.agents.orchestrator.asyncio.sleep",
                new=AsyncMock(
                    side_effect=[None, asyncio.CancelledError()]
                ),
            ),
            patch(
                "app.services.agents.orchestrator.run_strategic_signals_cycle",
                new=AsyncMock(return_value=None),
            ) as signals,
            patch(
                "app.services.agents.orchestrator.run_session_synthesis",
                new=AsyncMock(),
            ) as briefing,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await orchestrator._strategic_signals_loop()

        signals.assert_awaited_once()
        briefing.assert_not_awaited()

    async def test_graceful_drain_skip_analysis_skips_opportunity_and_briefing(self):
        orchestrator = self._build_orchestrator(include_briefing=True)
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

        progress_events = []

        async def record_progress(event):
            progress_events.append(event)

        with (
            patch(
                "app.services.agents.orchestrator.run_synthesizer_cycle",
                new=AsyncMock(return_value=[{"op": "answer"}]),
            ) as synth,
            patch(
                "app.services.agents.orchestrator.run_opportunity_specialist_cycle",
                new=AsyncMock(return_value=[]),
            ) as opp,
            patch(
                "app.services.agents.orchestrator.run_session_synthesis",
                new=AsyncMock(return_value=None),
            ) as briefing,
        ):
            result = await orchestrator.graceful_drain(
                progress_callback=record_progress, mode="skip_analysis"
            )

        orchestrator.consolidated_agent.run_cycle.assert_awaited_once()
        synth.assert_awaited_once()
        opp.assert_not_awaited()
        briefing.assert_not_awaited()
        self.assertEqual(
            result,
            {
                "transcript_available": True,
                "insights_saved": 1,
                "synthesizer_ops": 1,
                "opportunity_ops": 0,
            },
        )
        self.assertNotIn("synthesis_generated", result)
        self.assertEqual(
            ["final_insights", "insight_reconciliation"],
            [event["stage"] for event in progress_events],
        )
        self.assertEqual([2, 3], [event["current_step"] for event in progress_events])
        self.assertTrue(all(event["total_steps"] == 4 for event in progress_events))

    async def test_graceful_drain_full_with_briefing_reports_six_steps(self):
        orchestrator = self._build_orchestrator(include_briefing=True)
        orchestrator._save_and_send_insight = AsyncMock(return_value=True)

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
            patch(
                "app.services.agents.orchestrator.run_session_synthesis",
                new=AsyncMock(return_value=None),
            ) as briefing,
        ):
            result = await orchestrator.graceful_drain(progress_callback=record_progress)

        briefing.assert_awaited_once()
        self.assertIs(False, result["synthesis_generated"])
        self.assertEqual(
            ["final_insights", "insight_reconciliation", "opportunity_matching", "call_briefing"],
            [event["stage"] for event in progress_events],
        )
        self.assertEqual([2, 3, 4, 5], [event["current_step"] for event in progress_events])
        self.assertTrue(all(event["total_steps"] == 6 for event in progress_events))

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

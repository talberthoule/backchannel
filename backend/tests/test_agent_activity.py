import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.agents.activity import ActivityRegistry, saved_outcome
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.agents.prompts import DEFAULT_ANALYST_LENSES
from app.ws.audio_pipeline import (
    _AudioPipelineState,
    _cancel_gateway_reconnect,
    _maintain_audio_gateway,
    _transcription_failure_handler,
)


class _WebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


async def _wait_for_messages(websocket, count):
    deadline = asyncio.get_running_loop().time() + 1
    while len(websocket.messages) < count:
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Timed out waiting for {count} activity messages")
        await asyncio.sleep(0.005)


class ActivityRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_lifecycle_emits_full_snapshots_and_classifies_health(self):
        websocket = _WebSocket()
        registry = ActivityRegistry(
            uuid.uuid4(),
            websocket,
            [
                {
                    "slug": "consolidated_analyst",
                    "name": "Consolidated Analyst",
                    "trigger": "interval",
                    "state": "waiting",
                    "enabled": True,
                    "interval_seconds": 40,
                }
            ],
            coalesce_seconds=0.02,
        )

        await registry.emit(force=True)
        await registry.cycle_started("consolidated_analyst")
        await registry.cycle_finished(
            "consolidated_analyst",
            {"kind": "insights", "detail": "2 insights saved", "items": 2},
        )
        await registry.emit(force=True)

        record = websocket.messages[-1]["data"]["agents"][0]
        self.assertEqual("waiting", record["state"])
        self.assertEqual("insights", record["last_outcome"]["kind"])
        self.assertEqual(1, record["counts"]["runs"])
        self.assertEqual(2, record["counts"]["insights"])
        self.assertEqual(1, record["counts"]["productive"])
        self.assertIsNotNone(record["last_run_started_at"])
        self.assertIsNotNone(record["last_run_ms"])
        self.assertIsNotNone(record["next_due_at"])
        self.assertEqual(2, len(websocket.messages))

        await registry.cycle_error(
            "consolidated_analyst",
            {
                "kind": "timeout",
                "detail": "The endpoint timed out",
                "remedy": "Check the server.",
            },
        )
        self.assertEqual(3, len(websocket.messages))
        self.assertEqual(
            "failing",
            websocket.messages[-1]["data"]["agents"][0]["state"],
        )

        await registry.update_call(
            transcription={
                "jobs": 3,
                "failed": 1,
                "last_error": "Transcription failed for 1 segment",
            }
        )
        call = websocket.messages[-1]["data"]["call"]
        self.assertTrue(call["degraded"])
        self.assertEqual(1, call["transcription"]["failed"])
        self.assertIn("Transcription failed", call["degraded_reasons"][0])
        self.assertEqual(4, len(websocket.messages))

    def test_orchestrator_roster_explains_privacy_override_and_meeting_blocks(self):
        def config(slug, model_id, enabled=True, session_override=None):
            return SimpleNamespace(
                slug=slug,
                name=slug.replace("_", " ").title(),
                model_id=model_id,
                enabled=enabled,
                sub_types="",
                lenses="",
                prompt="",
                interval_seconds=20,
                model_intervals="",
                knowledge_source_ids="",
                _session_override=session_override,
            )

        orchestrator = AgentOrchestrator(
            session_id=uuid.uuid4(),
            websocket=_WebSocket(),
            directives=[],
            doc_summaries="",
            active_questions=[],
            speakers=[],
            agent_configs={
                "audio_gateway": config("audio_gateway", "local-live", False),
                "consolidated_analyst": config(
                    "consolidated_analyst", "cloud-model"
                ),
                "objection_handler": config(
                    "objection_handler",
                    "local-model",
                    False,
                    session_override=False,
                ),
                "opportunity_specialist": config(
                    "opportunity_specialist", "local-model"
                ),
            },
            meeting_type="general",
            local_only=True,
            admitted_models={"local-model"},
        )

        records = {
            record["slug"]: record
            for record in orchestrator.activity.snapshot()["agents"]
        }
        self.assertEqual("blocked", records["consolidated_analyst"]["state"])
        self.assertEqual(
            "privacy_first",
            records["consolidated_analyst"]["blocked_reason"],
        )
        self.assertIn("Admin -> Agents", records["consolidated_analyst"]["remedy"])
        self.assertEqual("off", records["objection_handler"]["state"])
        self.assertEqual(
            "session_override",
            records["objection_handler"]["blocked_reason"],
        )
        self.assertEqual("blocked", records["opportunity_specialist"]["state"])
        self.assertEqual(
            "meeting_type",
            records["opportunity_specialist"]["blocked_reason"],
        )
        # The analyst record carries its active lens count for the live summary
        # (empty lenses column falls back to the default lens set), minus any
        # lens suppressed for this meeting type. meeting_type="general" turns
        # offering matching off -- which is what blocks opportunity_specialist
        # just above -- so the analyst drops its opportunity lens rather than
        # scouting for matches nothing downstream can enrich (ALP-286).
        suppressed = {
            lens["item_type"] for lens in DEFAULT_ANALYST_LENSES
            if lens["item_type"] == "opportunity"
        }
        self.assertEqual(
            len(DEFAULT_ANALYST_LENSES) - len(suppressed),
            records["consolidated_analyst"]["lens_count"],
        )

    async def test_unselected_model_blocks_before_privacy_or_meeting_type(self):
        def config(slug):
            return SimpleNamespace(
                slug=slug,
                name=slug.replace("_", " ").title(),
                model_id="",
                enabled=True,
                sub_types="",
                lenses="",
                prompt="",
                interval_seconds=20,
                model_intervals="",
                knowledge_source_ids="",
                _session_override=None,
            )

        slugs = (
            "audio_gateway",
            "consolidated_analyst",
            "objection_handler",
            "synthesizer",
            "opportunity_specialist",
            "strategic_signals",
            "brief_meeting_lens",
            "brief_discovery_lens",
            "brief_arbiter",
        )
        with patch("app.services.agents.orchestrator.GeminiLiveSession") as gateway:
            orchestrator = AgentOrchestrator(
                session_id=uuid.uuid4(),
                websocket=_WebSocket(),
                directives=[],
                doc_summaries="",
                active_questions=[],
                speakers=[],
                agent_configs={slug: config(slug) for slug in slugs},
                meeting_type="general",
                local_only=True,
                admitted_models=set(),
            )

        gateway.assert_not_called()
        self.assertIsNone(orchestrator.audio_gateway)
        records = {
            record["slug"]: record
            for record in orchestrator.activity.snapshot()["agents"]
        }
        for slug in slugs:
            self.assertEqual("blocked", records[slug]["state"], slug)
            self.assertEqual("no_model", records[slug]["blocked_reason"], slug)
            self.assertIn("Admin -> Agents", records[slug]["remedy"], slug)
            self.assertFalse(orchestrator._is_enabled(slug), slug)

        await orchestrator.start()
        self.assertIsNone(orchestrator._gateway_task)
        self.assertIsNone(orchestrator._consolidated_task)
        self.assertIsNone(orchestrator._objection_task)
        self.assertIsNone(orchestrator._synth_subscriber)
        self.assertIsNone(orchestrator._opp_specialist_subscriber)
        self.assertIsNone(orchestrator._strategic_signals_task)
        await orchestrator.close_all()

    def test_saved_outcome_distinguishes_insights_dedup_and_model_silence(self):
        partial = saved_outcome(
            {"kind": "insights", "items": 3},
            produced=3,
            saved=2,
        )
        self.assertEqual("insights", partial["kind"])
        self.assertEqual(1, partial["deduped"])
        deduped = saved_outcome(
            {"kind": "insights", "items": 3},
            produced=3,
            saved=0,
        )
        self.assertEqual("all_deduped", deduped["kind"])
        self.assertEqual(3, deduped["deduped"])
        self.assertEqual(
            "all_filtered",
            saved_outcome(
                {"kind": "all_filtered", "items": 0},
                produced=0,
                saved=0,
            )["kind"],
        )

    async def test_regular_changes_coalesce_but_blocked_transitions_emit_immediately(self):
        websocket = _WebSocket()
        registry = ActivityRegistry(
            uuid.uuid4(),
            websocket,
            [
                {
                    "slug": "objection_handler",
                    "name": "Objection Handler",
                    "trigger": "interval",
                    "state": "waiting",
                    "enabled": True,
                    "interval_seconds": 10,
                }
            ],
            coalesce_seconds=0.03,
        )

        await registry.emit(force=True)
        await registry.cycle_started("objection_handler")
        await registry.cycle_finished(
            "objection_handler",
            {"kind": "no_findings", "detail": "No findings", "items": 0},
        )
        self.assertEqual(1, len(websocket.messages))
        await _wait_for_messages(websocket, 2)
        self.assertEqual(2, len(websocket.messages))

        await registry.set_agent_state(
            "objection_handler",
            "blocked",
            blocked_reason="privacy_first",
            remedy="Assign a local model.",
        )
        self.assertEqual(3, len(websocket.messages))

    async def test_transcription_failure_updates_the_durable_call_health(self):
        websocket = _WebSocket()
        registry = ActivityRegistry(uuid.uuid4(), websocket, [])
        handler = _transcription_failure_handler(
            websocket,
            batch_model_is_local=False,
            activity=registry,
        )

        await handler(1, "transcribe")
        await handler(2, "transcribe")
        await registry.emit(force=True)

        call = websocket.messages[-1]["data"]["call"]
        self.assertEqual(2, call["transcription"]["failed"])
        self.assertIn("API key", call["transcription"]["last_error"])
        self.assertTrue(call["degraded"])

    async def test_gateway_loss_records_the_failure_while_reconnecting(self):
        websocket = _WebSocket()
        registry = ActivityRegistry(
            uuid.uuid4(),
            websocket,
            [
                {
                    "slug": "audio_gateway",
                    "name": "Audio Bridge",
                    "trigger": "stream",
                    "state": "running",
                    "enabled": True,
                    "interval_seconds": None,
                }
            ],
        )
        orchestrator = SimpleNamespace(
            activity=registry,
            check_health=AsyncMock(return_value=False),
        )
        state = _AudioPipelineState()

        with patch(
            "app.ws.audio_pipeline._reconnect_audio_gateway",
            new=AsyncMock(return_value=False),
        ):
            await _maintain_audio_gateway(websocket, orchestrator, state)
            record = registry.snapshot()["agents"][0]

        await _cancel_gateway_reconnect(state)
        self.assertEqual("failing", record["state"])
        self.assertIn("stopped responding", record["last_error"]["detail"])
        self.assertEqual("reconnecting", registry.snapshot()["call"]["gateway"]["state"])


if __name__ == "__main__":
    unittest.main()

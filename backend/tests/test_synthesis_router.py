import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.routers.synthesis import get_synthesis, refresh_synthesis
from app.services.agents.orchestrator import _synthesis_payload


def _synthesis(history=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        mode="live",
        status="completed",
        top_outcomes=[],
        client_objectives=[],
        top_opportunities=[],
        risks_blockers=[],
        action_plan=[],
        unresolved_discovery_questions=[],
        strategic_signals=[],
        signal_history=history or [],
        evidence_refs=[],
        lens_meeting={},
        lens_discovery={},
        arbiter_notes="",
        model_ids={},
        error_message="",
        created_at=now,
        updated_at=now,
        clusters=[],
    )


class SynthesisRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_is_returned_only_for_explicit_get(self):
        session_id = uuid4()
        db = AsyncMock()
        db.get.return_value = SimpleNamespace(id=session_id)
        expected = _synthesis(
            [{"section": "strategic_signals", "title": "Budget", "count": 2}]
        )

        with patch(
            "app.routers.synthesis.get_session_synthesis",
            new=AsyncMock(return_value=expected),
        ):
            summary = await get_synthesis(
                session_id,
                mode="live",
                include_history=False,
                db=db,
            )
            full = await get_synthesis(
                session_id,
                mode="live",
                include_history=True,
                db=db,
            )

        self.assertEqual(1, summary.signal_history_count)
        self.assertEqual([], summary.signal_history)
        self.assertEqual(1, full.signal_history_count)
        self.assertEqual(expected.signal_history, full.signal_history)

    def test_websocket_payload_sends_history_count_not_full_history(self):
        synthesis = _synthesis(
            [
                {"section": "strategic_signals", "title": "Budget"},
                {"section": "risks_blockers", "title": "Timeline"},
            ]
        )

        payload = _synthesis_payload(synthesis)

        self.assertEqual(2, payload["signal_history_count"])
        self.assertNotIn("signal_history", payload)

    async def test_live_refresh_dispatches_to_strategic_signals(self):
        session_id = uuid4()
        db = AsyncMock()
        db.get.return_value = SimpleNamespace(id=session_id)
        expected = _synthesis(
            [{"section": "strategic_signals", "title": "Budget"}]
        )

        with (
            patch(
                "app.routers.synthesis.run_strategic_signals_cycle",
                new=AsyncMock(return_value=expected),
            ) as signals,
            patch(
                "app.routers.synthesis.run_session_synthesis",
                new=AsyncMock(),
            ) as briefing,
        ):
            result = await refresh_synthesis(
                session_id,
                mode="live",
                db=db,
            )

        self.assertEqual(1, result.signal_history_count)
        self.assertEqual([], result.signal_history)
        signals.assert_awaited_once_with(session_id)
        briefing.assert_not_awaited()

    async def test_post_call_refresh_dispatches_to_briefing_trio(self):
        session_id = uuid4()
        db = AsyncMock()
        db.get.return_value = SimpleNamespace(id=session_id)
        expected = _synthesis()
        expected.mode = "post_call"

        with (
            patch(
                "app.routers.synthesis.run_strategic_signals_cycle",
                new=AsyncMock(),
            ) as signals,
            patch(
                "app.routers.synthesis.run_session_synthesis",
                new=AsyncMock(return_value=expected),
            ) as briefing,
        ):
            result = await refresh_synthesis(
                session_id,
                mode="post_call",
                db=db,
            )

        self.assertEqual("post_call", result.mode)
        self.assertEqual(0, result.signal_history_count)
        briefing.assert_awaited_once_with(
            session_id,
            mode="post_call",
        )
        signals.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

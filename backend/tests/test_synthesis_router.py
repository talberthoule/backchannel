import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.routers.synthesis import refresh_synthesis


class SynthesisRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_refresh_dispatches_to_strategic_signals(self):
        session_id = uuid4()
        db = AsyncMock()
        db.get.return_value = SimpleNamespace(id=session_id)
        expected = SimpleNamespace()

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

        self.assertIs(expected, result)
        signals.assert_awaited_once_with(session_id)
        briefing.assert_not_awaited()

    async def test_post_call_refresh_dispatches_to_briefing_trio(self):
        session_id = uuid4()
        db = AsyncMock()
        db.get.return_value = SimpleNamespace(id=session_id)
        expected = SimpleNamespace()

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

        self.assertIs(expected, result)
        briefing.assert_awaited_once_with(
            session_id,
            mode="post_call",
        )
        signals.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

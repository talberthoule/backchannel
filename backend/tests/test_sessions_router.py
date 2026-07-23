import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.routers.sessions import update_session
from app.schemas import SessionUpdate


def _session(state: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        state=state,
        started_at=None,
        ended_at=None,
    )


class UpdateSessionStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_call_stamps_started_at(self):
        # Regression: v0.3.1-v0.3.3 shipped without the datetime import, so
        # the pre_call -> active transition (Start Call) raised NameError.
        session = _session("pre_call")
        db = AsyncMock()
        db.get.return_value = session

        result = await update_session(session.id, SessionUpdate(state="active"), db=db)

        self.assertIs(result, session)
        self.assertEqual(session.state, "active")
        self.assertIsInstance(session.started_at, datetime)
        self.assertIsNotNone(session.started_at.tzinfo)
        db.commit.assert_awaited_once()

    async def test_end_call_stamps_ended_at(self):
        session = _session("active")
        session.started_at = datetime.now(timezone.utc)
        db = AsyncMock()
        db.get.return_value = session

        await update_session(session.id, SessionUpdate(state="completed"), db=db)

        self.assertEqual(session.state, "completed")
        self.assertIsInstance(session.ended_at, datetime)

    async def test_resume_completed_session_clears_ended_at(self):
        session = _session("completed")
        session.ended_at = datetime.now(timezone.utc)
        db = AsyncMock()
        db.get.return_value = session

        await update_session(session.id, SessionUpdate(state="active"), db=db)

        self.assertEqual(session.state, "active")
        self.assertIsNone(session.ended_at)


if __name__ == "__main__":
    unittest.main()

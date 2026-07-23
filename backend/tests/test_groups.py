import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.models import SessionGroup
from app.routers.groups import delete_group


class DeleteGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_ungroups_sessions_without_deleting_them(self):
        group_id = uuid.uuid4()
        group = SessionGroup(id=group_id, name="Discovery")
        db = MagicMock()
        db.get = AsyncMock(return_value=group)
        db.execute = AsyncMock()
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        await delete_group(group_id, db)

        db.get.assert_awaited_once_with(SessionGroup, group_id)
        db.delete.assert_awaited_once_with(group)
        db.commit.assert_awaited_once()
        sql = str(
            db.execute.await_args.args[0].compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("UPDATE sessions SET group_id=NULL", sql)
        self.assertIn(group_id.hex, sql)


if __name__ == "__main__":
    unittest.main()

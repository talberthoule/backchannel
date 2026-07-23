import unittest
from unittest.mock import patch

from app.main import _add_missing_columns, _cleanup_orphan_audio


class FakeInspector:
    def get_table_names(self):
        return ["call_segments"]

    def get_columns(self, table):
        self.assert_call_segments(table)
        return [{"name": "audio_path"}]

    @staticmethod
    def assert_call_segments(table):
        if table != "call_segments":
            raise AssertionError(table)


class FakeSyncConnection:
    def __init__(self):
        self.executed = []

    def execute(self, statement):
        self.executed.append(str(statement))


class FakeAsyncConnection:
    def __init__(self):
        self.sync = FakeSyncConnection()

    async def run_sync(self, callback):
        callback(self.sync)


class FakeCleanupConnection:
    async def execute(self, statement):
        del statement
        return [
            ("audio/session/segment_1_mic.wav", "audio/session/segment_1_sys.wav"),
            (None, "audio/session/segment_2_sys.wav"),
        ]


class StartupSchemaPatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_adds_both_track_provenance_columns_to_existing_database(self):
        connection = FakeAsyncConnection()

        with patch("sqlalchemy.inspect", return_value=FakeInspector()):
            await _add_missing_columns(connection)

        sql = "\n".join(connection.sync.executed)
        self.assertIn("ADD COLUMN mic_audio_path VARCHAR(500)", sql)
        self.assertIn("ADD COLUMN system_audio_path VARCHAR(500)", sql)

    async def test_startup_cleanup_preserves_database_referenced_tracks(self):
        with patch("app.main.cleanup_orphan_track_audio", return_value=0) as cleanup:
            await _cleanup_orphan_audio(FakeCleanupConnection())

        cleanup.assert_called_once_with(
            {
                "audio/session/segment_1_mic.wav",
                "audio/session/segment_1_sys.wav",
                "audio/session/segment_2_sys.wav",
            }
        )


if __name__ == "__main__":
    unittest.main()

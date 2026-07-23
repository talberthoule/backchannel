import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock
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


class FakeRevalidationInspector:
    def get_table_names(self):
        return ["sessions", "questions", "session_syntheses"]

    def get_columns(self, table):
        existing = {
            "sessions": {"speaker_context_dirty", "speaker_context_enhanced_at"},
            "questions": {"enhanced"},
            "session_syntheses": {"status"},
        }
        return [{"name": name} for name in existing[table]]


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

    async def test_adds_revalidation_revision_columns_to_existing_database(self):
        connection = FakeAsyncConnection()

        with patch("sqlalchemy.inspect", return_value=FakeRevalidationInspector()):
            await _add_missing_columns(connection)

        sql = "\n".join(connection.sync.executed)
        self.assertIn(
            "ADD COLUMN speaker_context_version INTEGER NOT NULL DEFAULT 0",
            sql,
        )
        self.assertIn("ADD COLUMN speaker_mapping_revision_id UUID", sql)
        self.assertEqual(2, sql.count("ADD COLUMN speaker_mapping_revision_id UUID"))


class AlembicTrackPathRevisionTests(unittest.TestCase):
    def test_revision_016_upgrade_and_downgrade(self):
        path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "016_add_call_segment_track_paths.py"
        )
        spec = importlib.util.spec_from_file_location("alembic_revision_016", path)
        self.assertIsNotNone(spec)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        revision.op = MagicMock()

        revision.upgrade()

        added = revision.op.add_column.call_args_list
        self.assertEqual(
            ["mic_audio_path", "system_audio_path"],
            [call.args[1].name for call in added],
        )
        self.assertEqual([500, 500], [call.args[1].type.length for call in added])
        self.assertEqual([True, True], [call.args[1].nullable for call in added])

        revision.downgrade()

        self.assertEqual(
            [
                (("call_segments", "system_audio_path"), {}),
                (("call_segments", "mic_audio_path"), {}),
            ],
            [(call.args, call.kwargs) for call in revision.op.drop_column.call_args_list],
        )


class AlembicSpeakerRevalidationRevisionTests(unittest.TestCase):
    def test_revision_018_upgrade_and_downgrade(self):
        path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "018_add_speaker_revalidation.py"
        )
        spec = importlib.util.spec_from_file_location("alembic_revision_018", path)
        self.assertIsNotNone(spec)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        revision.op = MagicMock()

        revision.upgrade()

        self.assertEqual(
            [
                "speaker_mapping_revisions",
                "speaker_revalidation_runs",
                "speaker_revalidation_batches",
            ],
            [call.args[0] for call in revision.op.create_table.call_args_list],
        )
        self.assertEqual(
            [
                ("sessions", "speaker_context_version"),
                ("questions", "speaker_mapping_revision_id"),
                ("session_syntheses", "speaker_mapping_revision_id"),
            ],
            [
                (call.args[0], call.args[1].name)
                for call in revision.op.add_column.call_args_list
            ],
        )

        revision.downgrade()

        self.assertEqual(
            [
                "speaker_revalidation_batches",
                "speaker_revalidation_runs",
                "speaker_mapping_revisions",
            ],
            [call.args[0] for call in revision.op.drop_table.call_args_list],
        )
        self.assertEqual(
            [
                ("session_syntheses", "speaker_mapping_revision_id"),
                ("questions", "speaker_mapping_revision_id"),
                ("sessions", "speaker_context_version"),
            ],
            [call.args for call in revision.op.drop_column.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()

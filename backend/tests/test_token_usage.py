import importlib.util
import unittest
import uuid
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from app.main import _add_thinking_token_column
from app.routers.sessions import get_token_usage
from app.services import token_usage
from app.services.token_usage import UsageCounts


def counts(input_tokens, output_tokens, thinking=0, total=None, seconds=0.0, cached=0, audio_in=0, audio_out=0):
    """UsageCounts with the total synthesized unless given, for terse asserts."""
    if total is None:
        total = input_tokens + output_tokens + thinking
    return UsageCounts(input_tokens, output_tokens, thinking, total, seconds, cached, audio_in, audio_out)


class _Modality(str, Enum):
    """Shaped like google.genai.types.MediaModality: a str enum whose str()
    form is "_Modality.AUDIO" rather than "AUDIO"."""

    TEXT = "TEXT"
    AUDIO = "AUDIO"


def _modality_count(modality, token_count):
    return SimpleNamespace(modality=modality, token_count=token_count)


class TokenUsageTests(unittest.IsolatedAsyncioTestCase):
    """normalize_usage returns UsageCounts: (input, output, thinking, total,
    audio_seconds, cached_input, audio_input, audio_output).

    audio_seconds exists because OpenAI Realtime transcription bills per
    minute and reports no token counts at all, so a token-only tuple had
    nowhere to put it and the usage was dropped (ALP-300). The three trailing
    slices are subsets of input / output that bill at their own rates.
    """

    def test_normalizes_gemini_and_openai_usage(self):
        gemini = SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=5,
            total_token_count=17,
        )
        self.assertEqual(counts(12, 5), token_usage.normalize_usage(gemini))
        self.assertEqual(
            counts(8, 3),
            token_usage.normalize_usage({"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}),
        )
        self.assertEqual(
            counts(7, 2),
            token_usage.normalize_usage({"input_tokens": 7, "output_tokens": 2}),
        )

    def test_result_stays_positionally_compatible(self):
        # Readers that index 0..4 predate the slices and must keep working.
        normalized = token_usage.normalize_usage({"input_tokens": 7, "output_tokens": 2})
        self.assertEqual((7, 2, 0, 9, 0.0), normalized[:5])
        self.assertEqual(7, normalized.input_tokens)
        self.assertEqual(0, normalized.cached_input_tokens)

    def test_normalizes_gemini_live_response_tokens(self):
        live = SimpleNamespace(
            prompt_token_count=12,
            response_token_count=5,
            total_token_count=17,
        )
        self.assertEqual(counts(12, 5), token_usage.normalize_usage(live))

    def test_captures_gemini_thinking_tokens_without_double_counting(self):
        # Gemini's reported total already includes thoughts, so the total must
        # pass through untouched: 12 + 5 + 40 would overstate it as 57.
        thinking = SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=5,
            thoughts_token_count=40,
            total_token_count=57,
        )
        self.assertEqual(counts(12, 5, 40, 57), token_usage.normalize_usage(thinking))

    def test_synthesized_total_includes_thinking(self):
        self.assertEqual(
            counts(10, 4, 6, 20),
            token_usage.normalize_usage({"input_tokens": 10, "output_tokens": 4, "thoughts_token_count": 6}),
        )

    def test_captures_openai_nested_reasoning_tokens(self):
        openai = {
            "prompt_tokens": 9,
            "completion_tokens": 7,
            "total_tokens": 16,
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
        self.assertEqual(counts(9, 7, 5, 16), token_usage.normalize_usage(openai))

    def test_thinking_only_usage_is_still_recorded(self):
        self.assertEqual(
            counts(0, 0, 3, 3),
            token_usage.normalize_usage({"thoughts_token_count": 3}),
        )

    # --- cached and audio slices ---

    def test_captures_gemini_cached_and_audio_slices(self):
        """A batch transcription request: a WAV plus a short text prompt.

        The audio dominates the prompt and bills at the audio rate, so it has
        to be recorded apart from the text or the estimate uses the text rate
        for all of it.
        """
        gemini = SimpleNamespace(
            prompt_token_count=1030,
            candidates_token_count=20,
            total_token_count=1050,
            cached_content_token_count=0,
            prompt_tokens_details=[
                _modality_count(_Modality.TEXT, 30),
                _modality_count(_Modality.AUDIO, 1000),
            ],
            candidates_tokens_details=[_modality_count(_Modality.TEXT, 20)],
        )
        self.assertEqual(
            counts(1030, 20, 0, 1050, audio_in=1000),
            token_usage.normalize_usage(gemini),
        )

    def test_captures_gemini_implicit_cache_hits(self):
        gemini = SimpleNamespace(
            prompt_token_count=5000,
            candidates_token_count=100,
            total_token_count=5100,
            cached_content_token_count=4096,
        )
        self.assertEqual(counts(5000, 100, cached=4096), token_usage.normalize_usage(gemini))

    def test_captures_gemini_live_audio_output(self):
        # The live gateway answers in audio; the Live API names the output
        # breakdown response_tokens_details rather than candidates_*.
        live = SimpleNamespace(
            prompt_token_count=640,
            response_token_count=25,
            total_token_count=665,
            prompt_tokens_details=[_modality_count(_Modality.AUDIO, 600), _modality_count(_Modality.TEXT, 40)],
            response_tokens_details=[_modality_count(_Modality.AUDIO, 25)],
        )
        self.assertEqual(
            counts(640, 25, audio_in=600, audio_out=25),
            token_usage.normalize_usage(live),
        )

    def test_reads_modality_from_plain_strings_and_dicts(self):
        gemini = {
            "prompt_token_count": 100,
            "candidates_token_count": 10,
            "prompt_tokens_details": [
                {"modality": "AUDIO", "token_count": 60},
                {"modality": "MediaModality.AUDIO", "token_count": 20},
                {"modality": "TEXT", "token_count": 20},
            ],
        }
        self.assertEqual(counts(100, 10, audio_in=80), token_usage.normalize_usage(gemini))

    def test_captures_openai_cached_and_audio_slices(self):
        chat = {
            "prompt_tokens": 2000,
            "completion_tokens": 50,
            "total_tokens": 2050,
            "prompt_tokens_details": {"cached_tokens": 1500, "audio_tokens": 300},
            "completion_tokens_details": {"reasoning_tokens": 0, "audio_tokens": 10},
        }
        self.assertEqual(
            counts(2000, 50, 0, 2050, cached=1500, audio_in=300, audio_out=10),
            token_usage.normalize_usage(chat),
        )

    def test_captures_openai_realtime_token_shaped_usage(self):
        # gpt-4o-transcribe over the Realtime socket reports per-item token
        # counts with the audio slice under input_token_details.
        realtime = {
            "type": "tokens",
            "total_tokens": 110,
            "input_tokens": 100,
            "input_token_details": {"text_tokens": 4, "audio_tokens": 96},
            "output_tokens": 10,
        }
        self.assertEqual(counts(100, 10, 0, 110, audio_in=96), token_usage.normalize_usage(realtime))

    def test_captures_openai_responses_api_cached_tokens(self):
        responses = {
            "input_tokens": 400,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 256},
            "output_tokens_details": {"reasoning_tokens": 8},
        }
        self.assertEqual(counts(400, 20, 8, cached=256), token_usage.normalize_usage(responses))

    def test_slices_are_clamped_to_their_side(self):
        # A slice larger than the count it is part of would price more cached
        # or audio tokens than there were tokens; clamp rather than trust it.
        # Cached takes the input tokens first, so the audio slice is what is
        # left over: nothing here.
        odd = {
            "prompt_tokens": 10,
            "completion_tokens": 3,
            "prompt_tokens_details": {"cached_tokens": 50, "audio_tokens": 50},
            "completion_tokens_details": {"audio_tokens": 9},
        }
        self.assertEqual(counts(10, 3, cached=10, audio_in=0, audio_out=3), token_usage.normalize_usage(odd))

    def test_cached_and_audio_input_are_clamped_jointly(self):
        # Both are slices of the same input count, so their sum can never
        # exceed it; otherwise the API and the Tokens tab would report 900
        # audio and 800 cached of 1,000 input while the estimate priced fewer.
        # Cached wins, mirroring frontend/src/lib/modelPricing.ts.
        gemini = {
            "prompt_token_count": 1000,
            "candidates_token_count": 10,
            "cached_content_token_count": 800,
            "prompt_tokens_details": [{"modality": "AUDIO", "token_count": 900}],
        }
        self.assertEqual(counts(1000, 10, cached=800, audio_in=200), token_usage.normalize_usage(gemini))

    def test_slices_alone_do_not_make_an_empty_payload_recordable(self):
        # Modality details without any count are not usage.
        self.assertIsNone(
            token_usage.normalize_usage({"prompt_tokens_details": {"cached_tokens": 5}})
        )

    # --- duration-billed rows ---

    def test_realtime_duration_payload_is_recorded_not_dropped(self):
        """The exact shape that was being discarded.

        OpenAI Realtime transcription reports this on
        conversation.item.input_audio_transcription.completed. It carries no
        token counts, so before ALP-300 it normalized to all-zero and returned
        None, and the live gateway's spend vanished from the cost page.
        """
        self.assertEqual(
            counts(0, 0, seconds=4.5),
            token_usage.normalize_usage({"type": "duration", "seconds": 4.5}, "audio_gateway"),
        )

    def test_duration_is_not_truncated_to_whole_seconds(self):
        # Segments are seldom whole seconds; int() on each would lose minutes
        # across a call of any length.
        normalized = token_usage.normalize_usage({"seconds": 0.75})
        self.assertEqual(0.75, normalized.audio_seconds)

    def test_a_duration_payload_does_not_warn(self):
        token_usage._warned_usage_sources.clear()
        self.addCleanup(token_usage._warned_usage_sources.clear)
        with mock.patch.object(token_usage.logger, "warning") as warning:
            token_usage.normalize_usage({"type": "duration", "seconds": 2.0}, "audio_gateway")
        warning.assert_not_called()

    def test_zero_duration_is_still_dropped(self):
        # A silent stretch bills nothing; writing a row per empty event would
        # be noise, not signal.
        self.assertIsNone(token_usage.normalize_usage({"type": "duration", "seconds": 0}))

    def test_duration_billed_rows_reach_the_summary(self):
        rows = [
            SimpleNamespace(source="audio_gateway", model_id="gpt-live-transcribe", input_tokens=0, output_tokens=0, thinking_tokens=0, total_tokens=0, audio_seconds=120.0),
            SimpleNamespace(source="consolidated_analyst", model_id="gpt-5.6-luna", input_tokens=20, output_tokens=4, thinking_tokens=0, total_tokens=24, audio_seconds=0.0),
        ]
        summary = token_usage.summarize_usage(rows)
        self.assertEqual(120.0, summary["audio_seconds"])
        by_source = {item["source"]: item for item in summary["by_source"]}
        self.assertEqual(120.0, by_source["audio_gateway"]["audio_seconds"])
        # The zero-token gateway row survives the token-ordered sort rather
        # than being filtered out; ordering by cost is the UI's job, since
        # seconds and tokens have no common scale here.
        self.assertIn("audio_gateway", by_source)
        self.assertEqual(0, by_source["audio_gateway"]["total_tokens"])

    def test_legacy_rows_without_audio_column_summarize_as_zero(self):
        rows = [SimpleNamespace(source="analyze", model_id="gemini-pro", input_tokens=6, output_tokens=2, thinking_tokens=0, total_tokens=8, audio_seconds=None)]
        self.assertEqual(0.0, token_usage.summarize_usage(rows)["audio_seconds"])

    # --- recording ---

    async def test_unrecognized_usage_warns_only_once_per_source(self):
        token_usage._warned_usage_sources.clear()
        self.addCleanup(token_usage._warned_usage_sources.clear)
        with mock.patch.object(token_usage.logger, "warning") as warning:
            await token_usage.record_token_usage(
                uuid.uuid4(), "audio_gateway", "live-model", {"mystery_tokens": 4}
            )
            await token_usage.record_token_usage(
                uuid.uuid4(), "audio_gateway", "live-model", {"mystery_tokens": 5}
            )
            await token_usage.record_token_usage(
                uuid.uuid4(), "batch_transcriber", "batch-model", {"mystery_tokens": 6}
            )
        self.assertEqual(2, warning.call_count)
        self.assertIn("audio_gateway", warning.call_args_list[0].args)
        self.assertIn("batch_transcriber", warning.call_args_list[1].args)

    async def test_recorded_row_carries_every_slice(self):
        added = []
        db = mock.MagicMock()
        db.add = added.append
        db.commit = mock.AsyncMock()
        factory = mock.MagicMock()
        factory.return_value.__aenter__ = mock.AsyncMock(return_value=db)
        factory.return_value.__aexit__ = mock.AsyncMock(return_value=False)
        session_id = uuid.uuid4()
        with mock.patch.object(token_usage, "async_session", factory):
            await token_usage.record_token_usage(
                session_id,
                "batch_transcriber",
                "gemini-2.5-flash",
                {
                    "prompt_token_count": 1030,
                    "candidates_token_count": 20,
                    "total_token_count": 1050,
                    "cached_content_token_count": 0,
                    "prompt_tokens_details": [{"modality": "AUDIO", "token_count": 1000}],
                },
            )
        self.assertEqual(1, len(added))
        row = added[0]
        self.assertEqual(session_id, row.session_id)
        self.assertEqual((1030, 20, 0, 1050), (row.input_tokens, row.output_tokens, row.thinking_tokens, row.total_tokens))
        self.assertEqual((0, 1000, 0), (row.cached_input_tokens, row.audio_input_tokens, row.audio_output_tokens))
        db.commit.assert_awaited_once()

    # --- summary ---

    def test_summarizes_by_source_and_model(self):
        rows = [
            SimpleNamespace(source="batch_transcriber", model_id="gemini-flash", input_tokens=10, output_tokens=2, thinking_tokens=0, total_tokens=12),
            SimpleNamespace(source="batch_transcriber", model_id="gemini-flash", input_tokens=5, output_tokens=1, thinking_tokens=0, total_tokens=6),
            SimpleNamespace(source="consolidated_analyst", model_id="gemini-pro", input_tokens=20, output_tokens=4, thinking_tokens=9, total_tokens=33),
        ]
        summary = token_usage.summarize_usage(rows)
        self.assertEqual(51, summary["total_tokens"])
        self.assertEqual(35, summary["input_tokens"])
        self.assertEqual(7, summary["output_tokens"])
        self.assertEqual(9, summary["thinking_tokens"])
        self.assertEqual(
            {
                (item["source"], item["model_id"]): item["total_tokens"]
                for item in summary["by_source"]
            },
            {("batch_transcriber", "gemini-flash"): 18, ("consolidated_analyst", "gemini-pro"): 33},
        )
        self.assertEqual(
            {item["model_id"]: item["total_tokens"] for item in summary["by_model"]},
            {"gemini-flash": 18, "gemini-pro": 33},
        )

    def test_summary_carries_the_slices_through_every_level(self):
        rows = [
            SimpleNamespace(source="batch_transcriber", model_id="gemini-2.5-flash", input_tokens=1030, output_tokens=20, thinking_tokens=0, total_tokens=1050, audio_seconds=0.0, cached_input_tokens=0, audio_input_tokens=1000, audio_output_tokens=0),
            SimpleNamespace(source="batch_transcriber", model_id="gemini-2.5-flash", input_tokens=530, output_tokens=10, thinking_tokens=0, total_tokens=540, audio_seconds=0.0, cached_input_tokens=0, audio_input_tokens=500, audio_output_tokens=0),
            SimpleNamespace(source="synthesizer", model_id="gemini-2.5-flash", input_tokens=5000, output_tokens=100, thinking_tokens=0, total_tokens=5100, audio_seconds=0.0, cached_input_tokens=4096, audio_input_tokens=0, audio_output_tokens=0),
            SimpleNamespace(source="audio_gateway", model_id="gemini-live", input_tokens=640, output_tokens=25, thinking_tokens=0, total_tokens=665, audio_seconds=0.0, cached_input_tokens=0, audio_input_tokens=600, audio_output_tokens=25),
        ]
        summary = token_usage.summarize_usage(rows)
        self.assertEqual((4096, 2100, 25), (summary["cached_input_tokens"], summary["audio_input_tokens"], summary["audio_output_tokens"]))
        by_source = {item["source"]: item for item in summary["by_source"]}
        self.assertEqual(1500, by_source["batch_transcriber"]["audio_input_tokens"])
        self.assertEqual(4096, by_source["synthesizer"]["cached_input_tokens"])
        self.assertEqual(25, by_source["audio_gateway"]["audio_output_tokens"])
        by_model = {item["model_id"]: item for item in summary["by_model"]}
        # Slices merge across sources for the same model, like the counts do.
        self.assertEqual((4096, 1500), (by_model["gemini-2.5-flash"]["cached_input_tokens"], by_model["gemini-2.5-flash"]["audio_input_tokens"]))

    def test_legacy_rows_without_thinking_column_summarize_as_zero(self):
        # Rows written before the column existed arrive as NULL from the driver.
        rows = [SimpleNamespace(source="analyze", model_id="gemini-pro", input_tokens=6, output_tokens=2, thinking_tokens=None, total_tokens=8)]
        summary = token_usage.summarize_usage(rows)
        self.assertEqual(0, summary["thinking_tokens"])
        self.assertEqual(8, summary["total_tokens"])

    def test_legacy_rows_without_slice_columns_summarize_as_zero(self):
        rows = [SimpleNamespace(source="analyze", model_id="gemini-pro", input_tokens=6, output_tokens=2, thinking_tokens=0, total_tokens=8, cached_input_tokens=None, audio_input_tokens=None, audio_output_tokens=None)]
        summary = token_usage.summarize_usage(rows)
        self.assertEqual((0, 0, 0), (summary["cached_input_tokens"], summary["audio_input_tokens"], summary["audio_output_tokens"]))

    def test_empty_summary_is_zero(self):
        self.assertEqual(
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "thinking_tokens": 0,
                "total_tokens": 0,
                "audio_seconds": 0.0,
                "cached_input_tokens": 0,
                "audio_input_tokens": 0,
                "audio_output_tokens": 0,
                "by_source": [],
                "by_model": [],
            },
            token_usage.summarize_usage([]),
        )

    async def test_recording_failure_never_escapes(self):
        with mock.patch.object(token_usage, "async_session", side_effect=RuntimeError("db unavailable")), \
             mock.patch.object(token_usage.logger, "exception"):
            await token_usage.record_token_usage(
                uuid.uuid4(),
                "consolidated_analyst",
                "gemini-pro",
                {"prompt_tokens": 2, "completion_tokens": 1},
            )

    async def test_missing_usage_is_not_written(self):
        session_factory = mock.MagicMock()
        with mock.patch.object(token_usage, "async_session", session_factory):
            await token_usage.record_token_usage(uuid.uuid4(), "chat", "gemini-pro", None)
        session_factory.assert_not_called()

    async def test_malformed_provider_usage_never_escapes(self):
        with mock.patch.object(token_usage.logger, "exception"):
            await token_usage.record_token_usage(
                uuid.uuid4(), "audio_gateway", "provider-model", {"input_tokens": "unknown"}
            )

    async def test_endpoint_returns_persisted_summary(self):
        row = SimpleNamespace(source="analyze", model_id="gemini-pro", input_tokens=6, output_tokens=2, total_tokens=8)
        result = mock.MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db = mock.AsyncMock()
        db.get.return_value = SimpleNamespace()
        db.execute.return_value = result
        summary = await get_token_usage(uuid.uuid4(), db)
        self.assertEqual(8, summary["total_tokens"])
        self.assertEqual("analyze", summary["by_source"][0]["source"])

    async def test_endpoint_rejects_unknown_session(self):
        db = mock.AsyncMock()
        db.get.return_value = None
        with self.assertRaises(HTTPException) as ctx:
            await get_token_usage(uuid.uuid4(), db)
        self.assertEqual(404, ctx.exception.status_code)


class TokenUsageSchemaPatchTests(unittest.TestCase):
    """The startup column patch and the alembic migration add the same
    columns, each guarded so the other having run first is a no-op."""

    def _run_patch(self, existing: set[str]) -> list[str]:
        statements: list[str] = []
        connection = mock.MagicMock()
        connection.execute.side_effect = lambda clause: statements.append(str(clause))
        inspector = mock.MagicMock()
        inspector.get_columns.return_value = [{"name": name} for name in existing]
        _add_thinking_token_column(connection, inspector, ["token_usage"])
        return statements

    def test_startup_patch_adds_the_slice_columns(self):
        statements = self._run_patch({"input_tokens", "output_tokens", "thinking_tokens", "audio_seconds"})
        self.assertEqual(3, len(statements))
        for column in ("cached_input_tokens", "audio_input_tokens", "audio_output_tokens"):
            self.assertTrue(
                any(f"ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0" in statement for statement in statements),
                column,
            )

    def test_startup_patch_is_a_no_op_once_present(self):
        statements = self._run_patch({
            "input_tokens", "output_tokens", "thinking_tokens", "audio_seconds",
            "cached_input_tokens", "audio_input_tokens", "audio_output_tokens",
        })
        self.assertEqual([], statements)

    def test_startup_patch_skips_a_missing_table(self):
        connection = mock.MagicMock()
        _add_thinking_token_column(connection, mock.MagicMock(), ["sessions"])
        connection.execute.assert_not_called()

    @staticmethod
    def _load_migration():
        # Loaded by path: the installed alembic package shadows the repo's
        # alembic/ directory on the import path.
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "025_token_usage_modality_columns.py"
        spec = importlib.util.spec_from_file_location("migration_025_token_usage", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_migration_chains_from_audio_seconds_and_guards_existing_columns(self):
        migration = self._load_migration()
        self.assertEqual("025_token_usage_modalities", migration.revision)
        self.assertEqual("024_token_usage_audio_seconds", migration.down_revision)
        inspector = mock.MagicMock()
        inspector.get_table_names.return_value = ["token_usage"]
        inspector.get_columns.return_value = [{"name": "input_tokens"}, {"name": "audio_input_tokens"}]
        with mock.patch.object(migration, "op") as op, \
             mock.patch.object(migration.sa, "inspect", return_value=inspector):
            migration.upgrade()
        added = [call.args[1].name for call in op.add_column.call_args_list]
        # The one column the startup patch already created is left alone.
        self.assertEqual(["cached_input_tokens", "audio_output_tokens"], added)
        for call in op.add_column.call_args_list:
            self.assertEqual("token_usage", call.args[0])
            self.assertFalse(call.args[1].nullable)

    def test_migration_skips_a_database_without_the_table(self):
        migration = self._load_migration()
        inspector = mock.MagicMock()
        inspector.get_table_names.return_value = []
        with mock.patch.object(migration, "op") as op, \
             mock.patch.object(migration.sa, "inspect", return_value=inspector):
            migration.upgrade()
            migration.downgrade()
        op.add_column.assert_not_called()
        op.drop_column.assert_not_called()


if __name__ == "__main__":
    unittest.main()

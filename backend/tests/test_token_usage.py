import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from app.routers.sessions import get_token_usage
from app.services import token_usage


class TokenUsageTests(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_gemini_and_openai_usage(self):
        gemini = SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=5,
            total_token_count=17,
        )
        self.assertEqual((12, 5, 0, 17), token_usage.normalize_usage(gemini))
        self.assertEqual(
            (8, 3, 0, 11),
            token_usage.normalize_usage({"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}),
        )
        self.assertEqual(
            (7, 2, 0, 9),
            token_usage.normalize_usage({"input_tokens": 7, "output_tokens": 2}),
        )

    def test_normalizes_gemini_live_response_tokens(self):
        live = SimpleNamespace(
            prompt_token_count=12,
            response_token_count=5,
            total_token_count=17,
        )
        self.assertEqual((12, 5, 0, 17), token_usage.normalize_usage(live))

    def test_captures_gemini_thinking_tokens_without_double_counting(self):
        # Gemini's reported total already includes thoughts, so the total must
        # pass through untouched: 12 + 5 + 40 would overstate it as 57.
        thinking = SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=5,
            thoughts_token_count=40,
            total_token_count=57,
        )
        self.assertEqual((12, 5, 40, 57), token_usage.normalize_usage(thinking))

    def test_synthesized_total_includes_thinking(self):
        self.assertEqual(
            (10, 4, 6, 20),
            token_usage.normalize_usage({"input_tokens": 10, "output_tokens": 4, "thoughts_token_count": 6}),
        )

    def test_captures_openai_nested_reasoning_tokens(self):
        openai = {
            "prompt_tokens": 9,
            "completion_tokens": 7,
            "total_tokens": 16,
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
        self.assertEqual((9, 7, 5, 16), token_usage.normalize_usage(openai))

    def test_thinking_only_usage_is_still_recorded(self):
        self.assertEqual(
            (0, 0, 3, 3),
            token_usage.normalize_usage({"thoughts_token_count": 3}),
        )

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

    def test_legacy_rows_without_thinking_column_summarize_as_zero(self):
        # Rows written before the column existed arrive as NULL from the driver.
        rows = [SimpleNamespace(source="analyze", model_id="gemini-pro", input_tokens=6, output_tokens=2, thinking_tokens=None, total_tokens=8)]
        summary = token_usage.summarize_usage(rows)
        self.assertEqual(0, summary["thinking_tokens"])
        self.assertEqual(8, summary["total_tokens"])

    def test_empty_summary_is_zero(self):
        self.assertEqual(
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "thinking_tokens": 0,
                "total_tokens": 0,
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


if __name__ == "__main__":
    unittest.main()

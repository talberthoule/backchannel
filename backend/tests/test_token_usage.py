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
        self.assertEqual((12, 5, 17), token_usage.normalize_usage(gemini))
        self.assertEqual(
            (8, 3, 11),
            token_usage.normalize_usage({"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}),
        )
        self.assertEqual(
            (7, 2, 9),
            token_usage.normalize_usage({"input_tokens": 7, "output_tokens": 2}),
        )

    def test_normalizes_gemini_live_response_tokens(self):
        live = SimpleNamespace(
            prompt_token_count=12,
            response_token_count=5,
            total_token_count=17,
        )
        self.assertEqual((12, 5, 17), token_usage.normalize_usage(live))

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
            SimpleNamespace(source="batch_transcriber", model_id="gemini-flash", input_tokens=10, output_tokens=2, total_tokens=12),
            SimpleNamespace(source="batch_transcriber", model_id="gemini-flash", input_tokens=5, output_tokens=1, total_tokens=6),
            SimpleNamespace(source="consolidated_analyst", model_id="gemini-pro", input_tokens=20, output_tokens=4, total_tokens=24),
        ]
        summary = token_usage.summarize_usage(rows)
        self.assertEqual(42, summary["total_tokens"])
        self.assertEqual(35, summary["input_tokens"])
        self.assertEqual(7, summary["output_tokens"])
        self.assertEqual(
            {
                (item["source"], item["model_id"]): item["total_tokens"]
                for item in summary["by_source"]
            },
            {("batch_transcriber", "gemini-flash"): 18, ("consolidated_analyst", "gemini-pro"): 24},
        )
        self.assertEqual(
            {item["model_id"]: item["total_tokens"] for item in summary["by_model"]},
            {"gemini-flash": 18, "gemini-pro": 24},
        )

    def test_empty_summary_is_zero(self):
        self.assertEqual(
            {
                "input_tokens": 0,
                "output_tokens": 0,
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

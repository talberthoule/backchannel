import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from google.genai import errors as genai_errors

from app.routers.chat import ChatIn, ChatMessage, chat

GOOGLE_MODEL = "gemini-3.5-flash"
OPENAI_MODEL = "gpt-5.4-mini"


def _db_mock():
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(
        name="Session",
        started_at=datetime(2026, 7, 1, 12, 0, 0),
        created_at=datetime(2026, 7, 1, 12, 0, 0),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    return db


def _body(model_id: str) -> ChatIn:
    return ChatIn(
        model_id=model_id,
        session_ids=[uuid4()],
        messages=[ChatMessage(role="user", content="hi")],
    )


def _openai_status_error(status: int, message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        status,
        request=request,
        json={"error": {"message": message}},
    )
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


class ChatProviderErrorTests(unittest.IsolatedAsyncioTestCase):
    async def _run_chat(self, model_id: str, exc: Exception):
        with patch("app.routers.chat.generate_text", new=AsyncMock(side_effect=exc)):
            with self.assertRaises(HTTPException) as ctx:
                await chat(_body(model_id), db=_db_mock())
        return ctx.exception

    async def test_google_spending_cap_429_maps_to_429_with_remedy(self):
        exc = genai_errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": (
                        "Your project has exceeded its monthly spending cap. "
                        "Please go to AI Studio at https://ai.studio/spend to "
                        "manage your project spend cap."
                    ),
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )
        result = await self._run_chat(GOOGLE_MODEL, exc)
        self.assertEqual(429, result.status_code)
        self.assertIn("spending cap", result.detail)
        self.assertIn("AI Studio", result.detail)
        self.assertIn("Admin", result.detail)

    async def test_google_bad_api_key_maps_to_502_with_admin_keys_hint(self):
        exc = genai_errors.ClientError(
            400,
            {
                "error": {
                    "code": 400,
                    "message": "API key not valid. Please pass a valid API key.",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )
        result = await self._run_chat(GOOGLE_MODEL, exc)
        self.assertEqual(502, result.status_code)
        self.assertIn("Gemini rejected the API key", result.detail)
        self.assertIn("Admin -> Connections", result.detail)

    async def test_google_permission_denied_maps_to_502(self):
        exc = genai_errors.ClientError(
            403,
            {
                "error": {
                    "code": 403,
                    "message": "Permission denied.",
                    "status": "PERMISSION_DENIED",
                }
            },
        )
        result = await self._run_chat(GOOGLE_MODEL, exc)
        self.assertEqual(502, result.status_code)
        self.assertIn("Admin -> Connections", result.detail)

    async def test_openai_rate_limit_maps_to_429_with_remedy(self):
        exc = _openai_status_error(429, "You exceeded your current quota.")
        result = await self._run_chat(OPENAI_MODEL, exc)
        self.assertEqual(429, result.status_code)
        self.assertIn("OpenAI quota exhausted", result.detail)
        self.assertIn("spending cap", result.detail)
        self.assertIn("Admin", result.detail)

    async def test_openai_auth_error_maps_to_502_with_admin_keys_hint(self):
        exc = _openai_status_error(401, "Incorrect API key provided.")
        result = await self._run_chat(OPENAI_MODEL, exc)
        self.assertEqual(502, result.status_code)
        self.assertIn("OpenAI rejected the API key", result.detail)
        self.assertIn("Admin -> Connections", result.detail)

    async def test_transport_error_maps_to_502_chat_failed(self):
        exc = httpx.ConnectError("connection refused")
        result = await self._run_chat(OPENAI_MODEL, exc)
        self.assertEqual(502, result.status_code)
        self.assertIn("Chat failed", result.detail)
        self.assertIn("OpenAI error", result.detail)

    async def test_programming_errors_still_propagate(self):
        # Only provider/client errors are translated; bugs must stay 500s.
        with patch(
            "app.routers.chat.generate_text",
            new=AsyncMock(side_effect=TypeError("boom")),
        ):
            with self.assertRaises(TypeError):
                await chat(_body(GOOGLE_MODEL), db=_db_mock())


if __name__ == "__main__":
    unittest.main()

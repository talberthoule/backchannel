"""Regression tests: briefing and strategic-signals calls route by registry provider.

The production bug: these paths built a google genai.Client directly and sent
whatever model id the agent was configured with to generateContent, so an
OpenAI model id (e.g. gpt-5.6-luna) produced a Gemini 404 NOT_FOUND. They now
route through app.services.llm.generate_json, which dispatches by provider.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services import briefing_synthesis, llm
from app.services.agents import strategic_signals
from app.services.briefing_synthesis import (
    BRIEF_ARBITER_SLUG,
    BRIEF_DISCOVERY_LENS_SLUG,
    BRIEF_MEETING_LENS_SLUG,
    BriefArbiterOutput,
    BriefLensOutput,
    run_session_synthesis,
)

OPENAI_MODEL = "gpt-5.6-luna"
GOOGLE_MODEL = "gemini-3.5-flash"


def _chat_response(content=None, status=200, message="You exceeded your current quota."):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    if status != 200:
        return httpx.Response(status, request=request, json={"error": {"message": message}})
    return httpx.Response(
        200,
        request=request,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        },
    )


class FakeHTTPX:
    """Stands in for llm.httpx.AsyncClient; records chat-completions posts."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def __call__(self, timeout=None):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.posts.append({"url": url, "json": json})
        return self.responses.pop(0)


class FakeGoogleJSONClient:
    """Async genai.Client stand-in returning schema-shaped parsed output."""

    def __init__(self):
        self.calls = []
        self.aio = SimpleNamespace(models=self)

    async def generate_content(self, model=None, contents=None, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if getattr(config, "response_schema", None) is BriefArbiterOutput:
            parsed = BriefArbiterOutput(arbiter_notes="settled")
        else:
            parsed = BriefLensOutput(notes="ok")
        return SimpleNamespace(parsed=parsed, text="", usage_metadata=None)


def _context():
    return SimpleNamespace(
        meeting_context_text="ctx",
        transcript_text="transcript line",
        directives_text="none",
        document_summaries="none",
        speakers_text="Speaker 1",
        insights_text="- none",
    )


def _briefing_configs(model_id):
    return {
        slug: SimpleNamespace(enabled=True, model_id=model_id, prompt="")
        for slug in (BRIEF_MEETING_LENS_SLUG, BRIEF_DISCOVERY_LENS_SLUG, BRIEF_ARBITER_SLUG)
    }


class ProviderRoutingTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(llm, "is_local_only", AsyncMock(return_value=False)))
        self.enterContext(patch.object(llm, "_resolve_key", AsyncMock(return_value="k")))
        self.enterContext(patch.object(llm, "record_token_usage", AsyncMock()))

    def _patch_openai(self, fake_httpx):
        genai_client = MagicMock()
        self.enterContext(patch.object(llm.httpx, "AsyncClient", fake_httpx))
        self.enterContext(patch.object(llm.genai, "Client", genai_client))
        return genai_client

    def _patch_google(self, fake_client):
        httpx_client = MagicMock()
        self.enterContext(patch.object(llm.genai, "Client", MagicMock(return_value=fake_client)))
        self.enterContext(patch.object(llm.httpx, "AsyncClient", httpx_client))
        return httpx_client


class LLMGenerateJsonDispatchTests(ProviderRoutingTestCase):
    async def test_openai_model_dispatches_to_openai_json_mode(self):
        fake = FakeHTTPX([_chat_response('{"notes": "ok"}')])
        genai_client = self._patch_openai(fake)

        parsed = await llm.generate_json(OPENAI_MODEL, "Prompt", BriefLensOutput)

        genai_client.assert_not_called()
        self.assertEqual("ok", parsed.notes)
        self.assertEqual(1, len(fake.posts))
        post = fake.posts[0]
        self.assertIn("/chat/completions", post["url"])
        self.assertEqual(OPENAI_MODEL, post["json"]["model"])
        self.assertEqual({"type": "json_object"}, post["json"]["response_format"])
        self.assertIn("Required JSON Contract", post["json"]["messages"][0]["content"])

    async def test_google_model_dispatches_to_native_response_schema(self):
        client = FakeGoogleJSONClient()
        httpx_client = self._patch_google(client)

        parsed = await llm.generate_json(GOOGLE_MODEL, "Prompt", BriefLensOutput)

        httpx_client.assert_not_called()
        self.assertEqual("ok", parsed.notes)
        self.assertEqual(1, len(client.calls))
        config = client.calls[0]["config"]
        self.assertEqual("application/json", config.response_mime_type)
        self.assertIs(BriefLensOutput, config.response_schema)

    async def test_openai_reply_failing_validation_gets_one_strict_reprompt(self):
        fake = FakeHTTPX([_chat_response("not json"), _chat_response('{"notes": "ok"}')])
        self._patch_openai(fake)

        parsed = await llm.generate_json(OPENAI_MODEL, "Prompt", BriefLensOutput)

        self.assertEqual("ok", parsed.notes)
        self.assertEqual(2, len(fake.posts))
        retry_messages = fake.posts[1]["json"]["messages"]
        self.assertEqual(3, len(retry_messages))
        self.assertEqual("assistant", retry_messages[1]["role"])
        self.assertIn("valid JSON", retry_messages[2]["content"])


class BriefingProviderRoutingTests(ProviderRoutingTestCase):
    def _patch_briefing(self):
        persist = AsyncMock(return_value=SimpleNamespace())
        self.enterContext(
            patch("app.services.privacy.is_local_only", new=AsyncMock(return_value=False))
        )
        self.enterContext(
            patch.object(briefing_synthesis, "_build_context", AsyncMock(return_value=_context()))
        )
        self.enterContext(patch.object(briefing_synthesis, "_persist_synthesis", persist))
        return persist

    async def test_openai_lenses_and_arbiter_use_openai_path(self):
        persist = self._patch_briefing()
        lens_json = '{"notes": "lens ok"}'
        fake = FakeHTTPX([
            _chat_response(lens_json),
            _chat_response(lens_json),
            _chat_response('{"arbiter_notes": "settled"}'),
        ])
        genai_client = self._patch_openai(fake)

        await run_session_synthesis(
            uuid.uuid4(), mode="post_call", agent_configs=_briefing_configs(OPENAI_MODEL)
        )

        genai_client.assert_not_called()
        self.assertEqual(3, len(fake.posts))
        for post in fake.posts:
            self.assertIn("/chat/completions", post["url"])
            self.assertEqual(OPENAI_MODEL, post["json"]["model"])
            self.assertEqual({"type": "json_object"}, post["json"]["response_format"])
        persist.assert_awaited_once()
        kwargs = persist.await_args.kwargs
        self.assertEqual("completed", kwargs["status"])
        self.assertEqual("settled", kwargs["arbiter_output"].arbiter_notes)

    async def test_gemini_lenses_and_arbiter_use_google_native_schema(self):
        persist = self._patch_briefing()
        client = FakeGoogleJSONClient()
        httpx_client = self._patch_google(client)

        await run_session_synthesis(
            uuid.uuid4(), mode="post_call", agent_configs=_briefing_configs(GOOGLE_MODEL)
        )

        httpx_client.assert_not_called()
        self.assertEqual(3, len(client.calls))
        schemas = [call["config"].response_schema for call in client.calls]
        self.assertEqual(2, schemas.count(BriefLensOutput))
        self.assertEqual(1, schemas.count(BriefArbiterOutput))
        for call in client.calls:
            self.assertEqual(GOOGLE_MODEL, call["model"])
            self.assertEqual("application/json", call["config"].response_mime_type)
        persist.assert_awaited_once()
        self.assertEqual("completed", persist.await_args.kwargs["status"])

    async def test_openai_provider_error_surfaces_actionable_briefing_status(self):
        persist = self._patch_briefing()
        fake = FakeHTTPX([_chat_response(status=429), _chat_response(status=429)])
        self._patch_openai(fake)

        await run_session_synthesis(
            uuid.uuid4(), mode="post_call", agent_configs=_briefing_configs(OPENAI_MODEL)
        )

        persist.assert_awaited_once()
        kwargs = persist.await_args.kwargs
        self.assertEqual("error", kwargs["status"])
        message = kwargs["error_message"]
        self.assertIn("brief_meeting_lens: OpenAI quota exhausted", message)
        self.assertIn("Admin", message)
        # The status must carry the actionable remedy, not a raw JSON blob.
        self.assertNotIn("{", message)


class StrategicSignalsProviderRoutingTests(ProviderRoutingTestCase):
    def _patch_signals(self):
        persist = AsyncMock(return_value=SimpleNamespace())
        self.enterContext(
            patch.object(strategic_signals, "is_local_only", AsyncMock(return_value=False))
        )
        self.enterContext(
            patch.object(strategic_signals, "_build_context", AsyncMock(return_value=_context()))
        )
        self.enterContext(patch.object(strategic_signals, "_persist_synthesis", persist))
        return persist

    async def test_openai_model_uses_openai_path(self):
        persist = self._patch_signals()
        fake = FakeHTTPX([_chat_response('{"arbiter_notes": "live"}')])
        genai_client = self._patch_openai(fake)
        configs = {
            "strategic_signals": SimpleNamespace(enabled=True, model_id=OPENAI_MODEL, prompt="")
        }

        await strategic_signals.run_strategic_signals_cycle(uuid.uuid4(), agent_configs=configs)

        genai_client.assert_not_called()
        self.assertEqual(1, len(fake.posts))
        post = fake.posts[0]
        self.assertIn("/chat/completions", post["url"])
        self.assertEqual(OPENAI_MODEL, post["json"]["model"])
        persist.assert_awaited_once()
        self.assertEqual("live", persist.await_args.kwargs["arbiter_output"].arbiter_notes)

    async def test_gemini_model_uses_google_native_schema(self):
        persist = self._patch_signals()
        client = FakeGoogleJSONClient()
        httpx_client = self._patch_google(client)
        configs = {
            "strategic_signals": SimpleNamespace(enabled=True, model_id=GOOGLE_MODEL, prompt="")
        }

        await strategic_signals.run_strategic_signals_cycle(uuid.uuid4(), agent_configs=configs)

        httpx_client.assert_not_called()
        self.assertEqual(1, len(client.calls))
        call = client.calls[0]
        self.assertEqual(GOOGLE_MODEL, call["model"])
        self.assertEqual("application/json", call["config"].response_mime_type)
        self.assertIs(BriefArbiterOutput, call["config"].response_schema)
        persist.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

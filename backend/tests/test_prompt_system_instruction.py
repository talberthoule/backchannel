"""generate_json carries a system instruction to both providers (ALP-285).

The instruction half of an agent prompt is the only part a cache can share.
It has to arrive as an instruction - Gemini's ``system_instruction``, an
OpenAI-shaped server's leading system message - and it has to be guarded on
the way out, because splitting a prompt must not move text past the shield's
egress boundary.
"""

import unittest
from unittest import mock

from pydantic import BaseModel

from app.services import llm


class Reply(BaseModel):
    ok: bool = True


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed = parsed
        self.text = '{"ok": true}'
        self.usage_metadata = None


class GoogleSystemInstructionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in (
            ("is_local_only", mock.AsyncMock(return_value=False)),
            ("_resolve_key", mock.AsyncMock(return_value="k")),
            ("record_token_usage", mock.AsyncMock()),
        ):
            patcher = mock.patch.object(llm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The shield's own guard reaches the database for its settings, which
        # this suite has none of. The guard's behavior is asserted below with
        # its own patch; here it just has to not dial out.
        guard = mock.patch.object(llm.pii_egress, "guard", mock.AsyncMock())
        guard.start()
        self.addCleanup(guard.stop)

    async def _call(self, **kwargs):
        seen = {}

        class FakeModels:
            async def generate_content(self, *, model, contents, config):
                seen["contents"] = contents
                seen["config"] = config
                return _FakeResponse(Reply())

        class FakeClient:
            def __init__(self, api_key=None):
                self.aio = mock.Mock(models=FakeModels())

        with mock.patch.object(llm.genai, "Client", FakeClient):
            result = await llm.generate_json(
                "gemini-3.5-flash", "## Transcript\nHello", Reply, **kwargs
            )
        return result, seen

    async def test_the_instruction_half_arrives_as_system_instruction(self):
        _, seen = await self._call(system="You are an analyst. Return JSON.")
        self.assertEqual("You are an analyst. Return JSON.", seen["config"].system_instruction)
        # And it is not also glued onto the user turn.
        self.assertNotIn("You are an analyst", seen["contents"])
        self.assertIn("Hello", seen["contents"])

    async def test_no_system_instruction_is_sent_when_there_was_nothing_to_lift(self):
        _, seen = await self._call()
        self.assertIsNone(getattr(seen["config"], "system_instruction", None))

    async def test_the_shield_guards_the_instruction_half_too(self):
        with mock.patch.object(llm.pii_egress, "guard", mock.AsyncMock()) as guard:
            await self._call(system="You are an analyst.", source="consolidated_analyst")
        self.assertEqual("You are an analyst.", guard.await_args.kwargs["system"])


class OpenAISystemMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in (
            ("is_local_only", mock.AsyncMock(return_value=False)),
            ("_resolve_key", mock.AsyncMock(return_value="k")),
        ):
            patcher = mock.patch.object(llm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        guard = mock.patch.object(llm.pii_egress, "guard", mock.AsyncMock())
        guard.start()
        self.addCleanup(guard.stop)

    async def test_the_instruction_half_leads_the_message_list(self):
        seen = {}

        async def fake_openai_json(
            model_id,
            endpoint,
            prompt,
            response_schema,
            schema_hint,
            key,
            session_id,
            source,
            reasoning_effort,
            system=None,
        ):
            seen["system"] = system
            seen["prompt"] = prompt
            return response_schema()

        with (
            mock.patch.object(llm, "_openai_json", fake_openai_json),
            mock.patch.object(
                llm,
                "resolve_endpoint",
                mock.AsyncMock(
                    return_value=llm.OpenAIEndpoint(
                        base_url="http://x/v1", model="m", api_key="k"
                    )
                ),
            ),
        ):
            await llm.generate_json(
                "gpt-5.4-mini", "## Transcript\nHello", Reply, system="Be brief."
            )

        self.assertEqual("Be brief.", seen["system"])
        self.assertIn("Hello", seen["prompt"])


if __name__ == "__main__":
    unittest.main()

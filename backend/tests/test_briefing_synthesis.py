import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import llm
from app.services.briefing_synthesis import (
    BRIEF_ARBITER_SLUG,
    BriefArbiterOutput,
    BriefLensOutput,
    agent_config_enabled,
    _response_contract,
)
from app.services.llm import parse_json_response


class FakeGoogleClient:
    """Async genai.Client stand-in that fails the schema call once."""

    def __init__(self):
        self.calls = []
        self.models = self
        self.aio = SimpleNamespace(models=self)

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise ValueError("schema rejected")
        return SimpleNamespace(
            parsed=None,
            text='{"top_outcomes":[{"title":"Outcome","summary":"Client confirmed priority."}]}',
            usage_metadata=None,
        )


class BriefingSynthesisTests(unittest.TestCase):
    def test_parse_json_response_handles_fenced_json(self):
        parsed = parse_json_response(
            """```json
{"top_outcomes":[{"title":"Outcome","summary":"Client confirmed priority."}],"arbiter_notes":"Both lenses agree."}
```""",
            BriefArbiterOutput,
        )

        self.assertEqual("Outcome", parsed.top_outcomes[0].title)
        self.assertEqual("Both lenses agree.", parsed.arbiter_notes)

    def test_agent_config_enabled_requires_present_enabled_agent(self):
        self.assertFalse(agent_config_enabled({}, BRIEF_ARBITER_SLUG))
        self.assertFalse(agent_config_enabled({BRIEF_ARBITER_SLUG: MagicMock(enabled=False)}, BRIEF_ARBITER_SLUG))
        self.assertTrue(agent_config_enabled({BRIEF_ARBITER_SLUG: MagicMock(enabled=True)}, BRIEF_ARBITER_SLUG))


class BriefingSynthesisAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for target, value in (
            ("is_local_only", AsyncMock(return_value=False)),
            ("_resolve_key", AsyncMock(return_value="k")),
        ):
            patcher = patch.object(llm, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_generate_json_google_retries_with_json_contract(self):
        client = FakeGoogleClient()
        with (
            patch.object(llm.genai, "Client", return_value=client),
            patch.object(llm, "record_token_usage", new=AsyncMock()),
        ):
            parsed = await llm.generate_json(
                "gemini-3.5-flash",
                "Base prompt",
                BriefLensOutput,
                schema_hint=_response_contract(BriefLensOutput),
            )

        self.assertEqual("Outcome", parsed.top_outcomes[0].title)
        self.assertEqual(2, len(client.calls))
        retry_prompt = client.calls[1]["contents"]
        self.assertIn("Required JSON Contract", retry_prompt)
        self.assertIn("top_outcomes", retry_prompt)

    async def test_generate_json_records_usage_for_its_source(self):
        usage = SimpleNamespace(prompt_token_count=4, candidates_token_count=1, total_token_count=5)
        response = SimpleNamespace(parsed=BriefLensOutput(), text="", usage_metadata=usage)
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content=AsyncMock(return_value=response),
        )))
        session_id = uuid.uuid4()
        with (
            patch.object(llm.genai, "Client", return_value=client),
            patch.object(llm, "record_token_usage", new=AsyncMock()) as record,
        ):
            await llm.generate_json(
                "gemini-3.5-flash",
                "Base prompt",
                BriefLensOutput,
                session_id=session_id,
                source="brief_meeting_lens",
            )
        record.assert_awaited_once_with(session_id, "brief_meeting_lens", "gemini-3.5-flash", usage)


if __name__ == "__main__":
    unittest.main()

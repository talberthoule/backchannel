import sys
import types
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.briefing_synthesis import (
    BRIEF_ARBITER_SLUG,
    BriefArbiterOutput,
    BriefLensOutput,
    agent_config_enabled,
    _generate_structured,
    _parse_structured_response,
)


class FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeContent:
    def __init__(self, parts):
        self.parts = parts


class FakePart:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self):
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise ValueError("schema rejected")
        return SimpleNamespace(
            parsed=None,
            text='{"top_outcomes":[{"title":"Outcome","summary":"Client confirmed priority."}]}',
        )


class FakeClient:
    def __init__(self):
        self.models = FakeModels()
        self.aio = SimpleNamespace(models=self.models)


class BriefingSynthesisTests(unittest.TestCase):
    def test_parse_structured_response_handles_fenced_json(self):
        parsed = _parse_structured_response(
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
    async def test_generate_structured_retries_with_json_contract(self):
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")
        fake_google.__path__ = []
        fake_genai.types = SimpleNamespace(
            GenerateContentConfig=FakeGenerateContentConfig,
            Content=FakeContent,
            Part=FakePart,
        )
        fake_google.genai = fake_genai
        client = FakeClient()

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            parsed = await _generate_structured(client, "gemini-test", "Base prompt", BriefLensOutput)

        self.assertEqual("Outcome", parsed.top_outcomes[0].title)
        self.assertEqual(2, len(client.models.calls))
        retry_prompt = client.models.calls[1]["contents"][0].parts[0].text
        self.assertIn("Required JSON Contract", retry_prompt)
        self.assertIn("top_outcomes", retry_prompt)

    async def test_generate_structured_records_usage_for_its_source(self):
        response = SimpleNamespace(
            parsed=BriefLensOutput(),
            text="",
            usage_metadata=SimpleNamespace(prompt_token_count=4, candidates_token_count=1, total_token_count=5),
        )
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content=AsyncMock(return_value=response),
        )))
        session_id = uuid.uuid4()
        with patch("app.services.briefing_synthesis.record_token_usage", new=AsyncMock()) as record:
            await _generate_structured(
                client,
                "gemini-test",
                "Base prompt",
                BriefLensOutput,
                session_id=session_id,
                source="brief_meeting_lens",
            )
        record.assert_awaited_once_with(session_id, "brief_meeting_lens", "gemini-test", response.usage_metadata)


if __name__ == "__main__":
    unittest.main()

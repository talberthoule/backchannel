import json
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.services.agents.objection_handler import ObjectionHandlerAgent, _compose_rationale


SPEAKER_ID = str(uuid.uuid4())
SPEAKERS = [{"id": SPEAKER_ID, "name": "Speaker 1"}]


def _model_item(**overrides) -> dict:
    item = {
        "item_type": "objection",
        "question": "Pricing is higher than the budgeted amount",
        "response_now": "Totally fair — can I ask what number you had budgeted so we can look at phasing?",
        "bigger_picture": "Cost justification concern; build the ROI case before the next call.",
        "source_context": "That's way more than we planned to spend this year.",
        "severity": "high",
        "speaker_id": SPEAKER_ID,
    }
    item.update(overrides)
    return item


class ComposeRationaleTests(unittest.TestCase):
    def test_includes_micro_macro_and_severity(self):
        rationale = _compose_rationale(_model_item())
        self.assertIn("Respond now:", rationale)
        self.assertIn("Bigger picture:", rationale)
        self.assertIn("(Severity: high)", rationale)

    def test_skips_missing_fields_and_bad_severity(self):
        rationale = _compose_rationale({"response_now": "Say this.", "severity": "urgent"})
        self.assertEqual(rationale, "Respond now: Say this.")


class ObjectionHandlerCycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_cycle_parses_and_tags_items(self):
        agent = ObjectionHandlerAgent()
        raw = json.dumps([_model_item()])

        with patch(
            "app.services.agents.objection_handler.generate_text",
            new=AsyncMock(return_value=raw),
        ):
            items = await agent.run_cycle("Speaker 1: too expensive", [], SPEAKERS)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["item_type"], "objection")
        self.assertEqual(item["agent_source"], "objection_handler")
        self.assertEqual(item["speaker_id"], SPEAKER_ID)
        self.assertIn("Respond now:", item["rationale"])
        self.assertIn("Bigger picture:", item["rationale"])

    async def test_unchanged_window_skips_llm_call(self):
        agent = ObjectionHandlerAgent()
        mock_generate = AsyncMock(return_value="[]")

        with patch("app.services.agents.objection_handler.generate_text", new=mock_generate):
            await agent.run_cycle("Speaker 1: same text", [], SPEAKERS)
            await agent.run_cycle("Speaker 1: same text", [], SPEAKERS)

        self.assertEqual(mock_generate.await_count, 1)

    async def test_surfaced_objections_fed_back_into_prompt(self):
        agent = ObjectionHandlerAgent()
        mock_generate = AsyncMock(side_effect=[json.dumps([_model_item()]), "[]"])

        with patch("app.services.agents.objection_handler.generate_text", new=mock_generate):
            await agent.run_cycle("Speaker 1: window one", [], SPEAKERS)
            await agent.run_cycle("Speaker 1: window two", [], SPEAKERS)

        second_prompt = mock_generate.await_args_list[1].args[1]
        self.assertIn("Pricing is higher than the budgeted amount", second_prompt)

    async def test_unknown_speaker_id_normalized_to_none(self):
        agent = ObjectionHandlerAgent()
        raw = json.dumps([_model_item(speaker_id=str(uuid.uuid4()))])

        with patch(
            "app.services.agents.objection_handler.generate_text",
            new=AsyncMock(return_value=raw),
        ):
            items = await agent.run_cycle("Speaker 1: too expensive", [], SPEAKERS)

        self.assertIsNone(items[0]["speaker_id"])

    async def test_fenced_response_and_malformed_items_filtered(self):
        agent = ObjectionHandlerAgent()
        raw = "```json\n" + json.dumps([_model_item(), {"item_type": "objection"}, "junk"]) + "\n```"

        with patch(
            "app.services.agents.objection_handler.generate_text",
            new=AsyncMock(return_value=raw),
        ):
            items = await agent.run_cycle("Speaker 1: too expensive", [], SPEAKERS)

        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()

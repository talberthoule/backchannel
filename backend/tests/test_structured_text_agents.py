import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.agents.consolidated_analyst import (
    ConsolidatedAnalystAgent,
    ConsolidatedAnalystOutput,
)
from app.services.agents.synthesizer import (
    SynthesizerOutput,
    run_synthesizer_cycle,
)


class ConsolidatedAnalystStructuredOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_blank_model_is_not_replaced(self):
        self.assertEqual("", ConsolidatedAnalystAgent(model_override="")._model)

    async def test_cycle_uses_structured_output_without_changing_insight_shape(self):
        output = ConsolidatedAnalystOutput(
            items=[
                {
                    "item_type": "observation",
                    "question": "The rollout date is at risk",
                    "rationale": "The dependency is still unresolved",
                    "source_context": "We cannot start until procurement finishes",
                }
            ]
        )
        agent = ConsolidatedAnalystAgent(
            enabled_types={"observation"},
            prompt_override="{transcript_window}",
            meeting_context_text="",
        )

        with patch(
            "app.services.agents.consolidated_analyst.generate_json",
            new=AsyncMock(return_value=output),
        ) as generate:
            items = await agent.run_cycle("Transcript", [], "", [])

        self.assertIs(ConsolidatedAnalystOutput, generate.await_args.args[2])
        self.assertEqual("observer", items[0]["agent_source"])
        self.assertEqual("The rollout date is at risk", items[0]["question"])
        self.assertEqual("insights", agent.last_outcome["kind"])
        self.assertEqual(1, agent.last_outcome["items"])

    async def test_cycle_classifies_empty_filtered_and_unparseable_replies(self):
        agent = ConsolidatedAnalystAgent(
            enabled_types={"observation"},
            prompt_override="{transcript_window}",
            meeting_context_text="",
        )

        with patch(
            "app.services.agents.consolidated_analyst.generate_json",
            new=AsyncMock(return_value=ConsolidatedAnalystOutput(items=[])),
        ):
            self.assertEqual([], await agent.run_cycle("Transcript", [], "", []))
        self.assertEqual("no_findings", agent.last_outcome["kind"])

        filtered = ConsolidatedAnalystOutput(
            items=[{"item_type": "question", "question": "A question"}]
        )
        with patch(
            "app.services.agents.consolidated_analyst.generate_json",
            new=AsyncMock(return_value=filtered),
        ):
            self.assertEqual([], await agent.run_cycle("Transcript", [], "", []))
        self.assertEqual("all_filtered", agent.last_outcome["kind"])
        self.assertIn("1 disabled type", agent.last_outcome["detail"])

        with patch(
            "app.services.agents.consolidated_analyst.generate_json",
            new=AsyncMock(
                side_effect=json.JSONDecodeError("bad reply", "not-json", 0)
            ),
        ):
            self.assertEqual([], await agent.run_cycle("Transcript", [], "", []))
        self.assertEqual("parse_failed", agent.last_outcome["kind"])

    async def test_parser_reports_each_rejected_field(self):
        agent = ConsolidatedAnalystAgent(
            enabled_types={"observation"},
            prompt_override="{transcript_window}",
            meeting_context_text="",
        )

        with self.assertLogs(
            "app.services.agents.consolidated_analyst", level="WARNING"
        ) as logs:
            items = agent._parse_response(
                [
                    "junk",
                    {"item_type": "observation"},
                    {"question": "Useful text", "item_type": "???"},
                ]
            )

        self.assertEqual([], items)
        messages = "\n".join(logs.output)
        self.assertIn("entry_type=str", messages)
        self.assertIn("question=None", messages)
        self.assertIn("item_type='???'", messages)


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _Session:
    def __init__(self, question):
        self.question = question
        # Insights, transcript entries, then the speaker roster the alias map
        # is derived from (ALP-282).
        self._results = [_Result([question]), _Result([]), _Result([])]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _model, _item_id):
        return SimpleNamespace()

    async def execute(self, _query):
        return self._results.pop(0)


class SynthesizerStructuredOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_blank_model_reaches_the_shared_llm_guard(self):
        session_id = uuid.uuid4()
        question = SimpleNamespace(
            id=uuid.uuid4(),
            item_type="observation",
            question="Existing insight",
            rationale="",
            source_context="",
            speaker=None,
            speaker_id=None,
            answered=False,
            answer_summary="",
            starred=False,
            enrichment_notes="",
            agent_source="observer",
            # The working-set split (ALP-283) reads both stamps to decide
            # whether an insight is still live; a real Question row always
            # carries them, and updated_at is nullable.
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )

        with (
            patch(
                "app.services.agents.synthesizer.async_session",
                return_value=_Session(question),
            ),
            patch(
                "app.services.agents.synthesizer.build_meeting_context_text",
                return_value="",
            ),
            patch(
                "app.services.agents.synthesizer.generate_json",
                new=AsyncMock(side_effect=ValueError("blocked")),
            ) as generate,
        ):
            await run_synthesizer_cycle(session_id, model_override="")

        self.assertEqual("", generate.await_args.args[0])

    async def test_cycle_passes_structured_operations_to_existing_applier(self):
        session_id = uuid.uuid4()
        question = SimpleNamespace(
            id=uuid.uuid4(),
            item_type="observation",
            question="Existing insight",
            rationale="",
            source_context="",
            speaker=None,
            speaker_id=None,
            answered=False,
            answer_summary="",
            starred=False,
            enrichment_notes="",
            agent_source="observer",
            # The working-set split (ALP-283) reads both stamps to decide
            # whether an insight is still live; a real Question row always
            # carries them, and updated_at is nullable.
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )
        output = SynthesizerOutput(
            items=[
                {
                    "op": "create",
                    "item_type": "observation",
                    "question": "Combined strategic signal",
                }
            ]
        )
        applied = [{"op": "create", "applied": True}]

        with (
            patch(
                "app.services.agents.synthesizer.async_session",
                return_value=_Session(question),
            ),
            patch(
                "app.services.agents.synthesizer.build_meeting_context_text",
                return_value="",
            ),
            patch(
                "app.services.agents.synthesizer.generate_json",
                new=AsyncMock(return_value=output),
            ) as generate,
            patch(
                "app.services.agents.synthesizer._apply_operations",
                new=AsyncMock(return_value=applied),
            ) as apply_operations,
        ):
            result = await run_synthesizer_cycle(session_id)

        self.assertIs(SynthesizerOutput, generate.await_args.args[2])
        self.assertEqual(applied, result)
        self.assertEqual(
            "Combined strategic signal",
            apply_operations.await_args.args[1][0]["question"],
        )


class SynthesizerExcludesAskedRowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_excludes_the_operators_asked_rows(self):
        """ALP-178: the operator's own live-chat Q&A must never reach the
        Principal Agent, which can dismiss, adjust, or elevate whatever this
        query returns. _Session (above) stubs execute() without touching the
        query, so the exclusion is checked by compiling the real select()
        statement with literal binds rather than trusting a canned result.
        """
        session_id = uuid.uuid4()
        captured_query = {}

        class _CapturingSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _model, _item_id):
                return SimpleNamespace()

            async def execute(self, query):
                captured_query["questions"] = query
                return _Result([])

        with patch(
            "app.services.agents.synthesizer.async_session",
            return_value=_CapturingSession(),
        ):
            result = await run_synthesizer_cycle(session_id)

        self.assertEqual([], result)
        compiled = str(
            captured_query["questions"].compile(compile_kwargs={"literal_binds": True})
        )
        self.assertIn("questions.item_type != 'asked'", compiled)


if __name__ == "__main__":
    unittest.main()

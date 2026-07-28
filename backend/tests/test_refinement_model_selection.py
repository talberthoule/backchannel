"""ALP-157: the features that borrow an agent row's model.

Post-import Analyze and speaker context enhancement used to pin
settings.REFINEMENT_MODEL, so Privacy First refused them with nothing the user
could change. They now read the model from the agent row that already owns that
kind of work, which makes the choice visible, selectable, and judged by
destination like every other agent model.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.config import settings
from app.services.briefing_synthesis import agent_model_id
from app.services.llm import generate_text
from app.services.privacy import LocalOnlyModeError, privacy_impact

ON_PREM_MODEL = "endpoint:lm-studio:antares-1b"


def _row(model_id: str, enabled: bool = True):
    return SimpleNamespace(slug="whatever", model_id=model_id, enabled=enabled)


class AgentModelIdTests(unittest.IsolatedAsyncioTestCase):
    async def _resolve(self, configs, slug="synthesizer", default="fallback-model"):
        with patch(
            "app.services.briefing_synthesis.load_agent_configs",
            new=AsyncMock(return_value=configs),
        ):
            return await agent_model_id(slug, default)

    async def test_returns_the_configured_row_model(self):
        self.assertEqual(
            ON_PREM_MODEL,
            await self._resolve({"synthesizer": _row(ON_PREM_MODEL)}),
        )

    async def test_missing_row_falls_back_to_the_default(self):
        self.assertEqual("fallback-model", await self._resolve({}))

    async def test_blank_model_falls_back_to_the_default(self):
        self.assertEqual(
            "fallback-model",
            await self._resolve({"synthesizer": _row("")}),
        )

    async def test_a_disabled_agent_still_supplies_its_model(self):
        """Only model_id is borrowed.

        These features are user-initiated buttons, so turning the interval
        agent off must not silently break them.
        """
        self.assertEqual(
            ON_PREM_MODEL,
            await self._resolve({"synthesizer": _row(ON_PREM_MODEL, enabled=False)}),
        )


class SpeakerContextEnhancerModelTests(unittest.IsolatedAsyncioTestCase):
    """Enhance Insights runs whatever the synthesizer row is set to."""

    async def _run_batch_with(self, resolved_model):
        from app.services.speaker_context_enhancer import run_speaker_context_batch

        question_id = uuid4()
        question = SimpleNamespace(
            id=question_id,
            item_type="observation",
            question="Assigned insight",
            rationale="Reason",
            source_context="Evidence",
            speaker_id=None,
            speaker=None,
            dismissed=False,
            answered=False,
            answer_summary="",
            enhanced=False,
            agent_source="general",
            speaker_mapping_revision_id=None,
        )
        session = SimpleNamespace(meeting_type="general", meeting_context="")
        speaker = SimpleNamespace(
            id=uuid4(),
            name="Participant",
            role="",
            speaker_type="external",
            display_name="",
            display_name_enabled=False,
        )
        load_db = SimpleNamespace(
            get=AsyncMock(return_value=session),
            execute=AsyncMock(
                side_effect=[
                    _ListResult([speaker]),
                    _ListResult([question]),
                    _ListResult([]),
                ]
            ),
        )
        apply_db = SimpleNamespace(get=AsyncMock(return_value=question))

        with (
            patch(
                "app.services.speaker_context_enhancer.async_session",
                return_value=_AsyncContext(load_db),
            ),
            patch(
                "app.services.speaker_context_enhancer.agent_model_id",
                new=AsyncMock(return_value=resolved_model),
            ) as resolve,
            patch(
                "app.services.speaker_context_enhancer.generate_text",
                new=AsyncMock(return_value="[]"),
            ) as generate,
            patch(
                "app.services.speaker_context_enhancer._apply_operations_in_db",
                new=AsyncMock(return_value=[]),
            ),
        ):
            await run_speaker_context_batch(uuid4(), [question_id], uuid4(), apply_db)

        return resolve, generate

    async def test_uses_the_synthesizer_rows_model(self):
        resolve, generate = await self._run_batch_with(ON_PREM_MODEL)

        self.assertEqual(ON_PREM_MODEL, generate.await_args.args[0])
        self.assertEqual("synthesizer", resolve.await_args.args[0])
        self.assertEqual(settings.REFINEMENT_MODEL, resolve.await_args.args[1])

    async def test_falls_back_to_the_refinement_setting(self):
        _, generate = await self._run_batch_with(settings.REFINEMENT_MODEL)

        self.assertEqual(settings.REFINEMENT_MODEL, generate.await_args.args[0])


class AnalyzeModelTests(unittest.IsolatedAsyncioTestCase):
    """Post-import Analyze runs whatever the consolidated analyst is set to."""

    async def _analyze_with(self, resolved_model):
        from app.routers.analyze import analyze_transcript

        session = SimpleNamespace(state="imported", started_at=None, ended_at=None)
        db = SimpleNamespace(
            get=AsyncMock(return_value=session),
            execute=AsyncMock(
                side_effect=[
                    _ListResult([SimpleNamespace(text="They mentioned a renewal.")]),
                    _ListResult([]),
                ]
            ),
            add=lambda obj: None,
            commit=AsyncMock(),
        )

        with (
            patch(
                "app.routers.analyze.agent_model_id",
                new=AsyncMock(return_value=resolved_model),
            ) as resolve,
            patch(
                "app.routers.analyze.generate_text",
                new=AsyncMock(return_value="[]"),
            ) as generate,
        ):
            await analyze_transcript(uuid4(), db)

        return resolve, generate

    async def test_uses_the_consolidated_analyst_rows_model(self):
        resolve, generate = await self._analyze_with(ON_PREM_MODEL)

        self.assertEqual(ON_PREM_MODEL, generate.await_args.args[0])
        self.assertEqual("consolidated_analyst", resolve.await_args.args[0])
        self.assertEqual(settings.REFINEMENT_MODEL, resolve.await_args.args[1])

    async def test_falls_back_to_the_refinement_setting(self):
        _, generate = await self._analyze_with(settings.REFINEMENT_MODEL)

        self.assertEqual(settings.REFINEMENT_MODEL, generate.await_args.args[0])


class RefusalMessageTests(unittest.IsolatedAsyncioTestCase):
    """A refusal names the model and the feature, not just that something is off."""

    def _refuse_everything(self):
        for name, value in (("is_local_only", True), ("allows_local_only", False)):
            patcher = patch(f"app.services.llm.{name}", new=AsyncMock(return_value=value))
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_message_names_the_model_and_the_calling_feature(self):
        self._refuse_everything()

        with self.assertRaises(LocalOnlyModeError) as ctx:
            await generate_text(
                "gemini-3.5-flash", "prompt", source="speaker_context_enhancer"
            )

        message = str(ctx.exception)
        self.assertIn("gemini-3.5-flash", message)
        self.assertIn("speaker_context_enhancer", message)
        self.assertIn("Assign a self-hosted model", message)
        self.assertEqual("gemini-3.5-flash", ctx.exception.model_id)
        self.assertEqual("speaker_context_enhancer", ctx.exception.agent)

    async def test_an_unlabelled_caller_still_names_the_model(self):
        self._refuse_everything()

        with self.assertRaises(LocalOnlyModeError) as ctx:
            await generate_text("gemini-3.5-flash", "prompt")

        self.assertIn("gemini-3.5-flash", str(ctx.exception))


class PrivacyImpactHonestyTests(unittest.TestCase):
    """The panel must not promise what the runtime cannot do."""

    ON_PREM_TEXT = [{"id": ON_PREM_MODEL, "name": "antares-1b"}]

    def test_document_summarization_stays_disabled_with_a_local_text_model(self):
        """It calls the Gemini Files API, so no text model can substitute."""
        disabled = [i["feature"] for i in privacy_impact(self.ON_PREM_TEXT)["disabled"]]

        self.assertIn("Document upload & summarization", disabled)

    def test_document_summarization_is_disabled_with_no_local_text_model_too(self):
        disabled = [i["feature"] for i in privacy_impact()["disabled"]]

        self.assertIn("Document upload & summarization", disabled)

    def test_it_is_listed_exactly_once(self):
        disabled = [i["feature"] for i in privacy_impact(self.ON_PREM_TEXT)["disabled"]]

        self.assertEqual(1, disabled.count("Document upload & summarization"))

    def test_insight_enhancement_is_claimed_available_once_it_can_run(self):
        impact = privacy_impact(self.ON_PREM_TEXT)
        available = " ".join(i["feature"] for i in impact["available"])
        disabled = [i["feature"] for i in impact["disabled"]]

        self.assertIn("insight enhancement", available)
        self.assertNotIn("Insight enhancement", disabled)

    def test_insight_enhancement_and_analysis_stay_disabled_without_one(self):
        disabled = [i["feature"] for i in privacy_impact()["disabled"]]

        self.assertIn("Insight enhancement", disabled)
        self.assertIn("Post-import transcript analysis", disabled)


class _ListResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _AsyncContext:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        return False


if __name__ == "__main__":
    unittest.main()

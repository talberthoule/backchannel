import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services.agents.prompts import STRATEGIC_SIGNALS_PROMPT
from app.services.agents.strategic_signals import run_strategic_signals_cycle
from app.services.briefing_synthesis import BriefArbiterOutput, BriefItem, EvidenceRef


class StrategicSignalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_uses_one_model_call_and_preserves_evidence_refs(self):
        output = BriefArbiterOutput(
            strategic_signals=[
                BriefItem(
                    title="Budget is the gating signal",
                    evidence_refs=[
                        EvidenceRef(insight_id="insight-1", type="insight")
                    ],
                )
            ]
        )
        configs = {
            "strategic_signals": SimpleNamespace(
                enabled=True,
                model_id="test-model",
                prompt=STRATEGIC_SIGNALS_PROMPT,
            )
        }
        context = SimpleNamespace(
            meeting_context_text="ctx",
            transcript_text="transcript",
            directives_text="none",
            document_summaries="none",
            speakers_text="Speaker 1",
            insights_text="- insight_id=insight-1",
        )
        persisted = SimpleNamespace(
            strategic_signals=[output.strategic_signals[0].model_dump()]
        )

        with (
            patch(
                "app.services.agents.strategic_signals.is_local_only",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.agents.strategic_signals._build_context",
                new=AsyncMock(return_value=context),
            ),
            patch(
                "app.services.agents.strategic_signals.resolve_provider_key",
                new=AsyncMock(return_value="test"),
            ),
            patch("app.services.agents.strategic_signals.genai.Client"),
            patch(
                "app.services.agents.strategic_signals._generate_structured",
                new=AsyncMock(return_value=output),
            ) as generate,
            patch(
                "app.services.agents.strategic_signals._persist_synthesis",
                new=AsyncMock(return_value=persisted),
            ) as persist,
        ):
            result = await run_strategic_signals_cycle(
                uuid4(), agent_configs=configs
            )

        generate.assert_awaited_once()
        persist.assert_awaited_once()
        self.assertEqual(
            "insight-1",
            result.strategic_signals[0]["evidence_refs"][0]["insight_id"],
        )

    async def test_cycle_skips_when_agent_is_disabled(self):
        with patch(
            "app.services.agents.strategic_signals.is_local_only",
            new=AsyncMock(return_value=False),
        ):
            result = await run_strategic_signals_cycle(
                uuid4(),
                agent_configs={
                    "strategic_signals": SimpleNamespace(enabled=False)
                },
            )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

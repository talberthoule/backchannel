"""Privacy First admits agents by where their model runs, not by provider name.

Regression cover for ALP-152: with the mode on and a self-hosted model assigned,
the briefing returned 409 and every text agent silently sat out, because four
gates tested the provider name or the flag instead of allows_local_only().
"""

import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services import briefing_synthesis as briefing_mod
from app.services import privacy as privacy_mod
from app.services.agents import strategic_signals as signals_mod
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.custom_endpoints import EndpointTarget
from app.services.privacy import LocalOnlyModeError, admitted_model_ids

ON_PREM_MODEL = "endpoint:lm-studio:qwen3-8b"
PUBLIC_MODEL = "endpoint:together:qwen3-8b"
CLOUD_MODEL = "gemini-3.5-flash"


def _target(on_prem: bool) -> EndpointTarget:
    return EndpointTarget(
        endpoint_id="lm-studio" if on_prem else "together",
        name="LM Studio" if on_prem else "Together",
        base_url="http://localhost:1234/v1" if on_prem else "https://api.together.xyz/v1",
        model="qwen3-8b",
        api_key="",
        on_prem=on_prem,
        enabled=True,
    )


def _patch_resolution(test):
    """Resolve ON_PREM_MODEL on-prem and PUBLIC_MODEL off-prem."""

    async def resolve(model_id: str):
        if model_id == ON_PREM_MODEL:
            return _target(True)
        if model_id == PUBLIC_MODEL:
            return _target(False)
        return None

    patcher = mock.patch.object(
        privacy_mod, "resolve_target_standalone", mock.AsyncMock(side_effect=resolve)
    )
    patcher.start()
    test.addCleanup(patcher.stop)


class AdmittedModelIdsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _patch_resolution(self)

    async def test_admits_self_hosted_and_bundled_refuses_cloud(self):
        admitted = await admitted_model_ids(
            [ON_PREM_MODEL, PUBLIC_MODEL, CLOUD_MODEL, "local-whisper-base"], local_only=True
        )
        self.assertEqual({ON_PREM_MODEL, "local-whisper-base"}, admitted)

    async def test_mode_off_admits_everything(self):
        admitted = await admitted_model_ids([CLOUD_MODEL, PUBLIC_MODEL], local_only=False)
        self.assertEqual({CLOUD_MODEL, PUBLIC_MODEL}, admitted)

    async def test_blank_ids_are_dropped(self):
        self.assertEqual(set(), await admitted_model_ids(["", None], local_only=True))

    async def test_each_distinct_id_is_resolved_once(self):
        await admitted_model_ids([ON_PREM_MODEL, ON_PREM_MODEL, ON_PREM_MODEL], local_only=True)
        self.assertEqual(1, privacy_mod.resolve_target_standalone.await_count)


def _build_orchestrator(configs: dict, local_only: bool, admitted: set[str] | None):
    with (
        patch("app.services.agents.orchestrator.GeminiLiveSession", return_value=AsyncMock()),
        patch("app.services.agents.orchestrator.ConsolidatedAnalystAgent", return_value=MagicMock()),
        patch("app.services.agents.orchestrator.ObjectionHandlerAgent", return_value=MagicMock()),
    ):
        return AgentOrchestrator(
            session_id=uuid4(),
            websocket=AsyncMock(),
            directives=[],
            doc_summaries="",
            active_questions=[],
            speakers=[],
            agent_configs=configs,
            local_only=local_only,
            admitted_models=admitted,
        )


def _config(model_id: str, enabled: bool = True) -> MagicMock:
    return MagicMock(
        enabled=enabled, model_id=model_id, prompt="", interval_seconds=15, sub_types="", lenses=""
    )


class OrchestratorPrivacyAdmissionTests(unittest.TestCase):
    """The 9-minute silent call: every text agent was gated off."""

    def test_self_hosted_agents_run_under_privacy_first(self):
        configs = {
            "consolidated_analyst": _config(ON_PREM_MODEL),
            "objection_handler": _config(ON_PREM_MODEL),
            "synthesizer": _config(ON_PREM_MODEL),
        }
        orch = _build_orchestrator(configs, local_only=True, admitted={ON_PREM_MODEL})
        for slug in configs:
            self.assertTrue(orch._is_enabled(slug), f"{slug} should run on a self-hosted model")
        self.assertEqual([], orch.privacy_blocked_agents)

    def test_cloud_agents_are_still_refused_and_recorded(self):
        configs = {"consolidated_analyst": _config(CLOUD_MODEL)}
        orch = _build_orchestrator(configs, local_only=True, admitted=set())
        self.assertFalse(orch._is_enabled("consolidated_analyst"))
        self.assertEqual(
            [{"agent": "consolidated_analyst", "model_id": CLOUD_MODEL}],
            orch.privacy_blocked_agents,
        )

    def test_a_public_endpoint_is_not_admitted(self):
        orch = _build_orchestrator(
            {"consolidated_analyst": _config(PUBLIC_MODEL)}, local_only=True, admitted=set()
        )
        self.assertFalse(orch._is_enabled("consolidated_analyst"))

    def test_a_disabled_agent_is_not_reported_as_privacy_blocked(self):
        orch = _build_orchestrator(
            {"consolidated_analyst": _config(CLOUD_MODEL, enabled=False)},
            local_only=True,
            admitted=set(),
        )
        self.assertFalse(orch._is_enabled("consolidated_analyst"))
        self.assertEqual([], orch.privacy_blocked_agents)

    def test_mode_off_leaves_cloud_agents_enabled(self):
        orch = _build_orchestrator(
            {"consolidated_analyst": _config(CLOUD_MODEL)}, local_only=False, admitted=None
        )
        self.assertTrue(orch._is_enabled("consolidated_analyst"))

    def test_unresolved_admission_falls_back_to_bundled_local_only(self):
        # A caller that never resolved the set must not become permissive.
        orch = _build_orchestrator(
            {"consolidated_analyst": _config(ON_PREM_MODEL)}, local_only=True, admitted=None
        )
        self.assertFalse(orch._is_enabled("consolidated_analyst"))

    def test_briefing_stage_runs_when_the_arbiter_is_self_hosted(self):
        configs = {"brief_arbiter": _config(ON_PREM_MODEL)}
        orch = _build_orchestrator(configs, local_only=True, admitted={ON_PREM_MODEL})
        self.assertTrue(orch.briefing_enabled())
        self.assertIn("call_briefing", orch.drain_stages())

    def test_briefing_stage_is_dropped_when_the_arbiter_is_cloud(self):
        orch = _build_orchestrator(
            {"brief_arbiter": _config(CLOUD_MODEL)}, local_only=True, admitted=set()
        )
        self.assertFalse(orch.briefing_enabled())
        self.assertNotIn("call_briefing", orch.drain_stages())


class BriefingSynthesisPrivacyTests(unittest.IsolatedAsyncioTestCase):
    """The reported 409: the gate never read the arbiter's assigned model."""

    def setUp(self):
        _patch_resolution(self)
        # briefing_synthesis imports the privacy helpers inside the function to
        # break a circular import, so the source module is the patch point.
        self.enterContext(
            patch.object(privacy_mod, "is_local_only", AsyncMock(return_value=True))
        )

    def _configs(self, arbiter_model: str) -> dict:
        return {
            "brief_arbiter": _config(arbiter_model),
            "brief_meeting_lens": _config(arbiter_model),
            "brief_discovery_lens": _config(arbiter_model),
        }

    async def test_self_hosted_arbiter_is_not_refused(self):
        # It must get past the privacy gate; an empty transcript then ends the
        # run with None, which proves the gate was not what stopped it.
        with patch.object(
            briefing_mod,
            "_build_context",
            AsyncMock(
                return_value=briefing_mod.SynthesisContext(
                    meeting_context_text="",
                    transcript_text="(No transcript yet)",
                    directives_text="",
                    document_summaries="",
                    speakers_text="",
                    insights_text="",
                )
            ),
        ):
            result = await briefing_mod.run_session_synthesis(
                uuid4(), agent_configs=self._configs(ON_PREM_MODEL)
            )
        self.assertIsNone(result)

    async def test_cloud_arbiter_is_refused_with_an_actionable_message(self):
        with self.assertRaises(LocalOnlyModeError) as ctx:
            await briefing_mod.run_session_synthesis(
                uuid4(), agent_configs=self._configs(CLOUD_MODEL)
            )
        self.assertEqual(CLOUD_MODEL, ctx.exception.model_id)
        self.assertEqual("brief_arbiter", ctx.exception.agent)
        message = str(ctx.exception)
        self.assertIn(CLOUD_MODEL, message)
        self.assertIn("Admin -> Agents", message)


class StrategicSignalsPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _patch_resolution(self)
        self.enterContext(
            patch.object(signals_mod, "is_local_only", AsyncMock(return_value=True))
        )

    async def test_self_hosted_signals_are_not_refused(self):
        with patch.object(
            signals_mod,
            "_build_context",
            AsyncMock(
                return_value=briefing_mod.SynthesisContext(
                    meeting_context_text="",
                    transcript_text="(No transcript yet)",
                    directives_text="",
                    document_summaries="",
                    speakers_text="",
                    insights_text="",
                )
            ),
        ):
            result = await signals_mod.run_strategic_signals_cycle(
                uuid4(), agent_configs={"strategic_signals": _config(ON_PREM_MODEL)}
            )
        self.assertIsNone(result)

    async def test_cloud_signals_are_refused(self):
        with self.assertRaises(LocalOnlyModeError):
            await signals_mod.run_strategic_signals_cycle(
                uuid4(), agent_configs={"strategic_signals": _config(CLOUD_MODEL)}
            )


class LocalOnlyModeErrorMessageTests(unittest.TestCase):
    def test_names_the_agent_and_points_at_reassignment_first(self):
        message = str(LocalOnlyModeError("call briefing synthesis", CLOUD_MODEL, "brief_arbiter"))
        self.assertIn("brief_arbiter", message)
        self.assertIn(CLOUD_MODEL, message)
        # Reassignment is the remedy that keeps the guarantee, so it leads.
        self.assertLess(message.index("Admin -> Agents"), message.index("turn off Privacy First"))

    def test_still_reads_cleanly_without_a_model(self):
        message = str(LocalOnlyModeError("document upload to the Gemini Files API"))
        self.assertIn("requires an outside API call", message)
        self.assertIn("document upload", message)


if __name__ == "__main__":
    unittest.main()

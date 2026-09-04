"""The PII Shield's audio policy: audio is held to local models while the
shield is on, cloud text models stay admitted, and the refiner is scheduled
like the other interval agents."""

import os
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.services import transcription_runtime  # noqa: E402
from app.services.agents.orchestrator import AgentOrchestrator  # noqa: E402


CLOUD_BATCH = "gemini-3.5-flash"
CLOUD_LIVE = "gemini-3.1-flash-live-preview"
LOCAL_LIVE = "local-parakeet-live"
CLOUD_TEXT = "gemini-3.5-flash"


def _shield(enabled: bool):
    # transcription_runtime reads the flag through pii.state, not the shield
    # module, so the two never import each other.
    return patch("app.services.transcription_runtime.shield_enabled", AsyncMock(return_value=enabled))


class AudioLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_shield_alone_locks_audio_and_names_itself(self):
        with mock.patch.object(transcription_runtime, "get_local_only", AsyncMock(return_value=False)), _shield(True):
            self.assertEqual(await transcription_runtime.audio_lock_reason(MagicMock()), "The PII Shield is on")
        with mock.patch.object(transcription_runtime, "get_local_only", AsyncMock(return_value=False)), _shield(False):
            self.assertEqual(await transcription_runtime.audio_lock_reason(MagicMock()), "")
        with mock.patch.object(transcription_runtime, "get_local_only", AsyncMock(return_value=True)), _shield(False):
            self.assertEqual(await transcription_runtime.audio_lock_reason(MagicMock()), "Privacy First mode is on")

    async def test_a_cloud_batch_transcriber_is_coerced_to_local_under_the_shield(self):
        gateway = MagicMock(model_id="")
        with mock.patch.object(transcription_runtime, "get_app_setting", AsyncMock(return_value=CLOUD_BATCH)), \
             mock.patch.object(transcription_runtime, "get_local_only", AsyncMock(return_value=False)), \
             mock.patch.object(transcription_runtime, "_get_audio_gateway_config", AsyncMock(return_value=gateway)), \
             _shield(True):
            config = await transcription_runtime.get_transcription_runtime_config(MagicMock())
        self.assertEqual(config.batch_model_id, transcription_runtime.DEFAULT_LOCAL_BATCH_MODEL)

    async def test_selecting_a_cloud_transcriber_or_gateway_is_refused_with_the_shield_named(self):
        with mock.patch.object(transcription_runtime, "get_local_only", AsyncMock(return_value=False)), _shield(True):
            with self.assertRaises(ValueError) as batch:
                await transcription_runtime.set_batch_transcriber_model(MagicMock(), CLOUD_BATCH)
            with self.assertRaises(ValueError) as live:
                await transcription_runtime.set_live_preview_model(MagicMock(), CLOUD_LIVE)
        self.assertIn("PII Shield", str(batch.exception))
        self.assertIn("PII Shield", str(live.exception))

    async def test_local_choices_still_pass_under_the_shield(self):
        db = MagicMock()
        db.commit = AsyncMock()
        gateway = MagicMock(model_id="")
        with mock.patch.object(transcription_runtime, "get_local_only", AsyncMock(return_value=False)), \
             mock.patch.object(transcription_runtime, "set_app_setting", AsyncMock()), \
             mock.patch.object(transcription_runtime, "get_app_setting", AsyncMock(return_value="local-whisper-base")), \
             mock.patch.object(transcription_runtime, "_get_audio_gateway_config", AsyncMock(return_value=gateway)), \
             _shield(True):
            config = await transcription_runtime.set_batch_transcriber_model(db, "local-whisper-base")
            self.assertEqual(config.batch_model_id, "local-whisper-base")
            await transcription_runtime.set_live_preview_model(db, LOCAL_LIVE)
        self.assertEqual(gateway.model_id, LOCAL_LIVE)


def _config(model_id: str, enabled: bool = True) -> MagicMock:
    return MagicMock(enabled=enabled, model_id=model_id, prompt="", interval_seconds=15, sub_types="", lenses="")


def _build(configs: dict, *, audio_local_only: bool, local_only: bool = False) -> AgentOrchestrator:
    with (
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
            admitted_models={CLOUD_TEXT, CLOUD_LIVE, LOCAL_LIVE},
            audio_local_only=audio_local_only,
        )


def _agent(orchestrator: AgentOrchestrator, slug: str) -> dict:
    return next(a for a in orchestrator.activity.snapshot()["agents"] if a["slug"] == slug)


class OrchestratorAudioPolicyTests(unittest.TestCase):
    def test_cloud_gateway_is_blocked_by_the_shield_while_cloud_text_agents_run(self):
        configs = {
            "audio_gateway": _config(CLOUD_LIVE),
            "consolidated_analyst": _config(CLOUD_TEXT),
            "transcript_refiner": _config(CLOUD_TEXT),
        }
        orchestrator = _build(configs, audio_local_only=True)
        self.assertFalse(orchestrator._is_enabled("audio_gateway"))
        self.assertTrue(orchestrator._is_enabled("consolidated_analyst"))
        self.assertTrue(orchestrator._is_enabled("transcript_refiner", False))
        gateway = _agent(orchestrator, "audio_gateway")
        self.assertEqual(gateway["state"], "blocked")
        self.assertEqual(gateway["blocked_reason"], "pii_shield")
        self.assertIn("on-device captioner", gateway["remedy"])
        self.assertNotEqual(_agent(orchestrator, "consolidated_analyst")["state"], "blocked")
        self.assertNotEqual(_agent(orchestrator, "transcript_refiner")["state"], "blocked")
        self.assertIn("transcript_refinement", orchestrator.drain_stages())
        self.assertEqual(orchestrator.drain_stages()[0], "transcript_refinement")

    def test_on_device_captioner_is_admitted_under_the_shield(self):
        orchestrator = _build({"audio_gateway": _config(LOCAL_LIVE)}, audio_local_only=True)
        self.assertTrue(orchestrator._is_enabled("audio_gateway"))

    def test_without_the_shield_a_cloud_gateway_runs_as_before(self):
        orchestrator = _build({"audio_gateway": _config(CLOUD_LIVE)}, audio_local_only=False)
        self.assertTrue(orchestrator._is_enabled("audio_gateway"))
        self.assertNotIn("transcript_refinement", orchestrator.drain_stages())

    def test_privacy_first_still_reports_its_own_reason(self):
        with patch("app.services.agents.orchestrator.provider_for", return_value="google"):
            orchestrator = _build({"audio_gateway": _config(CLOUD_LIVE)}, audio_local_only=False, local_only=True)
            orchestrator.admitted_models = set()
        # Rebuild the snapshot state through the same gate the constructor used.
        self.assertFalse(orchestrator._is_enabled("audio_gateway"))


class TranscriptRefinementDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_refinement_reports_a_complete_progress_event(self):
        orchestrator = _build(
            {"transcript_refiner": _config(CLOUD_TEXT)},
            audio_local_only=True,
        )
        orchestrator._refine_recent_transcript = AsyncMock(return_value=0)
        stages = orchestrator.drain_stages()
        events = []

        async def record_progress(event):
            events.append(event)

        result = {"stage_errors": []}
        await orchestrator._run_transcript_refinement_stage(
            stages,
            record_progress,
            2 + len(stages),
            result,
        )

        self.assertEqual(
            {
                "stage": "transcript_refinement",
                "message": "Refining the transcript wording",
                "current_step": 1,
                "total_steps": 6,
                "progress": 15,
            },
            events[0],
        )


if __name__ == "__main__":
    unittest.main()

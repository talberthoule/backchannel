"""Pre-call batch-transcription readiness.

A live call that starts without a usable batch transcriber records audio and
diarizes speech but saves zero transcript rows, and nothing in the call UI
exposes the problem. Before a call starts, resolve the effective batch model
and verify it can actually run: local models need the onnx-asr runtime,
cloud models need an available provider API key (missing and known-bad keys
both block). Privacy First mode is preserved because the runtime config
already resolves to a local model while it is enabled.
"""

import importlib.util
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.services.provider_health import get_provider_status
from app.services.transcription_runtime import get_transcription_runtime_config

_PROVIDER_LABELS = {"google": "Google", "openai": "OpenAI"}


@dataclass(frozen=True)
class TranscriptionReadiness:
    ready: bool
    model_id: str
    provider: str  # "local" or a credentials provider id such as "google"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "model_id": self.model_id,
            "provider": self.provider,
            "reason": self.reason,
        }


def local_asr_available() -> bool:
    return importlib.util.find_spec("onnx_asr") is not None


async def get_transcription_readiness(db: AsyncSession) -> TranscriptionReadiness:
    runtime = await get_transcription_runtime_config(db)
    model_id = runtime.batch_model_id
    entry = next((m for m in MODEL_REGISTRY if m["id"] == model_id), None)
    # The runtime config only returns registry models; the transcriber factory
    # routes by registry provider and sends unknown non-local ids to the
    # Gemini transcriber, which needs a Google key.
    required_key = entry.get("requires_key") if entry else "google"

    if not required_key:
        if local_asr_available():
            return TranscriptionReadiness(True, model_id, "local")
        return TranscriptionReadiness(
            False,
            model_id,
            "local",
            f"Transcription cannot run: local model '{model_id}' needs the "
            "onnx-asr runtime, which is not installed in this environment. "
            "Select a cloud transcription model in Admin -> Transcription & "
            "Audio, or reinstall the app.",
        )

    status = await get_provider_status(db, required_key)
    label = _PROVIDER_LABELS.get(required_key, required_key)
    if status["key_available"]:
        return TranscriptionReadiness(True, model_id, required_key)

    if status["configured"] or status["env_fallback"]:
        reason = (
            f"Transcription cannot run: the {label} API key failed its last "
            "connection test. Replace or re-test it in Admin -> Connections, or "
            "switch to a local transcription model."
        )
    else:
        reason = (
            f"Transcription cannot run: the selected model '{model_id}' needs "
            f"a {label} API key and none is configured. Add one in "
            "Admin -> Connections, or switch to a local transcription model."
        )
    return TranscriptionReadiness(False, model_id, required_key, reason)

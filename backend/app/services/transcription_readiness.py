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
import logging
import threading
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


# Data files onnx_asr reads through importlib.resources at transcription time.
# A frozen bundle can import the package and still lack these, because
# PyInstaller freezes .py modules but leaves package data behind unless the
# spec collects it (ALP-376).
_ASR_DATA_FILES = ("fbanks.npz",)

_asr_probe_lock = threading.Lock()
_asr_probe: tuple[bool, str] | None = None

logger = logging.getLogger(__name__)


def _probe_local_asr() -> tuple[bool, str]:
    """Actually exercise the local ASR runtime, rather than trusting a name.

    Checking only that the module resolves is what let two shipped desktop
    builds report transcription as ready and then fail every single job: in
    v0.6.1 onnx_asr could not read its own version metadata, and in v0.6.2 it
    could not read its data files. Both import fine. So import the package for
    real and resolve the resources its preprocessors open, which needs no
    model weights and no network.
    """
    if importlib.util.find_spec("onnx_asr") is None:
        return False, "the onnx-asr runtime is not installed"
    try:
        from importlib.resources import files

        import onnx_asr.preprocessors  # noqa: F401 - import is the point

        data = files(onnx_asr.preprocessors).joinpath("data")
        missing = [name for name in _ASR_DATA_FILES if not data.joinpath(name).is_file()]
        if missing:
            return False, f"the onnx-asr runtime is missing its data files ({', '.join(missing)})"
    except Exception as exc:  # noqa: BLE001 - any failure here means it cannot transcribe
        return False, f"the onnx-asr runtime failed to load ({type(exc).__name__}: {exc})"
    return True, ""


def local_asr_status() -> tuple[bool, str]:
    """(usable, reason). Probed once per process; the answer cannot change."""
    global _asr_probe
    with _asr_probe_lock:
        if _asr_probe is None:
            _asr_probe = _probe_local_asr()
            if not _asr_probe[0]:
                logger.warning("Local ASR runtime unusable: %s", _asr_probe[1])
        return _asr_probe


def local_asr_available() -> bool:
    return local_asr_status()[0]


def reset_local_asr_probe_for_tests() -> None:
    global _asr_probe
    with _asr_probe_lock:
        _asr_probe = None


async def get_transcription_readiness(db: AsyncSession) -> TranscriptionReadiness:
    runtime = await get_transcription_runtime_config(db)
    model_id = runtime.batch_model_id
    entry = next((m for m in MODEL_REGISTRY if m["id"] == model_id), None)
    if not entry or not entry.get("supports_batch_audio"):
        detail = (
            "No batch transcription model is selected."
            if not model_id
            else f"The selected batch transcription model '{model_id}' is not available."
        )
        return TranscriptionReadiness(
            False,
            model_id,
            "",
            f"Transcription cannot run: {detail} Select a batch transcription "
            "model in Admin -> Transcription & Audio.",
        )

    required_key = entry.get("requires_key")

    if not required_key:
        usable, why = local_asr_status()
        if usable:
            return TranscriptionReadiness(True, model_id, "local")
        return TranscriptionReadiness(
            False,
            model_id,
            "local",
            f"Transcription cannot run: local model '{model_id}' needs the "
            f"onnx-asr runtime, and {why} in this environment. "
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

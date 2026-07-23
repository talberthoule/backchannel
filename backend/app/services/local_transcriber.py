"""Local ONNX ASR transcriber (Whisper / Parakeet via onnx-asr).

Same surface as BatchTranscriber.transcribe_segment. Models download on first
use into DATA_DIR/asr-models and are cached per process. Inference runs in a
thread so the event loop stays free. onnx-asr auto-selects CUDA when
onnxruntime-gpu is installed, otherwise CPU.
"""

import asyncio
import logging
import threading

from app.services.audio_utils import pcm16_to_float32
from app.services.batch_transcriber import (
    TranscriptionError,
    _audio_has_speech_energy,
    filter_transcript_text,
)
from app.services.secrets import data_dir

logger = logging.getLogger(__name__)

LOCAL_MODEL_MAP = {
    "local-whisper-base": "whisper-base",
    "local-parakeet-tdt-0.6b": "nemo-parakeet-tdt-0.6b-v2",
}

_loaded: dict[str, object] = {}
_load_lock = threading.Lock()  # ponytail: global lock; per-model locks if parallel first-loads matter


def _load_model(model_id: str):
    with _load_lock:
        if model_id not in _loaded:
            import onnx_asr

            name = LOCAL_MODEL_MAP[model_id]
            models_dir = data_dir() / "asr-models"
            models_dir.mkdir(parents=True, exist_ok=True)
            path = models_dir / name
            # onnx-asr 0.11 treats any existing local_dir as offline.
            # ponytail: populated partial caches need manual deletion; add staged downloads if recovery matters.
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
            logger.info(f"Loading local ASR model {name} (downloads on first use)")
            _loaded[model_id] = onnx_asr.load_model(name, path)
        return _loaded[model_id]


def create_transcriber(model_id: str, session_id=None):
    """LocalTranscriber for local-* ids, Gemini BatchTranscriber otherwise."""
    from app.services.batch_transcriber import BatchTranscriber

    if model_id in LOCAL_MODEL_MAP:
        return LocalTranscriber(model_id)
    return BatchTranscriber(model_id=model_id, session_id=session_id)


class LocalTranscriber:
    """Transcribes PCM16 16kHz mono segments with a local ONNX model."""

    def __init__(self, model_id: str, sample_rate: int = 16000):
        if model_id not in LOCAL_MODEL_MAP:
            raise ValueError(f"Unknown local ASR model: {model_id}")
        self._model_id = model_id
        self._sample_rate = sample_rate

    async def transcribe_segment(self, pcm_bytes: bytes) -> str | None:
        if len(pcm_bytes) < self._sample_rate:  # less than 0.5s of audio
            return None
        if not _audio_has_speech_energy(pcm_bytes):
            logger.info(f"Skipping segment: below energy floor ({len(pcm_bytes)} bytes)")
            return None

        try:
            model = await asyncio.to_thread(_load_model, self._model_id)
            waveform = pcm16_to_float32(pcm_bytes)
            raw = await asyncio.to_thread(model.recognize, waveform)
        except Exception as e:
            logger.error(f"Local transcription failed ({self._model_id}): {e}")
            raise TranscriptionError(
                f"Local transcription failed ({self._model_id}): {e}"
            ) from e

        text = filter_transcript_text(raw if isinstance(raw, str) else "")
        if not text:
            return None
        logger.info(f"Transcribed locally: '{text[:80]}'")
        return text

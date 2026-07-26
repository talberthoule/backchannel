"""On-device live interim captions - no cloud (ALP-147).

Same surface as GeminiLiveSession / OpenAIRealtimeSession (connect / send_audio /
receive_responses / close), but instead of a streaming cloud session it batches
incoming mic audio into short, NON-overlapping chunks and transcribes each with a
local ONNX ASR model (Parakeet by default). Non-overlapping matters because the
frontend *appends* interim text; a re-transcribed rolling window would duplicate.

This is a pseudo-live captioner: latency is roughly one commit interval (~3s),
not the sub-second partials the cloud gateways give. It is CPU-heavy - it shares
the machine with the diarization + batch-transcription pipeline - so it is
opt-in (select the "Parakeet Live" model) and the fit test projects whether the
machine can sustain it before you turn it on.
"""

import asyncio
import logging

from app.services.local_transcriber import LocalTranscriber

logger = logging.getLogger(__name__)

_PCM_BYTES_PER_SECOND = 16000 * 2

# Registry ids that mean "caption locally", mapped to the ASR model that does it.
# Parakeet's frame-synchronous decoding suits short chunks far better than
# Whisper's 30s-window design, so it is the only live option offered.
LOCAL_LIVE_MODEL_MAP = {
    "local-parakeet-live": "local-parakeet-tdt-0.6b",
}
DEFAULT_LOCAL_LIVE_ASR = "local-parakeet-tdt-0.6b"

# Finalize a caption roughly every this many seconds of audio (mirrors the
# OpenAI Realtime manual-commit cadence).
COMMIT_SECONDS = 3.0
# Do not transcribe a chunk shorter than this - too little context.
MIN_COMMIT_SECONDS = 1.0
# Cap the pending buffer so a stalled transcriber cannot grow it without bound;
# oldest audio is dropped past this.
MAX_PENDING_SECONDS = 30
_WARMUP_TIMEOUT_SECONDS = 20


def is_local_live_model(model_id: str) -> bool:
    return model_id in LOCAL_LIVE_MODEL_MAP


class LocalLiveCaptioner:
    """Rolling-commit local transcriber presented as an audio gateway session."""

    def __init__(
        self,
        model_override: str | None = None,
        session_id=None,
        *,
        commit_seconds: float = COMMIT_SECONDS,
        make_transcriber=LocalTranscriber,
    ):
        self._asr_model_id = LOCAL_LIVE_MODEL_MAP.get(model_override or "", DEFAULT_LOCAL_LIVE_ASR)
        self._session_id = session_id
        self._commit_seconds = commit_seconds
        self._make_transcriber = make_transcriber
        self._min_commit_bytes = int(MIN_COMMIT_SECONDS * _PCM_BYTES_PER_SECOND)
        self._max_pending_bytes = int(MAX_PENDING_SECONDS * _PCM_BYTES_PER_SECOND)
        self._pending = bytearray()
        self._transcriber = None
        self._closed = False
        self.session = None  # parity with the cloud sessions' "connected" marker

    async def connect(self):
        self._transcriber = self._make_transcriber(self._asr_model_id)
        self._pending = bytearray()
        self._closed = False
        self.session = True
        # Best-effort warmup so the first caption is not slowed by model load.
        try:
            from app.services.local_fit import synthetic_speech_clip

            await asyncio.wait_for(
                self._transcriber.transcribe_segment(synthetic_speech_clip(2)),
                timeout=_WARMUP_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - warmup is optional
            logger.info("Local live captioner warmup skipped: %s", exc)
        logger.info("Local live captioner ready (%s)", self._asr_model_id)
        return self.session

    async def send_audio(self, audio_data: bytes):
        if self._closed:
            return
        # Synchronous append/trim (no await) keeps this atomic against the commit
        # loop, which drains _pending without awaiting mid-drain.
        self._pending.extend(audio_data)
        overflow = len(self._pending) - self._max_pending_bytes
        if overflow > 0:
            del self._pending[:overflow]

    async def receive_responses(self):
        """Every commit interval, transcribe the accumulated (non-overlapping)
        chunk and yield it. Single-flight: the next chunk accumulates while this
        one transcribes, so it never overlaps or runs two transcriptions at once."""
        while not self._closed:
            await asyncio.sleep(self._commit_seconds)
            if self._closed:
                break
            if len(self._pending) < self._min_commit_bytes:
                continue
            chunk = bytes(self._pending)
            self._pending = bytearray()
            try:
                text = await self._transcriber.transcribe_segment(chunk)
            except Exception as exc:  # noqa: BLE001 - one bad chunk should not end captions
                logger.warning("Local live caption chunk failed: %s", exc)
                continue
            if text and text.strip():
                yield {"type": "transcript", "data": text}

    async def close(self):
        self._closed = True
        self.session = None
        self._pending = bytearray()
        logger.info("Local live captioner closed")

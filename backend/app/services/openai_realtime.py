"""OpenAI Realtime transcription session — same surface as GeminiLiveSession.

Connects to the realtime WebSocket with intent=transcription, streams PCM16
audio (upsampled 16k -> 24k, which the API expects), and yields completed
input transcriptions as {"type": "transcript", "data": text} events.
"""

import base64
import json
import logging

import numpy as np
import websockets

from app.services.batch_transcriber import _is_hallucination
from app.services.secrets import resolve_provider_key

logger = logging.getLogger(__name__)

REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
DEFAULT_TRANSCRIBE_MODEL = "gpt-realtime-whisper"

# Registry ids are the real API transcription model ids and pass through as-is.
TRANSCRIBE_MODEL_IDS = {
    "gpt-realtime-whisper",
    "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe",
}

# Ids that may persist in agent_configs rows from earlier registry versions.
LEGACY_MODEL_ALIASES = {
    "openai-realtime": "gpt-4o-transcribe",
    "openai-realtime-mini": "gpt-4o-mini-transcribe",
    "openai-realtime-whisper": "gpt-realtime-whisper",
}


def resolve_transcribe_model(model_override: str | None) -> str:
    if model_override in TRANSCRIBE_MODEL_IDS:
        return model_override
    return LEGACY_MODEL_ALIASES.get(model_override or "", DEFAULT_TRANSCRIBE_MODEL)


def _resample_16k_to_24k(pcm_bytes: bytes) -> bytes:
    if not pcm_bytes:
        return b""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    n_out = len(samples) * 3 // 2
    x_out = np.linspace(0, len(samples) - 1, n_out)
    resampled = np.interp(x_out, np.arange(len(samples)), samples)
    return resampled.astype(np.int16).tobytes()


def _parse_event(event: dict) -> str | None:
    """Return transcript text from a completed input transcription event, else None."""
    if event.get("type") != "conversation.item.input_audio_transcription.completed":
        return None
    text = (event.get("transcript") or "").strip()
    if not text:
        return None
    if _is_hallucination(text):
        logger.info(f"Filtered hallucinated realtime transcription: '{text[:80]}'")
        return None
    return text


class OpenAIRealtimeSession:
    def __init__(self, api_key: str | None = None, model_override: str | None = None):
        self._api_key = api_key
        self._ws = None
        self._transcribe_model = resolve_transcribe_model(model_override)
        self.session = None  # parity with GeminiLiveSession's "connected" marker

    async def connect(self):
        key = self._api_key or await resolve_provider_key("openai")
        if not key:
            raise RuntimeError("No API key configured for openai; add one in Admin -> API Keys")
        self._ws = await websockets.connect(
            REALTIME_URL,
            additional_headers={"Authorization": f"Bearer {key}"},
            max_size=16 * 1024 * 1024,
        )
        await self._ws.send(json.dumps({
            "type": "transcription_session.update",
            "session": {
                "input_audio_format": "pcm16",
                "input_audio_transcription": {"model": self._transcribe_model},
                "turn_detection": {"type": "server_vad"},
            },
        }))
        self.session = self._ws
        logger.info(
            f"OpenAI Realtime transcription session connected ({self._transcribe_model})"
        )
        return self._ws

    async def send_audio(self, audio_data: bytes):
        if self._ws:
            await self._ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(_resample_16k_to_24k(audio_data)).decode(),
            }))

    async def receive_responses(self):
        if not self._ws:
            return
        async for raw in self._ws:
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if event.get("type") == "error":
                logger.warning(f"OpenAI Realtime error event: {event.get('error')}")
                continue
            text = _parse_event(event)
            if text:
                yield {"type": "transcript", "data": text}

    async def close(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning(f"Error closing OpenAI Realtime session: {e}")
            self._ws = None
            self.session = None
            logger.info("OpenAI Realtime session closed")

"""OpenAI batch speech-to-text transcribers.

Same surface as BatchTranscriber.transcribe_segment: a PCM16 16 kHz mono
segment in, filtered plain text (or None) out, TranscriptionError on real
failures. Two REST paths, one per model family:

- OpenAITranscriber: specialized speech-to-text models (gpt-4o-transcribe,
  gpt-4o-mini-transcribe). Each segment is wrapped as WAV and posted
  multipart to /v1/audio/transcriptions.
- OpenAIChatTranscriber: audio-capable chat models (gpt-audio-1.5,
  gpt-audio-mini). Each segment is wrapped as WAV, base64-encoded, and sent
  to /v1/chat/completions as an "input_audio" content part (format "wav")
  next to a verbatim-transcription prompt, mirroring the Gemini
  BatchTranscriber's generateContent approach. No "modalities"/"audio"
  request fields: the "audio" parameter is only required when audio OUTPUT
  is requested, and this path wants text only.

The API key comes from the encrypted workspace credential with the
OPENAI_API_KEY env var as fallback (resolve_provider_key), matching every
other OpenAI call site.
"""

import base64
import logging

import httpx

from app.services.audio_utils import make_wav_header
from app.services.batch_transcriber import (
    TranscriptionError,
    _audio_has_speech_energy,
    filter_transcript_text,
)
from app.services.secrets import resolve_provider_key
from app.services.token_usage import record_token_usage

logger = logging.getLogger(__name__)

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

# Registry ids served by the specialized /v1/audio/transcriptions endpoint.
# Every other audio-capable OpenAI id goes through chat completions.
OPENAI_TRANSCRIBE_MODEL_IDS = frozenset({
    "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe",
})

# Mirrors the Gemini BatchTranscriber prompt so both providers share the
# same verbatim-output convention feeding filter_transcript_text.
_TRANSCRIBE_PROMPT = (
    "Transcribe this audio exactly as spoken. "
    "Output ONLY the transcribed text, nothing else. "
    "If no speech is detected, output an empty string."
)


class OpenAITranscriber:
    """Transcribes PCM16 16kHz mono segments via OpenAI speech-to-text."""

    def __init__(self, model_id: str, sample_rate: int = 16000, session_id=None, client=None):
        self._model_id = model_id
        self._sample_rate = sample_rate
        self._session_id = session_id
        self._client = client  # injectable for tests, like BatchTranscriber

    async def _post(self, key: str, wav_data: bytes):
        kwargs = {
            "headers": {"Authorization": f"Bearer {key}"},
            "data": {"model": self._model_id, "response_format": "json"},
            "files": {"file": ("segment.wav", wav_data, "audio/wav")},
        }
        if self._client is not None:
            return await self._client.post(OPENAI_TRANSCRIPTIONS_URL, **kwargs)
        async with httpx.AsyncClient(timeout=120) as client:
            return await client.post(OPENAI_TRANSCRIPTIONS_URL, **kwargs)

    async def transcribe_segment(self, pcm_bytes: bytes) -> str | None:
        """Transcribe a single-speaker PCM16 audio segment. Returns text or None."""
        if len(pcm_bytes) < self._sample_rate:  # less than 0.5s of audio
            return None

        # Pre-check: reject segments with too little audio energy
        if not _audio_has_speech_energy(pcm_bytes):
            logger.info(f"Skipping segment: below energy floor ({len(pcm_bytes)} bytes)")
            return None

        key = await resolve_provider_key("openai")
        if not key:
            raise TranscriptionError(
                "OpenAI batch transcription needs an OpenAI API key; "
                "add one in Admin -> API Keys or switch the batch model."
            )

        logger.info(f"Transcribing segment via OpenAI ({len(pcm_bytes)} bytes)")
        wav_data = make_wav_header(pcm_bytes, self._sample_rate) + pcm_bytes

        try:
            response = await self._post(key, wav_data)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.error(f"OpenAI transcription failed ({self._model_id}): {e}")
            raise TranscriptionError(
                f"OpenAI batch transcription failed ({self._model_id}): {e}"
            ) from e

        await record_token_usage(
            self._session_id,
            "batch_transcriber",
            self._model_id,
            payload.get("usage") if isinstance(payload, dict) else None,
        )
        text = filter_transcript_text(
            (payload.get("text") or "") if isinstance(payload, dict) else ""
        )
        if not text:
            return None
        logger.info(f"Transcribed: '{text[:80]}'")
        return text


def _chat_completion_text(payload) -> str:
    """Extract the assistant text from a chat completions response payload."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else ""


class OpenAIChatTranscriber:
    """Transcribes PCM16 16kHz mono segments via an audio-capable OpenAI chat model."""

    def __init__(self, model_id: str, sample_rate: int = 16000, session_id=None, client=None):
        self._model_id = model_id
        self._sample_rate = sample_rate
        self._session_id = session_id
        self._client = client  # injectable for tests, like BatchTranscriber

    async def _post(self, key: str, wav_data: bytes):
        body = {
            "model": self._model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(wav_data).decode("ascii"),
                                "format": "wav",
                            },
                        },
                        {"type": "text", "text": _TRANSCRIBE_PROMPT},
                    ],
                }
            ],
        }
        kwargs = {
            "headers": {"Authorization": f"Bearer {key}"},
            "json": body,
        }
        if self._client is not None:
            return await self._client.post(OPENAI_CHAT_COMPLETIONS_URL, **kwargs)
        async with httpx.AsyncClient(timeout=120) as client:
            return await client.post(OPENAI_CHAT_COMPLETIONS_URL, **kwargs)

    async def transcribe_segment(self, pcm_bytes: bytes) -> str | None:
        """Transcribe a single-speaker PCM16 audio segment. Returns text or None."""
        if len(pcm_bytes) < self._sample_rate:  # less than 0.5s of audio
            return None

        # Pre-check: reject segments with too little audio energy
        if not _audio_has_speech_energy(pcm_bytes):
            logger.info(f"Skipping segment: below energy floor ({len(pcm_bytes)} bytes)")
            return None

        key = await resolve_provider_key("openai")
        if not key:
            raise TranscriptionError(
                "OpenAI batch transcription needs an OpenAI API key; "
                "add one in Admin -> API Keys or switch the batch model."
            )

        logger.info(f"Transcribing segment via OpenAI chat audio ({len(pcm_bytes)} bytes)")
        wav_data = make_wav_header(pcm_bytes, self._sample_rate) + pcm_bytes

        try:
            response = await self._post(key, wav_data)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.error(f"OpenAI chat-audio transcription failed ({self._model_id}): {e}")
            raise TranscriptionError(
                f"OpenAI batch transcription failed ({self._model_id}): {e}"
            ) from e

        await record_token_usage(
            self._session_id,
            "batch_transcriber",
            self._model_id,
            payload.get("usage") if isinstance(payload, dict) else None,
        )
        text = filter_transcript_text(_chat_completion_text(payload))
        if not text:
            return None
        logger.info(f"Transcribed: '{text[:80]}'")
        return text

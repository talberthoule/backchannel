"""Simplified transcriber — transcribes single-speaker audio segments (no diarization).

Speaker identification is handled upstream by SpeakerDiarizer.
"""

import logging
import re

import numpy as np
from google import genai
from google.genai import types

from app.config import settings
from app.services.audio_utils import make_wav_header
from app.services.secrets import resolve_provider_key

logger = logging.getLogger(__name__)

# Known hallucination patterns that speech models generate from silence/noise.
# These are well-documented across Whisper, Gemini, and other STT models.
_HALLUCINATION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^hi,?\s+i'?m\s+\w+\s+and\s+i'?m\s+\w+\s+years?\s+old",
        r"^my\s+name\s+is\s+\w+\s+and\s+i'?m\s+\w+\s+years?\s+old",
        r"^hello,?\s+i'?m\s+\w+\s+and\s+this\s+is\s+my",
        r"^thank\s+you\s+for\s+watching",
        r"^what\s+is\s+up\s+youtube(\s+and\s+welcome\s+back)?",
        r"^welcome\s+back\s+to\s+(my|the)\s+(channel|video)",
        r"^thanks\s+for\s+watching",
        r"^please\s+subscribe",
        r"^don'?t\s+forget\s+to\s+(like|subscribe)",
        r"^if\s+you\s+enjoyed?\s+this\s+video",
        r"^see\s+you\s+(in\s+the\s+)?next\s+(video|time)",
        r"^subtitles?\s+(by|created|made)",
        r"^translated\s+by",
        r"^copyright\s+\d{4}",
        r"^\[?(music|applause|laughter|silence|blank|inaudible)\]?$",
        r"^www\.",
        r"^http",
    ]
]

# Phrases that are repeated verbatim across many hallucination reports
_HALLUCINATION_EXACT: set[str] = {
    "we have joined",
    "you",
    "yeah",
    "bye",
    "bye bye",
    "bye-bye",
    "okay",
    "so",
    "hmm",
    "uh",
    "um",
}

# Minimum word count — single-word "transcriptions" from noise are almost always junk
_MIN_WORD_COUNT = 2

# Audio energy threshold — reject segments that are mostly silence
_ENERGY_FLOOR = 0.005  # RMS energy below this is likely not real speech


def _is_hallucination(text: str) -> bool:
    """Check if transcribed text matches known hallucination patterns."""
    stripped = text.strip().rstrip(".")
    if stripped.lower() in _HALLUCINATION_EXACT:
        return True
    for pattern in _HALLUCINATION_PATTERNS:
        if pattern.search(stripped):
            return True
    return False


def _audio_has_speech_energy(pcm_bytes: bytes, threshold: float = _ENERGY_FLOOR) -> bool:
    """Check if the audio segment has enough energy to contain real speech."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(samples ** 2)))
    return rms >= threshold


def filter_transcript_text(text: str) -> str | None:
    """Shared post-filters for any transcriber: hallucinations and too-short output."""
    text = (text or "").strip()
    if not text:
        return None
    if _is_hallucination(text):
        logger.info(f"Filtered hallucinated transcript: '{text}'")
        return None
    if len(text.split()) < _MIN_WORD_COUNT:
        logger.info(f"Filtered short transcript: '{text}'")
        return None
    return text


class BatchTranscriber:
    """Transcribes PCM16 audio segments into plain text via Gemini."""

    def __init__(self, sample_rate: int = 16000, model_id: str | None = None, client=None):
        self._sample_rate = sample_rate
        self._model_id = model_id or settings.BATCH_TRANSCRIBER_MODEL
        self._client = client

    async def _get_client(self):
        # Lazy so the workspace-stored key (Admin -> API Keys) is picked up.
        if self._client is None:
            key = await resolve_provider_key("google")
            self._client = genai.Client(api_key=key)
        return self._client

    async def transcribe_segment(self, pcm_bytes: bytes) -> str | None:
        """Transcribe a single-speaker PCM16 audio segment. Returns text or None."""
        if len(pcm_bytes) < self._sample_rate:  # less than 0.5s of audio
            return None

        # Pre-check: reject segments with too little audio energy
        if not _audio_has_speech_energy(pcm_bytes):
            logger.info(f"Skipping segment: below energy floor ({len(pcm_bytes)} bytes)")
            return None

        logger.info(f"Transcribing segment ({len(pcm_bytes)} bytes)")

        wav_header = make_wav_header(pcm_bytes, self._sample_rate)
        wav_data = wav_header + pcm_bytes

        try:
            client = await self._get_client()
            response = await client.aio.models.generate_content(
                model=self._model_id,
                contents=[
                    types.Content(
                        parts=[
                            types.Part(inline_data=types.Blob(
                                data=wav_data,
                                mime_type="audio/wav",
                            )),
                            types.Part(text=(
                                "Transcribe this audio exactly as spoken. "
                                "Output ONLY the transcribed text, nothing else. "
                                "If no speech is detected, output an empty string."
                            )),
                        ]
                    )
                ],
            )
            text = filter_transcript_text(response.text or "")
            if not text:
                return None
            logger.info(f"Transcribed: '{text[:80]}'")
            return text

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None

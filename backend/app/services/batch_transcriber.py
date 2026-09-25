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
from app.services.token_usage import record_token_usage
from app.services.transcription_language import prompt_language_hint

logger = logging.getLogger(__name__)

# Shared by every prompt-driven transcriber (Gemini here, OpenAI chat audio),
# so both keep the same verbatim-output convention that
# filter_transcript_text expects. prompt_language_hint appends the
# workspace language when one is set.
TRANSCRIBE_PROMPT = (
    "Transcribe this audio exactly as spoken. "
    "Output ONLY the transcribed text, nothing else. "
    "If no speech is detected, output an empty string."
)


class TranscriptionError(RuntimeError):
    """A real transcription failure (provider, model, or runtime).

    Distinct from a filtered segment: transcribers return None for audio that
    produced no usable text, and raise this when transcription itself failed.
    """


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
        # Whisper's non-English silence hallucinations are subtitle credits
        # and sign-offs from the video it was trained on (ALP-399).
        r"amara\.org",
        r"^untertitel(ung)?\s+(im\s+auftrag|der|von|durch)",
        r"^subt[i\u00ed]tulos?\s+(realizados|por|hechos|de)",
        r"^sous-titr(es|age)\s+(r\u00e9alis\u00e9s|par|fait)",
        r"^legendas?\s+(pela|por|de)",
        r"^sottotitoli\s+(creati|a\s+cura|di)",
        r"^\u3054\u8996\u8074\u3042\u308a\u304c\u3068\u3046\u3054\u3056\u3044\u307e\u3057\u305f",
        r"^\uc2dc\uccad\ud574\s*\uc8fc\uc154\uc11c\s*\uac10\uc0ac\ud569\ub2c8\ub2e4",
        r"^(\u8c22\u8c22\u89c2\u770b|\u8b1d\u8b1d\u89c0\u770b|\u8bf7\u4e0d\u541d\u70b9\u8d5e)",
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

# Chinese, Japanese, Thai, Lao, Khmer and Burmese are written without spaces
# between words, so a whole sentence splits into one "word". Text in those
# scripts is measured in characters instead; three is about two English
# words (Chinese "wo tong yi", "I agree", is three characters).
_UNSPACED_SCRIPT = re.compile(
    "[\u3040-\u30ff"  # Hiragana, Katakana
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"  # CJK ideographs
    "\u0e00-\u0e7f\u0e80-\u0eff"  # Thai, Lao
    "\u1000-\u109f\u1780-\u17ff]"  # Burmese, Khmer
)
_MIN_UNSPACED_CHARS = 3


def _too_short(text: str) -> bool:
    if len(text.split()) >= _MIN_WORD_COUNT:
        return False
    return len(_UNSPACED_SCRIPT.findall(text)) < _MIN_UNSPACED_CHARS

# Audio energy threshold — reject segments that are mostly silence
_ENERGY_FLOOR = 0.005  # RMS energy below this is likely not real speech


# A line that is one short thing said over and over ("Oh, my God. Oh, my
# God. ..." / "In In In In ..." / "A... A... A...") is a decoder loop, not
# speech. Nobody repeats a phrase this many times in one segment.
_REPEAT_MIN_TOKENS = 6
_REPEAT_MAX_DISTINCT_RATIO = 0.34
# Whisper emits bracketed non-words ("[S] [S] [S]", "[BLANK_AUDIO]") on
# noise; a line made only of those carries nothing.
_BRACKET_JUNK = re.compile(r"^\s*(?:\[[A-Za-z_ ]{1,16}\]\s*[.,]?\s*)+$")


def _is_repetitive(text: str) -> bool:
    words = [w for w in re.split(r"[\s.,!?;:\-]+", text.lower()) if w]
    if len(words) < _REPEAT_MIN_TOKENS:
        return False
    return len(set(words)) / len(words) <= _REPEAT_MAX_DISTINCT_RATIO


def _is_hallucination(text: str) -> bool:
    """Check if transcribed text matches known hallucination patterns."""
    stripped = text.strip().rstrip(".")
    if stripped.lower() in _HALLUCINATION_EXACT:
        return True
    for pattern in _HALLUCINATION_PATTERNS:
        if pattern.search(stripped):
            return True
    if _BRACKET_JUNK.match(text) or _is_repetitive(text):
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
        # Length only: transcript text is personal data and the PII Shield
        # has not seen it yet at this point.
        logger.info(f"Filtered hallucinated transcript ({len(text)} chars)")
        return None
    if _too_short(text):
        logger.info(f"Filtered short transcript ({len(text)} chars)")
        return None
    return text


class BatchTranscriber:
    """Transcribes PCM16 audio segments into plain text via Gemini."""

    def __init__(
        self,
        sample_rate: int = 16000,
        model_id: str | None = None,
        client=None,
        session_id=None,
        language: str | None = None,
    ):
        self._sample_rate = sample_rate
        self._model_id = settings.BATCH_TRANSCRIBER_MODEL if model_id is None else model_id
        self._client = client
        self._session_id = session_id
        self._prompt = TRANSCRIBE_PROMPT + prompt_language_hint(language)

    async def _get_client(self):
        # Lazy so the workspace-stored key (Admin -> Connections) is picked up.
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
                            types.Part(text=self._prompt),
                        ]
                    )
                ],
            )
            await record_token_usage(
                self._session_id,
                "batch_transcriber",
                self._model_id,
                getattr(response, "usage_metadata", None),
            )
            text = filter_transcript_text(response.text or "")
            if not text:
                return None
            logger.info(f"Transcribed segment ({len(text)} chars)")
            return text

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptionError(f"Batch transcription failed: {e}") from e

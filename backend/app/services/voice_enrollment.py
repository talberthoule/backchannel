"""Encrypted local voice profile storage and enrollment validation."""

import json
import logging

import numpy as np

from app.services.audio_utils import pcm16_to_float32
from app.services.batch_transcriber import _audio_has_speech_energy
from app.services.secrets import get_secret, set_secret
from app.services.speaker_diarizer import extract_speaker_embedding

logger = logging.getLogger(__name__)

SETTING_LOCAL_VOICE_EMBEDDING = "diarization.local_voice_embedding"
LOCAL_VOICE_PROFILE_ID = "enrolled_local_user"
MIN_ENROLLMENT_SECONDS = 4
MAX_ENROLLMENT_SECONDS = 15
# Accepted browser samples stay below Starlette's in-memory multipart spool.
MAX_ENROLLMENT_UPLOAD_BYTES = 1024 * 1024
PCM_BYTES_PER_SECOND = 16000 * 2


class VoiceEnrollmentError(ValueError):
    pass


def normalize_embedding(value: np.ndarray) -> np.ndarray:
    embedding = np.asarray(value, dtype=np.float32)
    if embedding.ndim != 1 or embedding.size == 0 or not np.isfinite(embedding).all():
        raise VoiceEnrollmentError("Speaker embedding is invalid.")
    norm = float(np.linalg.norm(embedding))
    if norm <= 0:
        raise VoiceEnrollmentError("Speaker embedding is invalid.")
    return embedding / norm


def extract_enrollment_embedding(
    pcm_bytes: bytes,
    extractor=extract_speaker_embedding,
) -> np.ndarray:
    seconds = len(pcm_bytes) / PCM_BYTES_PER_SECOND
    if seconds < MIN_ENROLLMENT_SECONDS:
        raise VoiceEnrollmentError("Voice sample must be at least 4 seconds long.")
    if seconds > MAX_ENROLLMENT_SECONDS:
        raise VoiceEnrollmentError("Voice sample must be no longer than 15 seconds.")
    if not _audio_has_speech_energy(pcm_bytes):
        raise VoiceEnrollmentError("Voice sample must contain audible speech.")
    return normalize_embedding(extractor(pcm16_to_float32(pcm_bytes), 16000))


async def load_local_voice_embedding(db) -> np.ndarray | None:
    raw = await get_secret(db, SETTING_LOCAL_VOICE_EMBEDDING)
    if not raw:
        return None
    try:
        return normalize_embedding(np.asarray(json.loads(raw), dtype=np.float32))
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Ignoring invalid stored local voice profile")
        return None


async def save_local_voice_embedding(db, embedding: np.ndarray) -> None:
    normalized = normalize_embedding(embedding)
    await set_secret(
        db,
        SETTING_LOCAL_VOICE_EMBEDDING,
        json.dumps(normalized.tolist()),
    )


async def clear_local_voice_embedding(db) -> None:
    await set_secret(db, SETTING_LOCAL_VOICE_EMBEDDING, "")

import re

_MIN_NEW_SPEAKER_SECONDS = 4.0
_MIN_NEW_SPEAKER_WORDS = 10


def should_defer_new_speaker_segment(
    pcm_bytes: bytes,
    text: str,
    sample_rate: int = 16000,
) -> bool:
    """Delay one-off short fragments from creating durable speaker rows."""
    duration_seconds = len(pcm_bytes) / float(sample_rate * 2)
    word_count = len(re.findall(r"[A-Za-z0-9']+", text))
    return duration_seconds < _MIN_NEW_SPEAKER_SECONDS or word_count < _MIN_NEW_SPEAKER_WORDS

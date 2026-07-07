import asyncio
import logging
import re
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Filler words/phrases to strip
FILLER_PATTERNS = [
    r'\b(um+|uh+|er+|ah+|hm+|hmm+|mm+|mhm+)\b',
    r'\b(you know|i mean|like,?\s+like|sort of|kind of|basically|actually|literally)\b',
    r'\b(right\??\s*right|so\s+so|yeah\s+yeah|ok\s+so)\b',
]
FILLER_RE = re.compile('|'.join(FILLER_PATTERNS), re.IGNORECASE)

# Repeated words (stuttering)
STUTTER_RE = re.compile(r'\b(\w+)\s+\1\b', re.IGNORECASE)

# Multiple spaces / leading/trailing cleanup
MULTI_SPACE_RE = re.compile(r'\s{2,}')


def clean_transcript_text(text: str) -> str:
    """Remove filler words, stutters, and clean up whitespace."""
    # Remove fillers
    cleaned = FILLER_RE.sub('', text)
    # Remove stuttered words (keep one instance)
    cleaned = STUTTER_RE.sub(r'\1', cleaned)
    # Clean up punctuation artifacts
    cleaned = re.sub(r'\s+([.,!?])', r'\1', cleaned)  # space before punctuation
    cleaned = re.sub(r'([.,!?])\1+', r'\1', cleaned)  # repeated punctuation
    cleaned = re.sub(r',\s*,', ',', cleaned)  # double commas
    cleaned = MULTI_SPACE_RE.sub(' ', cleaned)
    cleaned = cleaned.strip()
    # Capitalize first letter
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


class TranscriptBuffer:
    """Buffers rapid-fire transcript fragments and flushes them as coherent utterances.

    Fragments accumulate until either:
    - A sentence boundary is detected (. ? !)
    - A silence gap occurs (no new fragment for `flush_delay` seconds)
    - The buffer exceeds a max length
    """

    def __init__(
        self,
        on_flush: Callable[[str], Awaitable[None]],
        flush_delay: float = 2.0,
        max_buffer_chars: int = 500,
    ):
        self._buffer = ""
        self._on_flush = on_flush
        self._flush_delay = flush_delay
        self._max_buffer_chars = max_buffer_chars
        self._flush_timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def add(self, text: str):
        """Add a transcript fragment to the buffer."""
        if not text or not text.strip():
            return

        async with self._lock:
            # Add space between fragments if needed
            if self._buffer and not self._buffer.endswith(' ') and not text.startswith(' '):
                self._buffer += ' '
            self._buffer += text.strip()

            # Cancel existing timer
            if self._flush_timer and not self._flush_timer.done():
                self._flush_timer.cancel()

            # Check for sentence boundaries
            if self._has_sentence_boundary() or len(self._buffer) >= self._max_buffer_chars:
                await self._flush()
            else:
                # Set timer for silence-based flush
                self._flush_timer = asyncio.create_task(self._delayed_flush())

    def _has_sentence_boundary(self) -> bool:
        """Check if the buffer ends with a sentence boundary."""
        stripped = self._buffer.rstrip()
        return bool(stripped) and stripped[-1] in '.?!'

    async def _delayed_flush(self):
        """Wait for silence gap, then flush."""
        try:
            await asyncio.sleep(self._flush_delay)
            async with self._lock:
                await self._flush()
        except asyncio.CancelledError:
            pass

    async def _flush(self):
        """Process and emit the buffered text."""
        if not self._buffer.strip():
            self._buffer = ""
            return

        raw = self._buffer.strip()
        self._buffer = ""

        cleaned = clean_transcript_text(raw)
        if cleaned and len(cleaned) > 1:  # Skip single-character artifacts
            logger.debug(f"Transcript flush: '{raw}' -> '{cleaned}'")
            await self._on_flush(cleaned)

    async def flush_remaining(self):
        """Force flush any remaining text (call on session end)."""
        if self._flush_timer and not self._flush_timer.done():
            self._flush_timer.cancel()
        async with self._lock:
            await self._flush()

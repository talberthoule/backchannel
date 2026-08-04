"""Shared state for text-based agents.

TranscriptBuffer: in-memory ring buffer (~5 min of transcript text), thread-safe.
"""

import asyncio
import time
from collections import deque

from app.services.agents.speaker_context import format_transcript_segment

# The segment cap, not get_window's max_age_seconds, is what actually bounds
# every agent's transcript window. The "~10s per segment" assumption behind this
# number does not hold in practice: a measured meeting averaged 4.87s between
# entries, so 30 segments was about 144s of speech, not the 300s the age budget
# advertises. Raising this roughly doubles the consolidated analyst's and
# strategic signals' transcript cost with no other code change (ALP-287).
_DEFAULT_BUFFER_SIZE = 30


class TranscriptBuffer:
    """Thread-safe ring buffer of recent transcript segments."""

    def __init__(self, max_segments: int = _DEFAULT_BUFFER_SIZE):
        self._segments: deque[dict] = deque(maxlen=max_segments)
        self._lock = asyncio.Lock()

    async def add(
        self,
        text: str,
        speaker: str | None = None,
        speaker_id: str | None = None,
        speaker_type: str | None = None,
    ):
        async with self._lock:
            self._segments.append({
                "text": text,
                "speaker": speaker or "Unknown",
                "speaker_id": speaker_id,
                "speaker_type": speaker_type,
                "ts": time.time(),
            })

    async def get_window(self, max_age_seconds: float = 300.0) -> str:
        """Return formatted transcript window for the last `max_age_seconds`.

        The effective window is the tighter of this age budget and the buffer's
        segment cap; at normal speech rates the cap binds first. See
        _DEFAULT_BUFFER_SIZE.
        """
        async with self._lock:
            cutoff = time.time() - max_age_seconds
            lines = []
            for seg in self._segments:
                if seg["ts"] >= cutoff:
                    lines.append(format_transcript_segment(
                        seg["text"],
                        seg["speaker"],
                        speaker_id=seg.get("speaker_id"),
                        speaker_type=seg.get("speaker_type"),
                    ))
            return "\n".join(lines) if lines else "(No recent transcript)"

    async def clear(self):
        async with self._lock:
            self._segments.clear()

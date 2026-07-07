"""Mixes mic and system-audio PCM16 tracks into one stream for the live gateway.

Sums frame-aligned int16 samples with clamping. If the other track has been
idle longer than the idle window, buffered frames flush solo so a mic-only
call (or a stopped screen share) keeps flowing.
"""

from time import monotonic

import numpy as np

FRAME_BYTES = 3200  # 1600 samples (~100ms) of PCM16 16kHz mono
IDLE_FLUSH_SECONDS = 0.2


class TrackMixer:
    def __init__(self, now=monotonic):
        self._buffers = {0: bytearray(), 1: bytearray()}
        self._last_seen = {0: 0.0, 1: 0.0}
        self._now = now

    def add(self, track: int, pcm: bytes) -> bytes | None:
        t = self._now()
        self._last_seen[track] = t
        self._buffers[track] += pcm

        out = bytearray()
        while len(self._buffers[0]) >= FRAME_BYTES and len(self._buffers[1]) >= FRAME_BYTES:
            a = np.frombuffer(bytes(self._buffers[0][:FRAME_BYTES]), dtype=np.int16).astype(np.int32)
            b = np.frombuffer(bytes(self._buffers[1][:FRAME_BYTES]), dtype=np.int16).astype(np.int32)
            out += np.clip(a + b, -32768, 32767).astype(np.int16).tobytes()
            del self._buffers[0][:FRAME_BYTES]
            del self._buffers[1][:FRAME_BYTES]

        other = 1 - track
        if not self._buffers[other] and t - self._last_seen[other] > IDLE_FLUSH_SECONDS:
            while len(self._buffers[track]) >= FRAME_BYTES:
                out += bytes(self._buffers[track][:FRAME_BYTES])
                del self._buffers[track][:FRAME_BYTES]

        return bytes(out) if out else None

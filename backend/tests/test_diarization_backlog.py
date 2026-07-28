"""The diarization backlog is bounded (ALP-153).

A diarizer slower than realtime used to grow the queue without limit until the
container was OOM-killed mid-call, which read to the user as a dead app: no
transcript, no insights, and an End Call button that did nothing.
"""

import asyncio
import unittest
from collections import deque

from app.ws.audio_runtime import (
    MAX_DIARIZATION_BACKLOG_BYTES,
    _PCM_BYTES_PER_SECOND,
    _QueuedAudioFrame,
    _shed_diarization_backlog,
)


def _frame(seconds: float = 1.0, track: int = 0, at: float = 0.0) -> _QueuedAudioFrame:
    # enqueued_at distinguishes otherwise-identical frames: _QueuedAudioFrame is
    # a dataclass, so equal payloads compare equal and membership assertions
    # would match the wrong frame.
    return _QueuedAudioFrame(
        track=track,
        pcm_bytes=b"\x00" * int(seconds * _PCM_BYTES_PER_SECOND),
        split_track_established=False,
        enqueued_at=at,
    )


def _fill(queue, pending, frames):
    buffered = 0
    for frame in frames:
        queue.put_nowait(frame)
        pending.append(0.0)
        buffered += len(frame.pcm_bytes)
    return buffered


class ShedDiarizationBacklogTests(unittest.TestCase):
    def setUp(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.pending: deque[float] = deque()

    def test_under_the_cap_nothing_is_dropped(self):
        buffered = _fill(self.queue, self.pending, [_frame(1.0) for _ in range(5)])
        result, dropped = _shed_diarization_backlog(self.queue, self.pending, buffered)
        self.assertEqual(0, dropped)
        self.assertEqual(buffered, result)
        self.assertEqual(5, self.queue.qsize())

    def test_the_backlog_cannot_grow_without_bound(self):
        # Simulate a diarizer that never consumes: 10 minutes of dual-track
        # audio arriving with nothing draining it.
        buffered = 0
        for _ in range(600):
            frame = _frame(1.0)
            self.queue.put_nowait(frame)
            self.pending.append(0.0)
            buffered += len(frame.pcm_bytes)
            buffered, _ = _shed_diarization_backlog(self.queue, self.pending, buffered)
        self.assertLessEqual(buffered, MAX_DIARIZATION_BACKLOG_BYTES)
        # Roughly 2 MB held, not the ~19 MB that 600 s of audio would be.
        self.assertLessEqual(self.queue.qsize() * _PCM_BYTES_PER_SECOND, MAX_DIARIZATION_BACKLOG_BYTES)

    def test_the_oldest_audio_is_dropped_first(self):
        # Recency is what live analysis needs, and shedding the front is what
        # lets a lagging diarizer catch back up.
        frames = [_frame(1.0, at=float(i)) for i in range(5)]
        buffered = _fill(self.queue, self.pending, frames)
        result, dropped = _shed_diarization_backlog(
            self.queue, self.pending, buffered, limit_bytes=3 * _PCM_BYTES_PER_SECOND
        )
        self.assertEqual(2, dropped)
        self.assertEqual(3 * _PCM_BYTES_PER_SECOND, result)
        remaining = []
        while not self.queue.empty():
            remaining.append(self.queue.get_nowait())
        self.assertEqual([2.0, 3.0, 4.0], [f.enqueued_at for f in remaining])

    def test_pending_ages_stay_in_step_with_the_queue(self):
        # backlog= in the ingress log reads len(pending), so a drift here would
        # misreport the backlog for the rest of the call.
        _fill(self.queue, self.pending, [_frame(1.0) for _ in range(40)])
        _, dropped = _shed_diarization_backlog(
            self.queue, self.pending, MAX_DIARIZATION_BACKLOG_BYTES * 3
        )
        self.assertEqual(self.queue.qsize(), len(self.pending))
        self.assertGreater(dropped, 0)

    def test_the_shutdown_sentinel_is_never_discarded(self):
        # Dropping None would leave the worker awaiting a stop that never comes.
        self.queue.put_nowait(None)
        result, dropped = _shed_diarization_backlog(
            self.queue, self.pending, MAX_DIARIZATION_BACKLOG_BYTES * 2
        )
        self.assertEqual(0, dropped)
        self.assertEqual(1, self.queue.qsize())
        self.assertIsNone(self.queue.get_nowait())

    def test_an_empty_queue_reports_nothing_buffered(self):
        # The worker can drain frames while we shed; accounting must not go
        # negative or claim memory that is no longer held.
        result, dropped = _shed_diarization_backlog(
            self.queue, self.pending, MAX_DIARIZATION_BACKLOG_BYTES * 5
        )
        self.assertEqual(0, result)
        self.assertEqual(0, dropped)

    def test_the_cap_is_a_sane_fraction_of_process_memory(self):
        # 30 s of dual-track PCM. If this ever grows past a few MB the bound
        # stops protecting the thing it exists to protect.
        self.assertLessEqual(MAX_DIARIZATION_BACKLOG_BYTES, 4 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()

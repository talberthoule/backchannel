"""Track one is finalized where the share ends, not at End Call (ALP-103).

The re-acceptance stopped new system ingress correctly, but the buffered tail
sat in the system diarizer until End Call and surfaced there as a brand-new
remote speaker almost four minutes after sharing had stopped. The audio was
real and predated the stop; the timing was the lie.
"""

import asyncio
import unittest
from types import SimpleNamespace

from app.ws.audio_messages import _handle_text_message
from app.ws.audio_runtime import _QueuedAudioFrame, _run_diarization_worker


class _Diarizer:
    """Stands in for the streaming diarizer's buffer/flush/reset contract."""

    def __init__(self, tail=(), name="sys"):
        self.name = name
        self._tail = list(tail)
        self.fed = []
        self.reset_calls = 0

    def feed_audio(self, pcm_bytes):
        self.fed.append(pcm_bytes)
        return []

    def flush_segments(self):
        # Real flush_segments drops a sub-minimum tail itself and returns [].
        segments, self._tail = self._tail, []
        return segments

    def reset(self):
        self.reset_calls += 1
        self._tail = []


def _segment(speaker_id, pcm=b"\x01\x02"):
    return SimpleNamespace(speaker_id=speaker_id, pcm_bytes=pcm)


def _frame(track=1, pcm=b"\x00\x00", flush=False):
    return _QueuedAudioFrame(
        track=track,
        pcm_bytes=pcm,
        split_track_established=True,
        enqueued_at=0.0,
        flush=flush,
    )


async def _drive(queue_items, system_diarizer):
    queue: asyncio.Queue = asyncio.Queue()
    for item in queue_items:
        queue.put_nowait(item)
    queue.put_nowait(None)

    emitted = []
    done = []

    async def on_segment(item, segment):
        emitted.append((item.track, segment.speaker_id))

    async def on_error(item, exc):  # pragma: no cover - not exercised
        raise exc

    return (
        await _run_diarization_worker(
            queue,
            _Diarizer(name="mic"),
            lambda: system_diarizer,
            on_segment,
            on_error,
            done.append,
        ),
        emitted,
        done,
    )


class SystemTrackFlushTests(unittest.IsolatedAsyncioTestCase):
    async def test_deactivation_finalizes_the_pending_buffer_immediately(self):
        system = _Diarizer(tail=[_segment("auto_2")])

        _, emitted, done = await _drive(
            [_frame(pcm=b"\x00" * 320), _frame(flush=True)],
            system,
        )

        # The tail is attributed at the stop boundary, on its own track.
        self.assertEqual([(1, "auto_2")], emitted)
        # And the diarizer is left empty, so End Call has nothing to surface.
        self.assertEqual(1, system.reset_calls)
        self.assertEqual([], system.flush_segments())
        # Backlog accounting still sees every item, sentinel included.
        self.assertEqual(2, len(done))

    async def test_end_call_after_the_flush_produces_nothing_for_track_one(self):
        """The actual acceptance failure: no late speaker from a stopped track."""
        system = _Diarizer(tail=[_segment("auto_2")])

        await _drive([_frame(pcm=bytes(320)), _frame(flush=True)], system)
        # What _finalize_call does at End Call.
        self.assertEqual([], system.flush_segments())

    async def test_a_sub_minimum_tail_yields_no_segment(self):
        """flush_segments drops it, so nothing is attributed at all."""
        system = _Diarizer(tail=[])

        _, emitted, _ = await _drive(
            [_frame(pcm=bytes(320)), _frame(flush=True)], system
        )

        self.assertEqual([], emitted)
        self.assertEqual(1, system.reset_calls)

    async def test_a_flush_never_builds_a_diarizer_for_a_track_that_never_ran(self):
        created = []

        def create():
            created.append(True)
            return _Diarizer()

        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait(_frame(flush=True))
        queue.put_nowait(None)

        async def on_segment(item, segment):  # pragma: no cover - not exercised
            raise AssertionError("no segments expected")

        async def on_error(item, exc):  # pragma: no cover - not exercised
            raise exc

        await _run_diarization_worker(
            queue, _Diarizer(name="mic"), create, on_segment, on_error, None
        )

        self.assertEqual([], created)

    async def test_mic_frames_are_untouched_by_a_system_flush(self):
        system = _Diarizer(tail=[_segment("auto_2")])
        system_pcm = b"\x02" * 320
        queue_items = [
            _frame(track=0, pcm=b"\x01" * 320),
            _frame(pcm=system_pcm),
            _frame(flush=True),
        ]

        _, emitted, _ = await _drive(queue_items, system)

        self.assertEqual([(1, "auto_2")], emitted)
        # Only the system frame reached the system diarizer: the mic frame went
        # to the mic one, and the flush fed no audio at all.
        self.assertEqual([system_pcm], system.fed)


class TrackStateDeactivationTests(unittest.IsolatedAsyncioTestCase):
    async def _handle(self, payload, flushed):
        state = SimpleNamespace(
            split_track_established=True, stopped=False, stop_drain_mode=None
        )
        await _handle_text_message(
            payload,
            "session",
            SimpleNamespace(),
            state,
            lambda data: "full",
            on_system_track_stopped=lambda: flushed.append(True) or asyncio.sleep(0),
        )
        return state

    async def test_system_deactivation_triggers_the_flush(self):
        flushed: list = []

        state = await self._handle(
            '{"type": "track_state", "track": 1, "active": false}', flushed
        )

        self.assertEqual([True], flushed)
        # The topology fact survives the stop; only capture ended (ALP-103).
        self.assertTrue(state.split_track_established)

    async def test_activation_does_not_flush(self):
        flushed: list = []

        await self._handle(
            '{"type": "track_state", "track": 1, "active": true}', flushed
        )

        self.assertEqual([], flushed)

    async def test_a_mic_track_state_does_not_flush_the_system_track(self):
        flushed: list = []

        await self._handle(
            '{"type": "track_state", "track": 0, "active": false}', flushed
        )

        self.assertEqual([], flushed)


if __name__ == "__main__":
    unittest.main()

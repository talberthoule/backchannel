import asyncio
import unittest

from app.services.ordered_transcription import OrderedTranscriptionQueue


class OrderedTranscriptionQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_emits_in_input_order_when_transcriptions_finish_out_of_order(self):
        delays = {
            b"first": 0.03,
            b"second": 0.0,
            b"third": 0.01,
        }
        emitted = []

        async def transcribe(pcm_bytes: bytes):
            await asyncio.sleep(delays[pcm_bytes])
            return pcm_bytes.decode()

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            emitted.append((speaker_auto_id, text))

        queue = OrderedTranscriptionQueue(transcribe=transcribe, emit=emit, max_concurrency=3)
        queue.add("auto_1", b"first")
        queue.add("auto_2", b"second")
        queue.add("auto_3", b"third")
        await queue.drain()

        self.assertEqual(
            [("auto_1", "first"), ("auto_2", "second"), ("auto_3", "third")],
            emitted,
        )

    async def test_skips_empty_transcripts_without_blocking_later_segments(self):
        emitted = []

        async def transcribe(pcm_bytes: bytes):
            return None if pcm_bytes == b"empty" else pcm_bytes.decode()

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            emitted.append(text)

        queue = OrderedTranscriptionQueue(transcribe=transcribe, emit=emit)
        queue.add("auto_1", b"empty")
        queue.add("auto_1", b"kept")
        await queue.drain()

        self.assertEqual(["kept"], emitted)

    async def test_transcription_timeout_unblocks_later_segments(self):
        emitted = []

        async def transcribe(pcm_bytes: bytes):
            if pcm_bytes == b"stuck":
                await asyncio.sleep(0.2)
                return "stuck"
            return pcm_bytes.decode()

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            emitted.append(text)

        queue = OrderedTranscriptionQueue(
            transcribe=transcribe,
            emit=emit,
            max_concurrency=2,
            transcribe_timeout_seconds=0.01,
        )
        queue.add("auto_1", b"stuck")
        queue.add("auto_1", b"kept")
        await queue.drain()

        self.assertEqual(["kept"], emitted)

    async def test_transcribe_errors_count_as_failures_and_notify(self):
        failures = []

        async def transcribe(pcm_bytes: bytes):
            if pcm_bytes == b"boom":
                raise RuntimeError("provider rejected the request")
            return pcm_bytes.decode()

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            pass

        async def on_failure(failed_count: int, kind: str):
            failures.append((failed_count, kind))

        queue = OrderedTranscriptionQueue(
            transcribe=transcribe, emit=emit, on_failure=on_failure
        )
        queue.add("auto_1", b"boom")
        queue.add("auto_1", b"ok")
        await queue.drain()

        self.assertEqual({"jobs": 2, "emitted": 1, "failed": 1}, queue.stats)
        self.assertEqual([(1, "transcribe")], failures)

    async def test_timeout_counts_as_failure(self):
        async def transcribe(pcm_bytes: bytes):
            await asyncio.sleep(0.2)
            return "late"

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            pass

        queue = OrderedTranscriptionQueue(
            transcribe=transcribe,
            emit=emit,
            transcribe_timeout_seconds=0.01,
        )
        queue.add("auto_1", b"stuck")
        await queue.drain()

        self.assertEqual({"jobs": 1, "emitted": 0, "failed": 1}, queue.stats)

    async def test_filtered_segment_is_not_a_failure(self):
        async def transcribe(pcm_bytes: bytes):
            return None

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            pass

        queue = OrderedTranscriptionQueue(transcribe=transcribe, emit=emit)
        queue.add("auto_1", b"quiet")
        await queue.drain()

        self.assertEqual({"jobs": 1, "emitted": 0, "failed": 0}, queue.stats)

    async def test_emit_errors_count_as_failures(self):
        failures = []

        async def transcribe(pcm_bytes: bytes):
            return pcm_bytes.decode()

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            raise RuntimeError("db unavailable")

        async def on_failure(failed_count: int, kind: str):
            failures.append((failed_count, kind))

        queue = OrderedTranscriptionQueue(
            transcribe=transcribe, emit=emit, on_failure=on_failure
        )
        queue.add("auto_1", b"text")
        await queue.drain()

        self.assertEqual({"jobs": 1, "emitted": 0, "failed": 1}, queue.stats)
        self.assertEqual([(1, "emit")], failures)

    async def test_failure_callback_errors_do_not_break_the_queue(self):
        emitted = []

        async def transcribe(pcm_bytes: bytes):
            if pcm_bytes == b"boom":
                raise RuntimeError("nope")
            return pcm_bytes.decode()

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            emitted.append(text)

        async def on_failure(failed_count: int, kind: str):
            raise RuntimeError("callback crashed")

        queue = OrderedTranscriptionQueue(
            transcribe=transcribe, emit=emit, on_failure=on_failure
        )
        queue.add("auto_1", b"boom")
        queue.add("auto_1", b"kept")
        await queue.drain()

        self.assertEqual(["kept"], emitted)
        self.assertEqual(1, queue.stats["failed"])


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

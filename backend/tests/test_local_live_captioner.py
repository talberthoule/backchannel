import asyncio
import unittest

from app.services.local_live_captioner import (
    LocalLiveCaptioner,
    is_local_live_model,
)


class FakeTranscriber:
    def __init__(self, model_id):
        self.model_id = model_id
        self.chunks: list[int] = []

    async def transcribe_segment(self, pcm_bytes):
        self.chunks.append(len(pcm_bytes))
        return "hello world"


class IsLocalLiveModelTests(unittest.TestCase):
    def test_only_the_live_id_matches(self):
        self.assertTrue(is_local_live_model("local-parakeet-live"))
        self.assertFalse(is_local_live_model("local-parakeet-tdt-0.6b"))
        self.assertFalse(is_local_live_model("gemini-3.1-flash-live-preview"))
        self.assertFalse(is_local_live_model(""))


class LocalLiveCaptionerTests(unittest.IsolatedAsyncioTestCase):
    def _captioner(self, commit_seconds=0.02):
        return LocalLiveCaptioner(
            "local-parakeet-live",
            commit_seconds=commit_seconds,
            make_transcriber=FakeTranscriber,
        )

    async def test_send_audio_trims_to_max(self):
        cap = self._captioner()
        over = cap._max_pending_bytes + 5000
        await cap.send_audio(b"\x00" * over)
        self.assertEqual(len(cap._pending), cap._max_pending_bytes)

    async def test_emits_a_caption_from_the_accumulated_chunk(self):
        cap = self._captioner()
        await cap.connect()
        # >= MIN_COMMIT (1s = 32000 bytes) of non-silent audio.
        await cap.send_audio(b"\x01\x02" * 20000)  # 40000 bytes
        gen = cap.receive_responses()
        try:
            event = await asyncio.wait_for(gen.__anext__(), timeout=2)
        finally:
            await cap.close()
            await gen.aclose()
        self.assertEqual(event, {"type": "transcript", "data": "hello world"})
        # The pending buffer was drained by the commit.
        self.assertEqual(len(cap._pending), 0)

    async def test_below_min_chunk_is_not_transcribed(self):
        cap = self._captioner()
        transcriber = FakeTranscriber("x")
        cap._transcriber = transcriber
        cap.session = True
        await cap.send_audio(b"\x00" * 10000)  # < 32000, below MIN_COMMIT
        gen = cap.receive_responses()
        # No event should arrive; the loop keeps waiting.
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(gen.__anext__(), timeout=0.2)
        await cap.close()
        await gen.aclose()
        self.assertEqual(transcriber.chunks, [])  # never transcribed the tiny chunk

    async def test_close_marks_session_gone(self):
        cap = self._captioner()
        await cap.connect()
        self.assertTrue(cap.session)
        await cap.close()
        self.assertIsNone(cap.session)


if __name__ == "__main__":
    unittest.main()

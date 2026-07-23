import math
import unittest
from unittest import mock

import numpy as np

from app.services import openai_transcriber
from app.services.batch_transcriber import BatchTranscriber, TranscriptionError
from app.services.local_transcriber import LocalTranscriber, create_transcriber
from app.services.openai_transcriber import OPENAI_TRANSCRIPTIONS_URL, OpenAITranscriber


def _speech_pcm(sample_rate: int = 16000) -> bytes:
    samples = [
        int(0.25 * 32767 * math.sin(2 * math.pi * 440 * i / sample_rate))
        for i in range(sample_rate)
    ]
    return np.array(samples, dtype=np.int16).tobytes()


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self._status_code = status_code
        self.calls: list[dict] = []

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self._payload, self._status_code)


class CreateTranscriberRoutingTests(unittest.TestCase):
    def test_local_id_routes_to_local_transcriber(self):
        self.assertIsInstance(create_transcriber("local-whisper-base"), LocalTranscriber)
        self.assertIsInstance(create_transcriber("local-parakeet-tdt-0.6b"), LocalTranscriber)

    def test_openai_id_routes_to_openai_transcriber(self):
        for model_id in ("gpt-4o-transcribe", "gpt-4o-mini-transcribe"):
            transcriber = create_transcriber(model_id, session_id="s-1")
            self.assertIsInstance(transcriber, OpenAITranscriber, model_id)
            self.assertEqual(model_id, transcriber._model_id)
            self.assertEqual("s-1", transcriber._session_id)

    def test_gemini_id_routes_to_batch_transcriber(self):
        transcriber = create_transcriber("gemini-3.5-flash-lite")
        self.assertIsInstance(transcriber, BatchTranscriber)

    def test_unknown_id_still_routes_to_batch_transcriber(self):
        # Ids removed from the registry may persist in stored settings.
        transcriber = create_transcriber("gemini-9.9-legacy-preview")
        self.assertIsInstance(transcriber, BatchTranscriber)


class OpenAITranscriberTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.resolve_key = mock.patch.object(
            openai_transcriber,
            "resolve_provider_key",
            mock.AsyncMock(return_value="test-key"),
        )
        self.resolve_key.start()
        self.addCleanup(self.resolve_key.stop)

        self.record_usage = mock.patch.object(
            openai_transcriber,
            "record_token_usage",
            mock.AsyncMock(),
        )
        self.record_usage_mock = self.record_usage.start()
        self.addCleanup(self.record_usage.stop)

    async def test_transcribes_segment_and_posts_wav_multipart(self):
        client = _FakeClient({"text": "this is transcribed speech"})
        transcriber = OpenAITranscriber("gpt-4o-transcribe", client=client)

        text = await transcriber.transcribe_segment(_speech_pcm())

        self.assertEqual("this is transcribed speech", text)
        self.assertEqual(1, len(client.calls))
        call = client.calls[0]
        self.assertEqual(OPENAI_TRANSCRIPTIONS_URL, call["url"])
        self.assertEqual("Bearer test-key", call["headers"]["Authorization"])
        self.assertEqual("gpt-4o-transcribe", call["data"]["model"])
        filename, wav_data, mime = call["files"]["file"]
        self.assertEqual("segment.wav", filename)
        self.assertEqual("audio/wav", mime)
        self.assertTrue(wav_data.startswith(b"RIFF"))

    async def test_records_provider_usage_for_session(self):
        usage = {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}
        client = _FakeClient({"text": "hello over there", "usage": usage})
        transcriber = OpenAITranscriber(
            "gpt-4o-mini-transcribe", session_id="sess-9", client=client
        )

        await transcriber.transcribe_segment(_speech_pcm())

        self.record_usage_mock.assert_awaited_once_with(
            "sess-9", "batch_transcriber", "gpt-4o-mini-transcribe", usage
        )

    async def test_short_segment_returns_none_without_network(self):
        client = _FakeClient({"text": "ignored"})
        transcriber = OpenAITranscriber("gpt-4o-transcribe", client=client)

        self.assertIsNone(await transcriber.transcribe_segment(b"\x00\x00" * 100))
        self.assertEqual([], client.calls)

    async def test_low_energy_segment_returns_none_without_network(self):
        client = _FakeClient({"text": "ignored"})
        transcriber = OpenAITranscriber("gpt-4o-transcribe", client=client)

        silence = b"\x00\x00" * 16000  # 1s of silence
        self.assertIsNone(await transcriber.transcribe_segment(silence))
        self.assertEqual([], client.calls)

    async def test_filters_single_word_output(self):
        client = _FakeClient({"text": "Okay."})
        transcriber = OpenAITranscriber("gpt-4o-transcribe", client=client)

        self.assertIsNone(await transcriber.transcribe_segment(_speech_pcm()))

    async def test_missing_key_raises_actionable_error_without_network(self):
        client = _FakeClient({"text": "ignored"})
        transcriber = OpenAITranscriber("gpt-4o-transcribe", client=client)
        with mock.patch.object(
            openai_transcriber, "resolve_provider_key", mock.AsyncMock(return_value="")
        ):
            with self.assertRaises(TranscriptionError) as ctx:
                await transcriber.transcribe_segment(_speech_pcm())

        self.assertIn("OpenAI API key", str(ctx.exception))
        self.assertIn("Admin -> API Keys", str(ctx.exception))
        self.assertEqual([], client.calls)

    async def test_http_error_raises_transcription_error(self):
        client = _FakeClient({"error": "bad"}, status_code=500)
        transcriber = OpenAITranscriber("gpt-4o-transcribe", client=client)

        with self.assertRaises(TranscriptionError) as ctx:
            await transcriber.transcribe_segment(_speech_pcm())

        self.assertIn("gpt-4o-transcribe", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

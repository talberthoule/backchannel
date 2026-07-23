import base64
import math
import unittest
from unittest import mock

import numpy as np

from app.services import openai_transcriber
from app.services.batch_transcriber import BatchTranscriber, TranscriptionError
from app.services.local_transcriber import LocalTranscriber, create_transcriber
from app.services.openai_transcriber import (
    OPENAI_CHAT_COMPLETIONS_URL,
    OPENAI_TRANSCRIPTIONS_URL,
    OpenAIChatTranscriber,
    OpenAITranscriber,
)


def _chat_payload(text: str, usage: dict | None = None) -> dict:
    payload = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    if usage is not None:
        payload["usage"] = usage
    return payload


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

    def test_openai_transcribe_id_routes_to_openai_transcriber(self):
        for model_id in ("gpt-4o-transcribe", "gpt-4o-mini-transcribe"):
            transcriber = create_transcriber(model_id, session_id="s-1")
            self.assertIsInstance(transcriber, OpenAITranscriber, model_id)
            self.assertEqual(model_id, transcriber._model_id)
            self.assertEqual("s-1", transcriber._session_id)

    def test_openai_chat_audio_id_routes_to_chat_transcriber(self):
        for model_id in ("gpt-audio-1.5", "gpt-audio-mini"):
            transcriber = create_transcriber(model_id, session_id="s-2")
            self.assertIsInstance(transcriber, OpenAIChatTranscriber, model_id)
            self.assertEqual(model_id, transcriber._model_id)
            self.assertEqual("s-2", transcriber._session_id)

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


class OpenAIChatTranscriberTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_transcribes_segment_via_chat_completions_input_audio(self):
        client = _FakeClient(_chat_payload("this is transcribed speech"))
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)

        text = await transcriber.transcribe_segment(_speech_pcm())

        self.assertEqual("this is transcribed speech", text)
        self.assertEqual(1, len(client.calls))
        call = client.calls[0]
        self.assertEqual(OPENAI_CHAT_COMPLETIONS_URL, call["url"])
        self.assertEqual("Bearer test-key", call["headers"]["Authorization"])
        body = call["json"]
        self.assertEqual("gpt-audio-1.5", body["model"])
        # Text-only output: the audio-output config and modalities fields
        # must be absent (the "audio" param is only for audio output).
        self.assertNotIn("modalities", body)
        self.assertNotIn("audio", body)
        (message,) = body["messages"]
        self.assertEqual("user", message["role"])
        audio_part, text_part = message["content"]
        self.assertEqual("input_audio", audio_part["type"])
        self.assertEqual("wav", audio_part["input_audio"]["format"])
        wav_data = base64.b64decode(audio_part["input_audio"]["data"])
        self.assertTrue(wav_data.startswith(b"RIFF"))
        self.assertEqual("text", text_part["type"])
        self.assertIn("Transcribe this audio exactly as spoken", text_part["text"])
        self.assertIn("Output ONLY the transcribed text", text_part["text"])

    async def test_records_provider_usage_for_session(self):
        usage = {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26}
        client = _FakeClient(_chat_payload("hello over there", usage))
        transcriber = OpenAIChatTranscriber(
            "gpt-audio-mini", session_id="sess-7", client=client
        )

        await transcriber.transcribe_segment(_speech_pcm())

        self.record_usage_mock.assert_awaited_once_with(
            "sess-7", "batch_transcriber", "gpt-audio-mini", usage
        )

    async def test_short_segment_returns_none_without_network(self):
        client = _FakeClient(_chat_payload("ignored"))
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)

        self.assertIsNone(await transcriber.transcribe_segment(b"\x00\x00" * 100))
        self.assertEqual([], client.calls)

    async def test_low_energy_segment_returns_none_without_network(self):
        client = _FakeClient(_chat_payload("ignored"))
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)

        silence = b"\x00\x00" * 16000  # 1s of silence
        self.assertIsNone(await transcriber.transcribe_segment(silence))
        self.assertEqual([], client.calls)

    async def test_filters_single_word_output(self):
        client = _FakeClient(_chat_payload("Okay."))
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)

        self.assertIsNone(await transcriber.transcribe_segment(_speech_pcm()))

    async def test_filters_hallucinated_output(self):
        client = _FakeClient(_chat_payload("Thank you for watching."))
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)

        self.assertIsNone(await transcriber.transcribe_segment(_speech_pcm()))

    async def test_empty_choices_returns_none(self):
        client = _FakeClient({"choices": []})
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)

        self.assertIsNone(await transcriber.transcribe_segment(_speech_pcm()))

    async def test_missing_key_raises_actionable_error_without_network(self):
        client = _FakeClient(_chat_payload("ignored"))
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)
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
        transcriber = OpenAIChatTranscriber("gpt-audio-1.5", client=client)

        with self.assertRaises(TranscriptionError) as ctx:
            await transcriber.transcribe_segment(_speech_pcm())

        self.assertIn("gpt-audio-1.5", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

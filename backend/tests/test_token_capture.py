import json
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from app.services.batch_transcriber import BatchTranscriber
from app.services.gemini_live import GeminiLiveSession, _usage_delta
from app.services.openai_realtime import OpenAIRealtimeSession


class _AsyncEvents:
    def __init__(self, events):
        self._events = iter(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration


class TokenCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_transcriber_records_response_usage(self):
        response = SimpleNamespace(
            text="hello there",
            usage_metadata=SimpleNamespace(prompt_token_count=9, candidates_token_count=2, total_token_count=11),
        )
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content=mock.AsyncMock(return_value=response),
        )))
        session_id = uuid.uuid4()
        transcriber = BatchTranscriber(client=client, session_id=session_id)
        with mock.patch("app.services.batch_transcriber._audio_has_speech_energy", return_value=True), \
             mock.patch("app.services.batch_transcriber.record_token_usage", mock.AsyncMock()) as record:
            text = await transcriber.transcribe_segment(b"\x01\x00" * 16000)
        self.assertEqual("hello there", text)
        record.assert_awaited_once_with(session_id, "batch_transcriber", transcriber._model_id, response.usage_metadata)

    def test_gemini_live_usage_uses_positive_cumulative_deltas(self):
        self.assertEqual((10, 2, 0, 12), _usage_delta((10, 2, 0, 12), (0, 0, 0, 0)))
        self.assertEqual((3, 1, 0, 4), _usage_delta((13, 3, 0, 16), (10, 2, 0, 12)))
        self.assertEqual((0, 0, 0, 0), _usage_delta((2, 1, 0, 3), (13, 3, 0, 16)))
        # A thinking-only increment still produces a delta.
        self.assertEqual((0, 0, 5, 5), _usage_delta((10, 2, 5, 17), (10, 2, 0, 12)))

    async def test_gemini_live_records_each_positive_delta(self):
        session_id = uuid.uuid4()
        gateway = GeminiLiveSession(session_id=session_id)
        gateway.session = SimpleNamespace(receive=lambda: _AsyncEvents([
            SimpleNamespace(server_content=None, usage_metadata=SimpleNamespace(prompt_token_count=10, response_token_count=1, total_token_count=11)),
            SimpleNamespace(server_content=None, usage_metadata=SimpleNamespace(prompt_token_count=14, response_token_count=2, total_token_count=16)),
        ]))
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            self.assertEqual([], [item async for item in gateway.receive_responses()])
        self.assertEqual(2, record.await_count)
        self.assertEqual(
            {"input_tokens": 4, "output_tokens": 1, "thoughts_token_count": 0, "total_tokens": 5},
            record.await_args_list[1].args[3],
        )

    async def test_malformed_gemini_usage_does_not_break_transcription(self):
        gateway = GeminiLiveSession(session_id=uuid.uuid4())
        gateway.session = SimpleNamespace(receive=lambda: _AsyncEvents([
            SimpleNamespace(
                usage_metadata=SimpleNamespace(prompt_token_count="unknown"),
                server_content=SimpleNamespace(
                    input_transcription=SimpleNamespace(text="hello there everyone"),
                    model_turn=None,
                ),
            ),
        ]))
        with mock.patch("app.services.gemini_live.logger.exception"):
            results = [item async for item in gateway.receive_responses()]
        self.assertEqual([{"type": "transcript", "data": "hello there everyone"}], results)

    async def test_openai_realtime_records_completed_event_usage(self):
        session_id = uuid.uuid4()
        gateway = OpenAIRealtimeSession(session_id=session_id)
        event = {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "hello there everyone",
            "usage": {"input_tokens": 6, "output_tokens": 2, "total_tokens": 8},
        }
        gateway._ws = _AsyncEvents([json.dumps(event)])
        with mock.patch("app.services.openai_realtime.record_token_usage", mock.AsyncMock()) as record:
            results = [item async for item in gateway.receive_responses()]
        self.assertEqual([{"type": "transcript", "data": "hello there everyone"}], results)
        record.assert_awaited_once_with(session_id, "audio_gateway", gateway._transcribe_model, event["usage"])


if __name__ == "__main__":
    unittest.main()

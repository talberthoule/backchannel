import json
import logging
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from app.services.batch_transcriber import BatchTranscriber
from app.services.gemini_live import GeminiLiveSession
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


def _usage(prompt, response, total=None):
    return SimpleNamespace(
        prompt_token_count=prompt,
        response_token_count=response,
        total_token_count=prompt + response if total is None else total,
    )


def _content(turn_complete=False, interrupted=False, generation_complete=False):
    return SimpleNamespace(
        turn_complete=turn_complete,
        interrupted=interrupted,
        generation_complete=generation_complete,
        input_transcription=None,
        model_turn=None,
    )


def _message(usage_metadata=None, server_content=None):
    return SimpleNamespace(usage_metadata=usage_metadata, server_content=server_content)


def _gateway(events, session_id=None):
    gateway = GeminiLiveSession(session_id=session_id or uuid.uuid4())
    gateway.session = SimpleNamespace(receive=lambda: _AsyncEvents(events))
    return gateway


async def _drain(gateway):
    return [item async for item in gateway.receive_responses()]


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

    # --- Gemini Live: one pending usage per turn, flushed when the turn ends ---

    async def test_gemini_live_growing_per_chunk_usage_records_once_at_its_final_value(self):
        """If usage rides every audio chunk with counts that grow through the
        turn, only the last value is the turn's bill; recording each chunk
        would multiply the turn by its chunk count."""
        session_id = uuid.uuid4()
        final = _usage(640, 25)
        gateway = _gateway([
            _message(_usage(600, 5), _content()),
            _message(_usage(620, 15), _content()),
            _message(final, _content(turn_complete=True)),
        ], session_id)
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            self.assertEqual([], await _drain(gateway))
        record.assert_awaited_once_with(session_id, "audio_gateway", gateway._model, final)

    async def test_gemini_live_one_usage_per_turn_records_once_per_turn(self):
        session_id = uuid.uuid4()
        first = _usage(10, 1)
        second = _usage(14, 0)
        gateway = _gateway([
            # Usage arriving on its own message, then the turn ending.
            _message(first, None),
            _message(None, _content(turn_complete=True)),
            # Usage arriving on the turn_complete message itself.
            _message(second, _content(turn_complete=True)),
        ], session_id)
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            await _drain(gateway)
        self.assertEqual(
            [
                mock.call(session_id, "audio_gateway", gateway._model, first),
                mock.call(session_id, "audio_gateway", gateway._model, second),
            ],
            record.await_args_list,
        )

    async def test_gemini_live_turn_without_usage_records_nothing(self):
        gateway = _gateway([
            _message(None, _content(turn_complete=True)),
            _message(None, _content(turn_complete=True)),
        ])
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            await _drain(gateway)
        record.assert_not_awaited()

    async def test_gemini_live_generation_complete_does_not_flush(self):
        # generation_complete precedes turn_complete inside the same turn;
        # flushing there too would record a per-chunk turn twice.
        session_id = uuid.uuid4()
        final = _usage(700, 30)
        gateway = _gateway([
            _message(_usage(690, 20), _content(generation_complete=True)),
            _message(final, _content(turn_complete=True)),
        ], session_id)
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            await _drain(gateway)
        record.assert_awaited_once_with(session_id, "audio_gateway", gateway._model, final)

    async def test_gemini_live_interruption_ends_the_turn(self):
        session_id = uuid.uuid4()
        cut = _usage(300, 4)
        gateway = _gateway([
            _message(cut, _content()),
            _message(None, _content(interrupted=True)),
        ], session_id)
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            await _drain(gateway)
        record.assert_awaited_once_with(session_id, "audio_gateway", gateway._model, cut)

    async def test_gemini_live_pending_usage_is_flushed_when_the_stream_ends(self):
        # The socket dropped mid-turn: the tokens were still billed.
        session_id = uuid.uuid4()
        pending = _usage(500, 10)
        gateway = _gateway([_message(pending, _content())], session_id)
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            await _drain(gateway)
        record.assert_awaited_once_with(session_id, "audio_gateway", gateway._model, pending)

    async def test_gemini_live_pending_usage_is_flushed_on_close_and_only_once(self):
        session_id = uuid.uuid4()
        pending = _usage(500, 10)
        gateway = GeminiLiveSession(session_id=session_id)
        gateway._pending_usage = pending
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            await gateway.close()
            await gateway.close()
        record.assert_awaited_once_with(session_id, "audio_gateway", gateway._model, pending)

    async def test_gemini_live_flushes_when_the_consumer_stops_early(self):
        session_id = uuid.uuid4()
        pending = _usage(500, 10)
        gateway = _gateway([
            _message(pending, SimpleNamespace(
                turn_complete=False,
                interrupted=False,
                input_transcription=SimpleNamespace(text="hello there everyone"),
                model_turn=None,
            )),
            _message(_usage(900, 90), _content(turn_complete=True)),
        ], session_id)
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            stream = gateway.receive_responses()
            self.assertEqual({"type": "transcript", "data": "hello there everyone"}, await stream.__anext__())
            await stream.aclose()
        # Only the usage seen before the consumer stopped; nothing invented.
        record.assert_awaited_once_with(session_id, "audio_gateway", gateway._model, pending)

    async def test_gemini_live_passes_the_raw_metadata_so_modality_slices_survive(self):
        # The per-modality breakdown (audio input, audio output) is what lets
        # the gateway price at the audio rate; a reconstructed dict of totals
        # would drop it.
        usage = SimpleNamespace(
            prompt_token_count=640,
            response_token_count=25,
            total_token_count=665,
            prompt_tokens_details=[SimpleNamespace(modality="AUDIO", token_count=600)],
            response_tokens_details=[SimpleNamespace(modality="AUDIO", token_count=25)],
        )
        gateway = _gateway([_message(usage, _content(turn_complete=True))])
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()) as record:
            await _drain(gateway)
        self.assertIs(usage, record.await_args.args[3])

    async def test_gemini_live_logs_each_usage_message_at_debug(self):
        gateway = _gateway([_message(_usage(640, 25, total=670), _content(turn_complete=True))])
        with mock.patch("app.services.gemini_live.record_token_usage", mock.AsyncMock()), \
             self.assertLogs("app.services.gemini_live", level=logging.DEBUG) as logs:
            await _drain(gateway)
        line = next(record for record in logs.output if "usage_metadata" in record)
        self.assertIn("prompt=640", line)
        self.assertIn("response=25", line)
        self.assertIn("total=670", line)
        self.assertIn("turn_complete=True", line)

    async def test_malformed_gemini_usage_does_not_break_transcription(self):
        gateway = _gateway([
            SimpleNamespace(
                usage_metadata=SimpleNamespace(prompt_token_count="unknown"),
                server_content=SimpleNamespace(
                    turn_complete=True,
                    interrupted=False,
                    input_transcription=SimpleNamespace(text="hello there everyone"),
                    model_turn=None,
                ),
            ),
        ])
        with mock.patch("app.services.token_usage.logger.exception"):
            results = await _drain(gateway)
        self.assertEqual([{"type": "transcript", "data": "hello there everyone"}], results)

    # --- OpenAI Realtime ---

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

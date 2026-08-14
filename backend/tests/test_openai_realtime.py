import asyncio
import json
import unittest

import numpy as np

from app.services.openai_realtime import (
    COMMIT_INTERVAL_BYTES,
    DEFAULT_TRANSCRIBE_MODEL,
    OpenAIRealtimeSession,
    _parse_event,
    _resample_16k_to_24k,
    _session_update_payload,
    resolve_transcribe_model,
)


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))


class SessionUpdateTests(unittest.TestCase):
    def test_ga_session_update_shape(self):
        payload = _session_update_payload("gpt-live-transcribe")
        self.assertEqual("session.update", payload["type"])
        self.assertEqual("transcription", payload["session"]["type"])
        audio_input = payload["session"]["audio"]["input"]
        self.assertEqual({"type": "audio/pcm", "rate": 24000}, audio_input["format"])
        self.assertEqual("gpt-live-transcribe", audio_input["transcription"]["model"])
        # gpt-live-transcribe rejects server VAD; must stay absent
        self.assertNotIn("turn_detection", audio_input)


class CommitCadenceTests(unittest.TestCase):
    def test_commits_after_interval_and_resets(self):
        session = OpenAIRealtimeSession(model_override="gpt-live-transcribe")
        ws = _FakeWS()
        session._ws = ws
        one_second = b"\x00" * 32000

        async def run():
            for _ in range(3):
                await session.send_audio(one_second)

        asyncio.run(run())
        types = [m["type"] for m in ws.sent]
        self.assertEqual(3, types.count("input_audio_buffer.append"))
        self.assertEqual(1, types.count("input_audio_buffer.commit"))
        self.assertEqual("input_audio_buffer.commit", types[-1])
        self.assertEqual(0, session._bytes_since_commit)
        self.assertEqual(3 * 32000, COMMIT_INTERVAL_BYTES)


class ResampleTests(unittest.TestCase):
    def test_length_scales_3_to_2(self):
        pcm = np.zeros(1600, dtype=np.int16).tobytes()
        out = _resample_16k_to_24k(pcm)
        self.assertEqual(2400 * 2, len(out))

    def test_constant_signal_preserved(self):
        pcm = (np.ones(1600, dtype=np.int16) * 1000).tobytes()
        out = np.frombuffer(_resample_16k_to_24k(pcm), dtype=np.int16)
        self.assertTrue(np.all(np.abs(out.astype(np.int32) - 1000) <= 1))

    def test_empty_input(self):
        self.assertEqual(b"", _resample_16k_to_24k(b""))


class ParseEventTests(unittest.TestCase):
    def test_completed_transcription_yields_text(self):
        event = {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "hello there everyone",
        }
        self.assertEqual("hello there everyone", _parse_event(event))

    def test_delta_ignored(self):
        event = {"type": "conversation.item.input_audio_transcription.delta", "delta": "hel"}
        self.assertIsNone(_parse_event(event))

    def test_hallucination_filtered(self):
        event = {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "Thank you for watching",
        }
        self.assertIsNone(_parse_event(event))

    def test_error_event_ignored(self):
        self.assertIsNone(_parse_event({"type": "error", "error": {"message": "x"}}))


class TranscribeModelSelectionTests(unittest.TestCase):
    def test_registry_ids_pass_through(self):
        self.assertEqual("gpt-live-transcribe", resolve_transcribe_model("gpt-live-transcribe"))
        self.assertEqual("gpt-4o-transcribe", resolve_transcribe_model("gpt-4o-transcribe"))
        self.assertEqual("gpt-4o-mini-transcribe", resolve_transcribe_model("gpt-4o-mini-transcribe"))

    def test_legacy_aliases_resolve(self):
        self.assertEqual("gpt-4o-transcribe", resolve_transcribe_model("openai-realtime"))
        self.assertEqual("gpt-4o-mini-transcribe", resolve_transcribe_model("openai-realtime-mini"))
        self.assertEqual("gpt-live-transcribe", resolve_transcribe_model("openai-realtime-whisper"))

    def test_the_retired_whisper_id_still_resolves(self):
        # gpt-realtime-whisper was the registry id until gpt-live-transcribe
        # replaced it. Stored agent_configs.model_id rows are never rewritten
        # in place (ALP-188), so any install that had selected it keeps a dead
        # id on disk. Without this alias the audio gateway would fail at call
        # time rather than at startup -- the same quiet failure mode seen when
        # a removed custom endpoint was left referenced.
        self.assertEqual("gpt-live-transcribe", resolve_transcribe_model("gpt-realtime-whisper"))

    def test_session_honors_model_override(self):
        session = OpenAIRealtimeSession(model_override="gpt-live-transcribe")
        self.assertEqual("gpt-live-transcribe", session._transcribe_model)

    def test_session_defaults_only_for_missing_override(self):
        self.assertEqual(
            DEFAULT_TRANSCRIBE_MODEL,
            OpenAIRealtimeSession()._transcribe_model,
        )
        self.assertEqual("", OpenAIRealtimeSession(model_override="")._transcribe_model)
        self.assertEqual(
            "something-else",
            OpenAIRealtimeSession(model_override="something-else")._transcribe_model,
        )


if __name__ == "__main__":
    unittest.main()

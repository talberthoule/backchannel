import unittest

import numpy as np

from app.services.openai_realtime import (
    DEFAULT_TRANSCRIBE_MODEL,
    OpenAIRealtimeSession,
    _parse_event,
    _resample_16k_to_24k,
    resolve_transcribe_model,
)


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
        self.assertEqual("gpt-realtime-whisper", resolve_transcribe_model("gpt-realtime-whisper"))
        self.assertEqual("gpt-4o-transcribe", resolve_transcribe_model("gpt-4o-transcribe"))
        self.assertEqual("gpt-4o-mini-transcribe", resolve_transcribe_model("gpt-4o-mini-transcribe"))

    def test_legacy_aliases_resolve(self):
        self.assertEqual("gpt-4o-transcribe", resolve_transcribe_model("openai-realtime"))
        self.assertEqual("gpt-4o-mini-transcribe", resolve_transcribe_model("openai-realtime-mini"))
        self.assertEqual("gpt-realtime-whisper", resolve_transcribe_model("openai-realtime-whisper"))

    def test_session_honors_model_override(self):
        session = OpenAIRealtimeSession(model_override="gpt-realtime-whisper")
        self.assertEqual("gpt-realtime-whisper", session._transcribe_model)

    def test_session_defaults_for_unknown_or_missing_override(self):
        self.assertEqual(
            DEFAULT_TRANSCRIBE_MODEL,
            OpenAIRealtimeSession()._transcribe_model,
        )
        self.assertEqual(
            DEFAULT_TRANSCRIBE_MODEL,
            OpenAIRealtimeSession(model_override="something-else")._transcribe_model,
        )


if __name__ == "__main__":
    unittest.main()

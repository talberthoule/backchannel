"""Real transcriber failures must surface as TranscriptionError, not None.

Filtered segments (too short, below the energy floor, hallucination text)
still return None; provider/model/runtime errors raise so the live-call
queue can count and report them (ALP-112).
"""

import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.services import local_transcriber
from app.services.batch_transcriber import BatchTranscriber, TranscriptionError
from app.services.local_transcriber import LocalTranscriber
from app.services.ordered_transcription import OrderedTranscriptionQueue


def _speech_pcm(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """PCM16 sine tone loud enough to pass the speech-energy floor."""
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    samples = (np.sin(2 * math.pi * 440 * t) * 8000).astype(np.int16)
    return samples.tobytes()


class _FailingModels:
    async def generate_content(self, **kwargs):
        raise RuntimeError("API key not valid")


class _EmptyTextModels:
    async def generate_content(self, **kwargs):
        return SimpleNamespace(text="")


def _client(models) -> SimpleNamespace:
    return SimpleNamespace(aio=SimpleNamespace(models=models))


class BatchTranscriberFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_error_raises_transcription_error(self):
        transcriber = BatchTranscriber(
            model_id="gemini-3.5-flash-lite", client=_client(_FailingModels())
        )

        with self.assertRaises(TranscriptionError):
            await transcriber.transcribe_segment(_speech_pcm())

    async def test_short_segment_returns_none_without_provider_call(self):
        transcriber = BatchTranscriber(
            model_id="gemini-3.5-flash-lite", client=_client(_FailingModels())
        )

        self.assertIsNone(await transcriber.transcribe_segment(b"\x00\x00" * 100))

    async def test_quiet_segment_returns_none_without_provider_call(self):
        transcriber = BatchTranscriber(
            model_id="gemini-3.5-flash-lite", client=_client(_FailingModels())
        )

        self.assertIsNone(await transcriber.transcribe_segment(b"\x00\x00" * 16000))

    async def test_empty_provider_text_is_filtered_not_failed(self):
        transcriber = BatchTranscriber(
            model_id="gemini-3.5-flash-lite", client=_client(_EmptyTextModels())
        )

        self.assertIsNone(await transcriber.transcribe_segment(_speech_pcm()))


class LocalTranscriberFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_error_raises_transcription_error(self):
        def broken_load(model_id):
            raise RuntimeError("onnx runtime exploded")

        transcriber = LocalTranscriber("local-whisper-base")
        with patch.object(local_transcriber, "_load_model", broken_load):
            with self.assertRaises(TranscriptionError):
                await transcriber.transcribe_segment(_speech_pcm())

    async def test_short_segment_returns_none_without_model_load(self):
        def broken_load(model_id):
            raise AssertionError("model should not load for short segments")

        transcriber = LocalTranscriber("local-whisper-base")
        with patch.object(local_transcriber, "_load_model", broken_load):
            self.assertIsNone(await transcriber.transcribe_segment(b"\x00\x00" * 100))


class QueueWithProductionTranscriberTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_transcriber_failure_reaches_status_callback(self):
        """An actual adapter failure must increment stats and notify."""
        failures = []

        def broken_load(model_id):
            raise RuntimeError("weights corrupted")

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            self.fail("nothing should be emitted for a failed segment")

        async def on_failure(failed_count: int, kind: str):
            failures.append((failed_count, kind))

        transcriber = LocalTranscriber("local-whisper-base")
        queue = OrderedTranscriptionQueue(
            transcribe=transcriber.transcribe_segment,
            emit=emit,
            on_failure=on_failure,
        )
        with patch.object(local_transcriber, "_load_model", broken_load):
            queue.add("auto_1", _speech_pcm())
            await queue.drain()

        self.assertEqual({"jobs": 1, "emitted": 0, "failed": 1}, queue.stats)
        self.assertEqual([(1, "transcribe")], failures)

    async def test_batch_transcriber_failure_reaches_status_callback(self):
        failures = []

        async def emit(speaker_auto_id: str, pcm_bytes: bytes, text: str):
            self.fail("nothing should be emitted for a failed segment")

        async def on_failure(failed_count: int, kind: str):
            failures.append((failed_count, kind))

        transcriber = BatchTranscriber(
            model_id="gemini-3.5-flash-lite", client=_client(_FailingModels())
        )
        queue = OrderedTranscriptionQueue(
            transcribe=transcriber.transcribe_segment,
            emit=emit,
            on_failure=on_failure,
        )
        queue.add("auto_1", _speech_pcm())
        await queue.drain()

        self.assertEqual({"jobs": 1, "emitted": 0, "failed": 1}, queue.stats)
        self.assertEqual([(1, "transcribe")], failures)


if __name__ == "__main__":
    unittest.main()

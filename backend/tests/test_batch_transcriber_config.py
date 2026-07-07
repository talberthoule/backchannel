import math
import unittest

import numpy as np

from app.services.batch_transcriber import BatchTranscriber


class BatchTranscriberConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_segment_uses_configured_model(self):
        fake_client = _FakeClient("this is transcribed speech")
        transcriber = BatchTranscriber(model_id="gemini-test-transcriber", client=fake_client)

        text = await transcriber.transcribe_segment(_speech_pcm())

        self.assertEqual("this is transcribed speech", text)
        self.assertEqual("gemini-test-transcriber", fake_client.aio.models.last_model)


def _speech_pcm(sample_rate: int = 16000) -> bytes:
    samples = [
        int(0.25 * 32767 * math.sin(2 * math.pi * 440 * i / sample_rate))
        for i in range(sample_rate)
    ]
    return np.array(samples, dtype=np.int16).tobytes()


class _FakeClient:
    def __init__(self, text: str):
        self.aio = _FakeAio(text)


class _FakeAio:
    def __init__(self, text: str):
        self.models = _FakeModels(text)


class _FakeModels:
    def __init__(self, text: str):
        self._text = text
        self.last_model: str | None = None

    async def generate_content(self, model: str, contents):
        self.last_model = model
        return _FakeResponse(self._text)


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


if __name__ == "__main__":
    unittest.main()

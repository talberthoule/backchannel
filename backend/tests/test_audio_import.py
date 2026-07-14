import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.routers.imports import _transcribe_audio_diarized, import_audio


class FakeUpload:
    filename = "recording.wav"

    async def read(self):
        return b"audio"


class AudioImportRuntimeBoundaryTests(unittest.TestCase):
    def test_only_audio_import_endpoint_disables_sortformer_probe(self):
        session_id = uuid.uuid4()
        db = object()

        with patch(
            "app.routers.imports._transcribe_audio_diarized",
            new=AsyncMock(return_value=1),
        ) as transcribe:
            asyncio.run(import_audio(session_id, FakeUpload(), db))

        transcribe.assert_awaited_once_with(
            b"audio",
            "wav",
            session_id,
            db,
            persist_audio=True,
            probe_sortformer=False,
        )

        with (
            patch("app.routers.imports.convert_to_pcm16", return_value=b"pcm"),
            patch(
                "app.routers.imports.get_diarizer_runtime_config",
                new=AsyncMock(side_effect=RuntimeError("stop after runtime config")),
            ) as runtime_config,
            self.assertRaisesRegex(RuntimeError, "stop after runtime config"),
        ):
            asyncio.run(_transcribe_audio_diarized(b"audio", "wav", session_id, db))

        runtime_config.assert_awaited_once_with(db, probe_sortformer=True)


if __name__ == "__main__":
    unittest.main()

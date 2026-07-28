import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from app.services.audio_utils import convert_to_pcm16, resolve_ffmpeg
from app.services.voice_enrollment import (
    MAX_ENROLLMENT_SECONDS,
    MIN_ENROLLMENT_SECONDS,
    SETTING_LOCAL_VOICE_EMBEDDING,
    VoiceEnrollmentError,
    clear_local_voice_embedding,
    extract_enrollment_embedding,
    load_local_voice_embedding,
    save_local_voice_embedding,
)


class VoiceEnrollmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_data_dir = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name

        from app.services import secrets

        self.secrets = secrets
        self.secrets._fernet = None
        self.store: dict[str, str] = {}

        async def fake_get(_db, key, default=""):
            return self.store.get(key, default)

        async def fake_set(_db, key, value):
            self.store[key] = value

        self.patches = [
            mock.patch.object(secrets, "get_app_setting", fake_get),
            mock.patch.object(secrets, "set_app_setting", fake_set),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in self.patches:
            patcher.stop()
        self.secrets._fernet = None
        if self.original_data_dir is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.original_data_dir
        self.tmp.cleanup()

    async def test_round_trip_is_normalized_and_encrypted(self):
        await save_local_voice_embedding(
            None,
            np.array([3.0, 4.0], dtype=np.float32),
        )

        stored = self.store[SETTING_LOCAL_VOICE_EMBEDDING]
        self.assertNotIn("3.0", stored)
        self.assertNotIn("4.0", stored)
        np.testing.assert_allclose(
            await load_local_voice_embedding(None),
            np.array([0.6, 0.8], dtype=np.float32),
        )

    async def test_clear_and_corrupt_storage_read_as_unenrolled(self):
        await save_local_voice_embedding(
            None,
            np.array([1.0, 0.0], dtype=np.float32),
        )
        await clear_local_voice_embedding(None)
        self.assertIsNone(await load_local_voice_embedding(None))

        await self.secrets.set_secret(
            None,
            SETTING_LOCAL_VOICE_EMBEDDING,
            "not-json",
        )
        with self.assertLogs("app.services.voice_enrollment", level="WARNING"):
            self.assertIsNone(await load_local_voice_embedding(None))

    def test_extract_normalizes_valid_embedding(self):
        voiced = np.full(16000 * MIN_ENROLLMENT_SECONDS, 1000, dtype=np.int16)

        result = extract_enrollment_embedding(
            voiced.tobytes(),
            extractor=lambda *_: np.array([3.0, 4.0], dtype=np.float32),
        )

        np.testing.assert_allclose(result, np.array([0.6, 0.8], dtype=np.float32))

    def test_extract_rejects_audio_outside_duration_bounds(self):
        short = np.full(16000 * MIN_ENROLLMENT_SECONDS - 1, 1000, dtype=np.int16)
        long = np.full(16000 * MAX_ENROLLMENT_SECONDS + 1, 1000, dtype=np.int16)

        with self.assertRaisesRegex(VoiceEnrollmentError, "at least 4 seconds"):
            extract_enrollment_embedding(short.tobytes(), extractor=lambda *_: np.ones(2))
        with self.assertRaisesRegex(VoiceEnrollmentError, "no longer than 15 seconds"):
            extract_enrollment_embedding(long.tobytes(), extractor=lambda *_: np.ones(2))

    def test_extract_rejects_silence_and_invalid_vectors(self):
        silence = np.zeros(16000 * MIN_ENROLLMENT_SECONDS, dtype=np.int16)
        with self.assertRaisesRegex(VoiceEnrollmentError, "audible speech"):
            extract_enrollment_embedding(silence.tobytes(), extractor=lambda *_: np.ones(2))

        voiced = np.full(16000 * MIN_ENROLLMENT_SECONDS, 1000, dtype=np.int16)
        for invalid in (
            np.array([np.nan], dtype=np.float32),
            np.array([0.0, 0.0], dtype=np.float32),
            np.array([[1.0, 0.0]], dtype=np.float32),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(VoiceEnrollmentError, "invalid"):
                    extract_enrollment_embedding(
                        voiced.tobytes(),
                        extractor=lambda *_args, value=invalid: value,
                    )

    @unittest.skipUnless(resolve_ffmpeg(), "ffmpeg is not installed")
    def test_webm_fixture_runs_real_conversion_fbank_and_embedding(self):
        fixture = Path(__file__).with_name("fixtures") / "voice_enrollment.webm"

        pcm = convert_to_pcm16(
            fixture.read_bytes(),
            "webm",
            max_seconds=MAX_ENROLLMENT_SECONDS,
        )
        result = extract_enrollment_embedding(pcm)

        self.assertGreaterEqual(len(pcm), MIN_ENROLLMENT_SECONDS * 16000 * 2)
        self.assertEqual(1, result.ndim)
        self.assertTrue(np.isfinite(result).all())
        self.assertAlmostEqual(1.0, float(np.linalg.norm(result)), places=5)


if __name__ == "__main__":
    unittest.main()

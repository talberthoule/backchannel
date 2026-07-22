import os
import tempfile
import unittest
import uuid

import numpy as np
import soundfile as sf


class AudioStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_close_roundtrip(self):
        from app.services.audio_store import SegmentAudioWriter, audio_file_path

        session_id = uuid.uuid4()
        writer = SegmentAudioWriter(session_id, 1)
        chunk = (np.sin(np.linspace(0, 100, 1600)) * 10000).astype(np.int16).tobytes()
        writer.append(chunk)
        writer.append(chunk)
        rel_path = writer.close()
        self.assertIsNotNone(rel_path)

        path = audio_file_path(session_id, 1)
        self.assertTrue(path.exists())
        data, rate = sf.read(path, dtype="int16")
        self.assertEqual(16000, rate)
        self.assertEqual(3200, len(data))

    def test_no_audio_returns_none(self):
        from app.services.audio_store import SegmentAudioWriter

        writer = SegmentAudioWriter(uuid.uuid4(), 1)
        self.assertIsNone(writer.close())

    def test_system_track_gets_own_file(self):
        from app.services.audio_store import SegmentAudioWriter, audio_file_path

        session_id = uuid.uuid4()
        writer = SegmentAudioWriter(session_id, 2, track="sys")
        writer.append(b"\x00\x01" * 1600)
        writer.close()
        path = audio_file_path(session_id, 2, track="sys")
        self.assertTrue(path.name.endswith("segment_2_sys.wav"))
        self.assertTrue(path.exists())

    def test_microphone_track_gets_own_file(self):
        from app.services.audio_store import SegmentAudioWriter, audio_file_path

        session_id = uuid.uuid4()
        writer = SegmentAudioWriter(session_id, 2, track="mic")
        writer.append(b"\x00\x01" * 1600)
        writer.close()
        path = audio_file_path(session_id, 2, track="mic")
        self.assertTrue(path.name.endswith("segment_2_mic.wav"))
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()

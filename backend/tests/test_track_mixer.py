import unittest

import numpy as np

from app.services.track_mixer import FRAME_BYTES, TrackMixer


def frame(value: int) -> bytes:
    return (np.ones(FRAME_BYTES // 2, dtype=np.int16) * value).tobytes()


class TrackMixerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.mixer = TrackMixer(now=lambda: self.now)

    def test_aligned_frames_are_summed(self):
        self.assertIsNone(self.mixer.add(0, frame(1000)))
        out = self.mixer.add(1, frame(2000))
        self.assertIsNotNone(out)
        mixed = np.frombuffer(out, dtype=np.int16)
        self.assertTrue(np.all(mixed == 3000))

    def test_sum_clamps_at_int16_range(self):
        self.mixer.add(0, frame(30000))
        out = self.mixer.add(1, frame(30000))
        mixed = np.frombuffer(out, dtype=np.int16)
        self.assertTrue(np.all(mixed == 32767))

    def test_solo_track_flushes_after_idle(self):
        # Only mic traffic; system track never seen -> flush immediately after idle window
        self.now = 10.0
        out = self.mixer.add(0, frame(500))
        self.assertIsNotNone(out)
        self.assertEqual(FRAME_BYTES, len(out))
        self.assertTrue(np.all(np.frombuffer(out, dtype=np.int16) == 500))

    def test_waits_for_laggard_within_idle_window(self):
        self.now = 10.0
        self.mixer.add(1, frame(100))  # system seen at t=10
        self.now = 10.05
        out = self.mixer.add(0, frame(200))  # mic arrives 50ms later; system buffer empty but recent
        self.assertIsNone(out)
        self.now = 10.4  # system now idle > 200ms
        out = self.mixer.add(0, frame(300))
        self.assertIsNotNone(out)
        self.assertEqual(2 * FRAME_BYTES, len(out))


if __name__ == "__main__":
    unittest.main()

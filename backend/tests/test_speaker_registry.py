import unittest

import numpy as np

from app.services.speaker_diarizer import SpeakerRegistry


def embedding(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


class SpeakerRegistryTests(unittest.TestCase):
    def test_short_unmatched_segment_reuses_profile_without_enrolling(self):
        registry = SpeakerRegistry(threshold=0.9, max_profiles=4)
        first_id = registry.match_or_create(embedding(1.0, 0.0))

        result = registry.match_or_create(
            embedding(0.0, 1.0),
            allow_create=False,
        )

        self.assertEqual(first_id, result)
        self.assertEqual(1, registry.profile_count)

    def test_long_unmatched_segment_can_enroll_new_profile(self):
        registry = SpeakerRegistry(threshold=0.9, max_profiles=4)
        registry.match_or_create(embedding(1.0, 0.0))

        second_id = registry.match_or_create(embedding(0.0, 1.0))

        self.assertEqual("auto_2", second_id)
        self.assertEqual(2, registry.profile_count)

    def test_profile_limit_reuses_closest_profile(self):
        registry = SpeakerRegistry(threshold=0.95, max_profiles=2)
        registry.match_or_create(embedding(1.0, 0.0, 0.0))
        registry.match_or_create(embedding(0.0, 1.0, 0.0))

        result = registry.match_or_create(embedding(0.6, 0.0, 0.8))

        self.assertEqual("auto_1", result)
        self.assertEqual(2, registry.profile_count)


if __name__ == "__main__":
    unittest.main()

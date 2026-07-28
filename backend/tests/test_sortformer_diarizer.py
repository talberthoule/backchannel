import unittest

import numpy as np

from app.services.sortformer_diarizer import SortformerDiarizer, extract_sortformer_turns
from app.services.speaker_diarizer import SpeakerRegistry
from app.services.voice_enrollment import LOCAL_VOICE_PROFILE_ID


def _embedding_from_signal_mean(pcm_float: np.ndarray, sample_rate: int) -> np.ndarray:
    del sample_rate
    if float(np.mean(pcm_float)) >= 0:
        return np.array([1.0, 0.0], dtype=np.float32)
    return np.array([0.0, 1.0], dtype=np.float32)


class StubSortformerDiarizer(SortformerDiarizer):
    def __init__(self, results, **kwargs):
        super().__init__(embedding_extractor=_embedding_from_signal_mean, **kwargs)
        self._results = list(results)

    def _run_sortformer(self, pcm_bytes: bytes):
        del pcm_bytes
        return self._results.pop(0)


class SortformerDiarizerTests(unittest.TestCase):
    def test_segments_record_absolute_start_across_windows(self):
        diarizer = StubSortformerDiarizer(
            [["0.00 1.00 speaker_0"], ["0.00 1.00 speaker_0"]],
            window_ms=1000,
        )
        diarizer._min_new_speaker_bytes = 0
        voice = (np.ones(16000, dtype=np.int16) * 1000).tobytes()

        first = diarizer.feed_audio(voice)
        second = diarizer.feed_audio(voice)

        self.assertEqual(0, first[0].start_sample)
        self.assertEqual(16000, second[0].start_sample)

    def test_first_short_turn_is_dropped_without_enrollment(self):
        diarizer = StubSortformerDiarizer([["0.00 1.00 speaker_0"]])
        voice = (np.ones(16000, dtype=np.int16) * 1000).tobytes()

        segments = diarizer._process_pcm_window(voice)

        self.assertEqual([], segments)
        self.assertEqual(0, diarizer._registry.profile_count)

    def test_first_short_turn_is_dropped_when_embedding_fails(self):
        def fail_embedding(pcm_float, sample_rate):
            del pcm_float, sample_rate
            raise RuntimeError("embedding unavailable")

        diarizer = StubSortformerDiarizer([["0.00 1.00 speaker_0"]])
        diarizer._embedding_extractor = fail_embedding
        voice = (np.ones(16000, dtype=np.int16) * 1000).tobytes()

        segments = diarizer._process_pcm_window(voice)

        self.assertEqual([], segments)
        self.assertEqual({}, diarizer._speaker_map)

    def test_enrollment_does_not_change_short_embedding_failure_behavior(self):
        registry = SpeakerRegistry(threshold=0.9)
        registry.enroll(
            LOCAL_VOICE_PROFILE_ID,
            np.array([1.0, 0.0], dtype=np.float32),
            fallback_for_unmatched=False,
        )

        def fail_embedding(pcm_float, sample_rate):
            del pcm_float, sample_rate
            raise RuntimeError("embedding unavailable")

        diarizer = StubSortformerDiarizer(
            [["0.00 1.00 speaker_0"]],
            registry=registry,
        )
        diarizer._embedding_extractor = fail_embedding
        voice = (np.ones(16000, dtype=np.int16) * 1000).tobytes()

        segments = diarizer._process_pcm_window(voice)

        self.assertEqual([], segments)
        self.assertEqual({}, diarizer._speaker_map)

    def test_extracts_turns_from_rttm_lines(self):
        result = [
            "SPEAKER sample 1 0.50 1.25 <NA> <NA> speaker_0 <NA> <NA>",
            "SPEAKER sample 1 2.00 0.75 <NA> <NA> speaker_1 <NA> <NA>",
        ]

        turns = extract_sortformer_turns(result)

        self.assertEqual(2, len(turns))
        self.assertEqual((0.5, 1.75, "speaker_0"), (turns[0].start_seconds, turns[0].end_seconds, turns[0].label))
        self.assertEqual((2.0, 2.75, "speaker_1"), (turns[1].start_seconds, turns[1].end_seconds, turns[1].label))

    def test_extracts_turns_from_simple_label_lines(self):
        result = ["0.00 1.00 speaker_a", "1.50 2.25 speaker_b"]

        turns = extract_sortformer_turns(result)

        self.assertEqual(
            [(0.0, 1.0, "speaker_a"), (1.5, 2.25, "speaker_b")],
            [(turn.start_seconds, turn.end_seconds, turn.label) for turn in turns],
        )

    def test_stitches_reused_sortformer_window_labels_by_voice_embedding(self):
        diarizer = StubSortformerDiarizer([
            ["0.00 4.00 speaker_0"],
            ["0.00 4.00 speaker_0"],
        ])
        first_voice = (np.ones(64000, dtype=np.int16) * 1000).tobytes()
        second_voice = (np.ones(64000, dtype=np.int16) * -1000).tobytes()

        first_segments = diarizer._process_pcm_window(first_voice)
        second_segments = diarizer._process_pcm_window(second_voice)

        self.assertEqual("auto_1", first_segments[0].speaker_id)
        self.assertEqual("auto_2", second_segments[0].speaker_id)


if __name__ == "__main__":
    unittest.main()

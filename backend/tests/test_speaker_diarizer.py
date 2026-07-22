import unittest
from unittest.mock import Mock, patch

import numpy as np

from app.services.speaker_diarizer import (
    DiarizedSegment,
    SpeakerDiarizer,
    SpeakerRegistry,
    VoiceActivityDetector,
)


def embedding(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def pcm(seconds: float, value: int = 1) -> bytes:
    return np.full(int(16000 * seconds), value, dtype=np.int16).tobytes()


def finalize(diarizer: SpeakerDiarizer, audio: bytes, embeddings: list[np.ndarray]):
    diarizer._current_segment.extend(audio)
    with patch(
        "app.services.speaker_diarizer._extract_embedding",
        side_effect=embeddings,
    ) as extract:
        return diarizer._finalize_segment(), extract


class SpeakerDiarizerTests(unittest.TestCase):
    def test_first_short_segment_is_dropped_without_enrollment(self):
        registry = SpeakerRegistry(threshold=0.68)
        diarizer = SpeakerDiarizer(registry=registry)

        segments, _ = finalize(diarizer, pcm(2.0), [embedding(1.0, 0.0)])

        self.assertEqual([], segments)
        self.assertEqual(0, registry.profile_count)

    def test_matched_fast_path_updates_profile_without_windows(self):
        registry = SpeakerRegistry(threshold=0.68)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)

        segments, extract = finalize(
            diarizer,
            pcm(6.0),
            [embedding(0.9, 0.43589)],
        )

        self.assertEqual(["auto_1"], [segment.speaker_id for segment in segments])
        self.assertEqual(1, extract.call_count)
        self.assertEqual(2, registry._profiles[0].sample_count)

    def test_coherent_unmatched_turn_enrolls_one_new_profile(self):
        registry = SpeakerRegistry(threshold=0.68)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)

        segments, extract = finalize(
            diarizer,
            pcm(6.0),
            [
                embedding(0.0, 1.0),
                embedding(0.10, 0.995),
                embedding(0.20, 0.980),
            ],
        )

        self.assertEqual(["auto_2"], [segment.speaker_id for segment in segments])
        self.assertEqual(2, registry.profile_count)
        self.assertEqual(3, extract.call_count)

    def test_mixed_turn_splits_without_enrollment_or_pcm_loss(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        registry.enroll("auto_2", embedding(0.0, 1.0))
        diarizer = SpeakerDiarizer(registry=registry)
        audio = pcm(3.0, 1) + pcm(3.0, 2)

        segments, _ = finalize(
            diarizer,
            audio,
            [embedding(1.0, 1.0), embedding(1.0, 0.0), embedding(0.0, 1.0)],
        )

        self.assertEqual(["auto_1", "auto_2"], [segment.speaker_id for segment in segments])
        self.assertEqual(audio, b"".join(segment.pcm_bytes for segment in segments))
        self.assertEqual(2, registry.profile_count)

    def test_split_groups_use_normalized_window_means(self):
        class RecordingRegistry(SpeakerRegistry):
            def __init__(self):
                super().__init__(threshold=0.90)
                self.forced: list[np.ndarray] = []

            def match_or_create(self, value, allow_create=True):
                if not allow_create:
                    self.forced.append(value.copy())
                return super().match_or_create(value, allow_create=allow_create)

        registry = RecordingRegistry()
        registry.enroll("auto_1", embedding(1.0, 0.0))
        registry.enroll("auto_2", embedding(0.0, 1.0))
        diarizer = SpeakerDiarizer(registry=registry)
        windows = [
            embedding(1.0, 0.1),
            embedding(1.0, 0.2),
            embedding(0.1, 1.0),
            embedding(0.2, 1.0),
        ]

        segments, _ = finalize(
            diarizer,
            pcm(12.0),
            [embedding(1.0, 1.0), *windows],
        )

        expected = []
        for group in (windows[:2], windows[2:]):
            mean = np.mean(group, axis=0)
            expected.append(mean / np.linalg.norm(mean))
        self.assertEqual(["auto_1", "auto_2"], [segment.speaker_id for segment in segments])
        self.assertEqual(2, len(registry.forced))
        np.testing.assert_allclose(expected, registry.forced, atol=1e-6)

    def test_short_tail_is_merged_into_previous_window(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)
        lengths: list[int] = []

        def extract(samples, sample_rate):
            self.assertEqual(16000, sample_rate)
            lengths.append(len(samples))
            return embedding(0.0, 1.0) if len(lengths) == 1 else embedding(1.0, 0.0)

        diarizer._current_segment.extend(pcm(6.5))
        with patch("app.services.speaker_diarizer._extract_embedding", side_effect=extract):
            diarizer._finalize_segment()

        self.assertEqual([104000, 48000, 56000], lengths)

    def test_split_groups_assigned_to_same_profile_are_merged(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)
        audio = pcm(6.0)

        segments, _ = finalize(
            diarizer,
            audio,
            [embedding(0.0, 1.0), embedding(1.0, 0.0), embedding(-1.0, 0.0)],
        )

        self.assertEqual(1, len(segments))
        self.assertEqual("auto_1", segments[0].speaker_id)
        self.assertEqual(audio, segments[0].pcm_bytes)
        self.assertEqual(1, registry.profile_count)

    def test_first_and_short_segments_skip_window_analysis(self):
        cases = [
            (SpeakerRegistry(threshold=0.90), pcm(6.0)),
            (SpeakerRegistry(threshold=0.90), pcm(2.0)),
        ]
        cases[1][0].enroll("auto_1", embedding(1.0, 0.0))

        for registry, audio in cases:
            with self.subTest(profile_count=registry.profile_count, seconds=len(audio) / 32000):
                diarizer = SpeakerDiarizer(registry=registry)
                segments, extract = finalize(diarizer, audio, [embedding(0.0, 1.0)])
                self.assertEqual(1, len(segments))
                self.assertEqual(1, extract.call_count)

    def test_window_embedding_failure_falls_back_to_full_segment(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)
        audio = pcm(6.0)
        diarizer._current_segment.extend(audio)

        with patch(
            "app.services.speaker_diarizer._extract_embedding",
            side_effect=[embedding(0.0, 1.0), RuntimeError("window failed")],
        ):
            segments = diarizer._finalize_segment()

        self.assertEqual(1, len(segments))
        self.assertEqual(audio, segments[0].pcm_bytes)
        self.assertEqual(2, registry.profile_count)

    def test_invalid_mixed_group_fallback_is_non_mutating(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)
        audio = pcm(6.0)

        segments, _ = finalize(
            diarizer,
            audio,
            [
                embedding(0.0, 1.0),
                embedding(1.0, 0.0),
                np.zeros(2, dtype=np.float32),
            ],
        )

        self.assertEqual(
            (1, 1, ["auto_1"]),
            (
                registry.profile_count,
                registry._profiles[0].sample_count,
                [segment.speaker_id for segment in segments],
            ),
        )
        self.assertEqual(audio, b"".join(segment.pcm_bytes for segment in segments))

    def test_mixed_first_appearance_waits_for_clean_turn_before_enrolling(self):
        registry = SpeakerRegistry(threshold=0.90)
        first = embedding(1.0, 0.0)
        second = embedding(0.0, 1.0)
        third = embedding(-1.0, 0.0)
        registry.enroll("auto_1", first)
        registry.enroll("auto_2", second)
        diarizer = SpeakerDiarizer(registry=registry)

        mixed, _ = finalize(
            diarizer,
            pcm(6.0),
            [embedding(1.0, 1.0), first, third],
        )
        self.assertEqual(2, registry.profile_count)
        self.assertEqual(["auto_1", "auto_2"], [segment.speaker_id for segment in mixed])

        clean, _ = finalize(
            diarizer,
            pcm(6.0),
            [third, third, third],
        )
        self.assertEqual(["auto_3"], [segment.speaker_id for segment in clean])
        self.assertEqual(3, registry.profile_count)

        later_mix, _ = finalize(
            diarizer,
            pcm(6.0),
            [embedding(-1.0, 1.0), second, third],
        )
        self.assertEqual(["auto_2", "auto_3"], [segment.speaker_id for segment in later_mix])
        self.assertEqual(3, registry.profile_count)

    def test_feed_audio_extends_all_finalized_pieces(self):
        diarizer = SpeakerDiarizer()
        diarizer._max_segment_samples = VoiceActivityDetector.FRAME_SAMPLES
        diarizer._vad.process_frame = Mock(return_value=1.0)
        pieces = [DiarizedSegment("auto_1", b"a"), DiarizedSegment("auto_2", b"b")]
        diarizer._finalize_segment = Mock(return_value=pieces)

        self.assertEqual(pieces, diarizer.feed_audio(bytes(VoiceActivityDetector.FRAME_SAMPLES * 2)))

    def test_feed_audio_silence_gap_extends_all_finalized_pieces(self):
        diarizer = SpeakerDiarizer()
        diarizer._silence_gap_samples = VoiceActivityDetector.FRAME_SAMPLES
        diarizer._vad.process_frame = Mock(side_effect=[1.0, 0.0])
        pieces = [DiarizedSegment("auto_1", b"a"), DiarizedSegment("auto_2", b"b")]
        diarizer._finalize_segment = Mock(return_value=pieces)
        two_frames = bytes(VoiceActivityDetector.FRAME_SAMPLES * 2 * 2)

        self.assertEqual(pieces, diarizer.feed_audio(two_frames))

    def test_flush_segments_returns_every_tail_piece(self):
        diarizer = SpeakerDiarizer()
        diarizer._current_segment.extend(pcm(1.0))
        pieces = [DiarizedSegment("auto_1", b"a"), DiarizedSegment("auto_2", b"b")]
        diarizer._finalize_segment = Mock(return_value=pieces)

        self.assertEqual(pieces, diarizer.flush_segments())

    def test_legacy_flush_preserves_every_tail_byte_in_one_segment(self):
        pieces = [DiarizedSegment("auto_1", b"a"), DiarizedSegment("auto_2", b"b")]
        legacy = SpeakerDiarizer()
        legacy._current_segment.extend(pcm(1.0))
        legacy._finalize_segment = Mock(return_value=pieces)
        batch = SpeakerDiarizer()
        batch._current_segment.extend(pcm(1.0))
        batch._finalize_segment = Mock(return_value=pieces)

        self.assertEqual(DiarizedSegment("auto_1", b"ab"), legacy.flush())
        self.assertEqual(pieces, batch.flush_segments())


if __name__ == "__main__":
    unittest.main()

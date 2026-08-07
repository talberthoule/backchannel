import unittest
from unittest.mock import Mock, patch

import numpy as np
import onnxruntime as ort

from app.config import Settings, _default_embed_threads, settings
from app.services import speaker_diarizer
from app.services.speaker_diarizer import (
    DiarizedSegment,
    SpeakerDiarizer,
    SpeakerRegistry,
    VoiceActivityDetector,
    _embed_session_options,
    _vad_session_options,
)
from app.services.voice_enrollment import LOCAL_VOICE_PROFILE_ID


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
    def test_segment_records_source_start_after_leading_silence(self):
        diarizer = SpeakerDiarizer()
        frame_samples = VoiceActivityDetector.FRAME_SAMPLES
        diarizer._min_segment_samples = 0
        diarizer._min_new_speaker_samples = 0
        diarizer._max_segment_samples = frame_samples
        diarizer._vad.process_frame = Mock(side_effect=[0.0, 0.0, 1.0])
        three_frames = bytes(frame_samples * 2 * 3)

        with patch(
            "app.services.speaker_diarizer._extract_embedding",
            return_value=embedding(1.0, 0.0),
        ):
            segments = diarizer.feed_audio(three_frames)

        self.assertEqual(1, len(segments))
        self.assertEqual(2 * frame_samples, segments[0].start_sample)

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

    def test_enrollment_preserves_first_long_unmatched_participant(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll(
            LOCAL_VOICE_PROFILE_ID,
            embedding(1.0, 0.0),
            fallback_for_unmatched=False,
        )
        diarizer = SpeakerDiarizer(registry=registry)

        segments, _ = finalize(
            diarizer,
            pcm(6.0),
            [
                embedding(0.0, 1.0),
                embedding(0.0, 1.0),
                embedding(0.0, -1.0),
            ],
        )

        self.assertEqual(["auto_1"], [segment.speaker_id for segment in segments])
        self.assertEqual(2, registry.profile_count)

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


class DiarizerThreadPoolTests(unittest.TestCase):
    """ALP-289: both ONNX sessions get a tuned pool instead of ORT's default."""

    def test_vad_session_is_single_threaded(self):
        self.assertEqual(1, _vad_session_options().intra_op_num_threads)

    def test_embed_session_bounds_the_pool_and_parks_it_between_calls(self):
        options = _embed_session_options()

        self.assertEqual(settings.DIARIZER_EMBED_ONNX_THREADS, options.intra_op_num_threads)
        self.assertEqual(
            "0",
            options.get_session_config_entry("session.intra_op.allow_spinning"),
        )

    def test_embed_thread_default_scales_with_the_host_and_never_reaches_zero(self):
        # The floor matters more than the ceiling: ORT reads 0 as "use every
        # core", so losing it would silently restore the default pool on the
        # smallest hosts - and on a 4-core CI runner a bounds-only assertion
        # cannot tell scaling from a hardcoded constant.
        self.assertEqual(
            [1, 1, 1, 1, 2, 4, 4, 4],
            [_default_embed_threads(n) for n in (None, 0, 1, 2, 4, 8, 28, 128)],
        )

    def test_supplied_thread_counts_are_clamped_out_of_ort_default_territory(self):
        for supplied, expected in ((0, 1), (-8, 1), (1, 1), (2, 2), (6, 6)):
            with self.subTest(supplied=supplied):
                configured = Settings(
                    DIARIZER_EMBED_ONNX_THREADS=supplied,
                    DIARIZER_VAD_ONNX_THREADS=supplied,
                )
                self.assertEqual(expected, configured.DIARIZER_EMBED_ONNX_THREADS)
                self.assertEqual(expected, configured.DIARIZER_VAD_ONNX_THREADS)

    def test_spinning_can_be_handed_back_to_ort(self):
        with patch.object(settings, "DIARIZER_EMBED_ONNX_SPIN", True):
            options = _embed_session_options()

        with self.assertRaises(RuntimeError):
            options.get_session_config_entry("session.intra_op.allow_spinning")


class DiarizerSessionWiringTests(unittest.TestCase):
    """The options must actually reach ORT, not merely be constructible.

    Dropping the options argument from either InferenceSession call reverts
    all of ALP-289 while leaving the builders above perfectly green.
    """

    def _construct(self, getter, attribute):
        original = getattr(speaker_diarizer, attribute)
        setattr(speaker_diarizer, attribute, None)
        self.addCleanup(setattr, speaker_diarizer, attribute, original)
        with patch("app.services.speaker_diarizer.ort.InferenceSession") as session:
            getter()
        self.assertEqual(1, session.call_count)
        args, kwargs = session.call_args
        self.assertEqual(
            2, len(args), "session options must reach InferenceSession positionally"
        )
        self.assertIsInstance(args[1], ort.SessionOptions)
        self.assertEqual(["CPUExecutionProvider"], kwargs["providers"])
        return args[1]

    def test_vad_session_is_built_with_the_single_threaded_options(self):
        options = self._construct(speaker_diarizer._get_vad_model, "_vad_session")

        self.assertEqual(settings.DIARIZER_VAD_ONNX_THREADS, options.intra_op_num_threads)

    def test_embed_session_is_built_with_the_bounded_pool_options(self):
        options = self._construct(speaker_diarizer._get_embed_model, "_embed_session")

        self.assertEqual(settings.DIARIZER_EMBED_ONNX_THREADS, options.intra_op_num_threads)
        self.assertEqual(
            "0",
            options.get_session_config_entry("session.intra_op.allow_spinning"),
        )


class FrameLoopTests(unittest.TestCase):
    """ALP-290: the per-frame loop pays only for what the frame needs."""

    def test_in_place_drain_yields_every_frame_in_order_with_a_clean_remainder(self):
        diarizer = SpeakerDiarizer()
        frame_samples = VoiceActivityDetector.FRAME_SAMPLES
        buffer = diarizer._pending_audio
        values = [100, 200, 300, 400, 500]
        remainder = np.full(frame_samples // 2, 999, dtype=np.int16).tobytes()
        audio = b"".join(
            np.full(frame_samples, value, dtype=np.int16).tobytes() for value in values
        ) + remainder
        seen: list[int] = []

        def record(frame_float):
            # Every sample in a frame carries that frame's value, and 32768 is
            # a power of two, so the round trip through float32 is exact.
            self.assertEqual(frame_samples, len(frame_float))
            seen.append(int(frame_float[0] * 32768.0))
            return 0.0

        diarizer._vad.process_frame = record
        # Deliberately unaligned chunks: frames must still be carved on
        # 1024-byte boundaries no matter how the input is split.
        for start in range(0, len(audio), 777):
            diarizer.feed_audio(audio[start:start + 777])

        self.assertEqual(values, seen)
        self.assertEqual(remainder, bytes(diarizer._pending_audio))
        self.assertEqual(len(values) * frame_samples, diarizer._processed_samples)
        # Drained in place rather than rebound to a fresh copy per frame.
        self.assertIs(buffer, diarizer._pending_audio)

    def test_a_broken_embedder_still_emits_every_segment(self):
        # A deployment whose embedding model never loads - no download_models
        # run, a truncated file, an ORT load failure - never enrolls anyone, so
        # profile_count stays 0 for the whole call. Short turns must still
        # reach transcription as unknown-speaker audio; dropping them would be
        # silent data loss visible only as a log line.
        registry = SpeakerRegistry(threshold=0.68)
        diarizer = SpeakerDiarizer(registry=registry)
        short = pcm(2.0)  # below MIN_NEW_SPEAKER_MS, so it cannot enroll
        long = pcm(6.0)
        emitted: list[DiarizedSegment] = []

        for audio in (short, long):
            diarizer._current_segment.extend(audio)
            with patch(
                "app.services.speaker_diarizer._extract_embedding",
                side_effect=RuntimeError("embedding model missing"),
            ):
                emitted.extend(diarizer._finalize_segment())

        self.assertEqual(
            ["auto_unknown", "auto_unknown"], [segment.speaker_id for segment in emitted]
        )
        self.assertEqual(short + long, b"".join(segment.pcm_bytes for segment in emitted))
        self.assertEqual(0, registry.profile_count)

    def test_diagnostic_counters_exist_before_any_audio_arrives(self):
        diarizer = SpeakerDiarizer()

        self.assertEqual(
            (0, 0.0, 0.0),
            (diarizer._diag_frames, diarizer._diag_max_prob, diarizer._diag_max_energy),
        )

    def test_diagnostic_window_reports_loudest_rms_then_rolls_over(self):
        diarizer = SpeakerDiarizer()
        frame_samples = VoiceActivityDetector.FRAME_SAMPLES
        diarizer._vad.process_frame = Mock(return_value=0.0)
        quiet = np.full(frame_samples, 5, dtype=np.int16).tobytes()
        # A single full-scale sample: the click that peak amplitude cannot
        # tell from a loud room. Its RMS is only 0.044, well under the frame
        # below, so it must not win the window.
        click = np.zeros(frame_samples, dtype=np.int16)
        click[0] = 32767
        # Negative frame: RMS squares, so this is genuinely the loudest one.
        # A signed max would read it as near-silence instead.
        loud = np.full(frame_samples, -8000, dtype=np.int16).tobytes()

        with self.assertLogs("app.services.speaker_diarizer", level="INFO") as logs:
            diarizer.feed_audio(quiet * 310 + click.tobytes() + loud)

        # Every sample in the loud frame shares one magnitude, so its RMS is
        # exactly 8000/32768 - the same figure the pre-ALP-290 code reported,
        # which keeps remembered thresholds meaningful.
        self.assertIn(f"max_rms={8000 / 32768.0:.4f}", logs.output[0])
        self.assertEqual(
            (0, 0.0, 0.0),
            (diarizer._diag_frames, diarizer._diag_max_prob, diarizer._diag_max_energy),
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from app.services.diarizer_selection import (
    DIARIZER_LIGHTWEIGHT,
    DIARIZER_SORTFORMER,
    flush_diarizer_segments,
    resolve_effective_diarizer_mode,
    sortformer_is_selectable,
)


class DiarizerSelectionTests(unittest.TestCase):
    def test_passed_benchmark_unlocks_sortformer_selection(self):
        self.assertTrue(
            sortformer_is_selectable(
                benchmark_status="passed",
                sortformer_available=True,
                benchmark_real_time_factor=0.2,
            )
        )

    def test_old_pass_is_not_selectable_when_rtf_misses_current_requirement(self):
        self.assertFalse(
            sortformer_is_selectable(
                benchmark_status="passed",
                sortformer_available=True,
                benchmark_real_time_factor=0.60,
            )
        )

    def test_zero_duration_measurement_does_not_unlock_sortformer(self):
        self.assertFalse(sortformer_is_selectable("passed", True, 0.0))

    def test_sortformer_selection_falls_back_without_passed_benchmark(self):
        self.assertEqual(
            DIARIZER_LIGHTWEIGHT,
            resolve_effective_diarizer_mode(
                selected_mode=DIARIZER_SORTFORMER,
                benchmark_status="failed",
                sortformer_available=True,
                benchmark_real_time_factor=0.60,
            ),
        )

    def test_sortformer_selection_is_effective_after_passed_benchmark(self):
        self.assertEqual(
            DIARIZER_SORTFORMER,
            resolve_effective_diarizer_mode(
                selected_mode=DIARIZER_SORTFORMER,
                benchmark_status="passed",
                sortformer_available=True,
                benchmark_real_time_factor=0.20,
            ),
        )

    def test_unknown_selection_uses_default_lightweight_mode(self):
        self.assertEqual(
            DIARIZER_LIGHTWEIGHT,
            resolve_effective_diarizer_mode(
                selected_mode="unknown",
                benchmark_status="passed",
                sortformer_available=True,
                benchmark_real_time_factor=0.20,
            ),
        )

    def test_flush_diarizer_segments_uses_batch_flush_when_available(self):
        class BatchFlushDiarizer:
            def flush_segments(self):
                return ["first", "second"]

        self.assertEqual(["first", "second"], flush_diarizer_segments(BatchFlushDiarizer()))

    def test_flush_diarizer_segments_wraps_single_flush_result(self):
        class SingleFlushDiarizer:
            def flush(self):
                return "only"

        self.assertEqual(["only"], flush_diarizer_segments(SingleFlushDiarizer()))


if __name__ == "__main__":
    unittest.main()

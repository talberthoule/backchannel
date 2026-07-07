import unittest

from app.services.batch_transcriber import _is_hallucination
from app.services.speaker_ghost_filter import should_defer_new_speaker_segment
from app.routers.imports import should_skip_import_ghost_speaker_segment


class GhostTranscriptFilterTests(unittest.TestCase):
    def test_filters_common_video_intro_hallucination(self):
        self.assertTrue(_is_hallucination("What is up YouTube and welcome back"))

    def test_defers_short_one_off_new_speaker_fragments(self):
        pcm_bytes = b"\x01\x00" * (16000 * 2)

        self.assertTrue(
            should_defer_new_speaker_segment(
                pcm_bytes,
                "you'll over-rotate and end up with something that doesn't look as good.",
            )
        )

    def test_allows_longer_new_speaker_segments(self):
        pcm_bytes = b"\x01\x00" * (16000 * 5)

        self.assertFalse(
            should_defer_new_speaker_segment(
                pcm_bytes,
                "No, I think you teed it up very well from what I heard and we have talked through the approach.",
            )
        )

    def test_import_defers_short_segment_that_would_create_new_speaker(self):
        pcm_bytes = b"\x01\x00" * (16000 * 2)

        self.assertTrue(
            should_skip_import_ghost_speaker_segment(
                auto_id="auto_2",
                auto_speaker_map={"auto_1": "known-speaker"},
                speakers=[],
                pcm_bytes=pcm_bytes,
                text="quick fragment",
            )
        )

    def test_import_keeps_short_segment_for_already_mapped_speaker(self):
        pcm_bytes = b"\x01\x00" * (16000 * 2)

        self.assertFalse(
            should_skip_import_ghost_speaker_segment(
                auto_id="auto_1",
                auto_speaker_map={"auto_1": "known-speaker"},
                speakers=[],
                pcm_bytes=pcm_bytes,
                text="quick fragment",
            )
        )


if __name__ == "__main__":
    unittest.main()

"""Decoder-loop and bracket-junk lines from a local Whisper on noise are
dropped before they reach the transcript, and the transcriber logs carry no
words."""

import logging
import unittest

from app.services.batch_transcriber import filter_transcript_text


class RepetitionTests(unittest.TestCase):
    def test_a_phrase_said_over_and_over_is_dropped(self):
        self.assertIsNone(filter_transcript_text("Oh, my God. " * 8))
        self.assertIsNone(filter_transcript_text("In " * 40))
        self.assertIsNone(filter_transcript_text("This is a... A... A... A... A... A... A... A... A... A..."))

    def test_bracketed_non_words_are_dropped(self):
        self.assertIsNone(filter_transcript_text("[S] [S] [S] [S] [S] [S]"))
        self.assertIsNone(filter_transcript_text("[BLANK_AUDIO]"))

    def test_real_speech_with_some_repetition_survives(self):
        kept = "I really, really think we should ship this, and I mean really ship it this week."
        self.assertEqual(filter_transcript_text(kept), kept)
        short = "Yes, yes, yes."  # three words, below the loop threshold
        self.assertEqual(filter_transcript_text(short), short)
        tokens = "[PERSON_1] asked [PERSON_2] and [ORG_1] about the renewal"
        self.assertEqual(filter_transcript_text(tokens), tokens)

    def test_logs_record_length_not_words(self):
        with self.assertLogs("app.services.batch_transcriber", level="INFO") as captured:
            filter_transcript_text("Oh, my God. " * 8)
            filter_transcript_text("hi")
        joined = "\n".join(captured.output)
        self.assertNotIn("God", joined)
        self.assertIn("chars", joined)


if __name__ == "__main__":
    unittest.main()

"""Duplicate-utterance suppression for live transcripts (ALP-301).

The fixtures are real consecutive pairs from session 343339c5, where 462 of
1189 entries were near-duplicates of the entry before them. Each pair is the
same speech transcribed twice, which is why the wording drifts between the two
copies rather than matching exactly.
"""

import unittest

from app.services.transcript_dedup import (
    LiveTranscriptDeduper,
    build_transcript_deduper,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def deduper(clock=None, window=10.0, similarity=0.7, min_words=5):
    return LiveTranscriptDeduper(
        window_seconds=window,
        similarity=similarity,
        min_words=min_words,
        clock=clock or FakeClock(),
    )


class RealDuplicatePairTests(unittest.TestCase):
    def test_verbatim_repeat_is_suppressed(self):
        d = deduper()
        self.assertTrue(d.admit("seen this now on a number of decks"))
        self.assertFalse(d.admit("seen this now on a number of decks"))

    def test_reheard_wording_drift_is_still_caught(self):
        # The twin is transcribed independently, so it is rarely identical.
        d = deduper()
        self.assertTrue(d.admit("the pure play cloud providers on the left"))
        self.assertFalse(d.admit("the peer-to-peer cloud providers on the left."))

    def test_partial_containment_is_caught(self):
        """One copy often starts late and is a subset of the other.

        This is why the metric divides by the shorter side: Jaccard scores this
        pair at 0.55 and would let the duplicate through.
        """
        d = deduper()
        self.assertTrue(
            d.admit("right just numbers stuff, but this this is a slide that you're going to start seeing")
        )
        self.assertFalse(
            d.admit("uh, or I guess number stuff. But this this is a slide that you're going to start seeing.")
        )

    def test_a_third_copy_is_also_suppressed(self):
        # admit() records only what it admits, so the surviving first copy
        # keeps matching against every later twin.
        d = deduper()
        self.assertTrue(d.admit("seen this now on a number of decks"))
        self.assertFalse(d.admit("seen this now on a number of decks"))
        self.assertFalse(d.admit("seen this now on a number of decks"))


class GenuineSpeechIsKeptTests(unittest.TestCase):
    def test_different_utterances_both_survive(self):
        d = deduper()
        self.assertTrue(d.admit("the pure play cloud providers on the left"))
        self.assertTrue(d.admit("what does the renewal timeline look like for that contract"))

    def test_short_backchannels_are_never_suppressed(self):
        """Two people saying "yeah, exactly" is conversation, not duplication."""
        d = deduper()
        for _ in range(5):
            self.assertTrue(d.admit("yeah exactly"))

    def test_short_utterances_do_not_crowd_the_window(self):
        # Backchannels are not remembered either; if they were, a run of them
        # could sit in the window and mask a real duplicate.
        clock = FakeClock()
        d = deduper(clock)
        d.admit("seen this now on a number of decks")
        for _ in range(50):
            d.admit("yeah okay")
        self.assertFalse(d.admit("seen this now on a number of decks"))

    def test_a_genuine_repeat_after_the_window_is_kept(self):
        # Saying the same thing ten minutes later is real speech, not a twin.
        clock = FakeClock()
        d = deduper(clock)
        self.assertTrue(d.admit("seen this now on a number of decks"))
        clock.advance(600)
        self.assertTrue(d.admit("seen this now on a number of decks"))

    def test_the_window_covers_the_observed_gap(self):
        # Measured pair gaps ran to a p90 of 3.8 seconds.
        clock = FakeClock()
        d = deduper(clock)
        self.assertTrue(d.admit("the pure play cloud providers on the left"))
        clock.advance(3.8)
        self.assertFalse(d.admit("the pure play cloud providers on the left"))

    def test_empty_and_whitespace_text_is_harmless(self):
        d = deduper()
        self.assertTrue(d.admit(""))
        self.assertTrue(d.admit("   "))
        self.assertTrue(d.admit(None))


class SettingsTests(unittest.TestCase):
    def test_disabled_setting_yields_a_pass_through(self):
        class Off:
            TRANSCRIPT_DEDUP_ENABLED = False

        d = build_transcript_deduper(Off())
        self.assertTrue(d.admit("seen this now on a number of decks"))
        self.assertTrue(d.admit("seen this now on a number of decks"))

    def test_enabled_setting_builds_a_real_deduper(self):
        class On:
            TRANSCRIPT_DEDUP_ENABLED = True
            TRANSCRIPT_DEDUP_WINDOW_SECONDS = 10.0
            TRANSCRIPT_DEDUP_SIMILARITY = 0.7
            TRANSCRIPT_DEDUP_MIN_WORDS = 5

        d = build_transcript_deduper(On())
        self.assertTrue(d.admit("seen this now on a number of decks"))
        self.assertFalse(d.admit("seen this now on a number of decks"))

    def test_shipped_defaults_suppress_the_measured_pairs(self):
        from app.config import settings

        d = build_transcript_deduper(settings)
        self.assertTrue(d.admit("the pure play cloud providers on the left"))
        self.assertFalse(d.admit("the peer-to-peer cloud providers on the left."))


if __name__ == "__main__":
    unittest.main()

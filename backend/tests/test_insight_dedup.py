"""Emission-time near-duplicate suppression (ALP-286).

The reference meeting (session 99985052, 57 minutes, internal_checkin) produced
199 insights, and the synthesizer later merged 21 of them away as duplicates.
The median gap between a merged pair was 1.0 minute and 90 percent were within
2.1 minutes, so the old 60-second window structurally could not see 13 of the
21 -- they were caught afterwards by the synthesizer at full corpus cost.

The pairs below are real insight texts from that meeting.
"""

import time
import unittest

from app.services.agents.orchestrator import _DEDUP_WINDOW_SECONDS, _texts_similar

# (earlier text, later text, gap in seconds) drawn from the reference meeting.
MERGED_PAIRS = [
    (
        "Develop standardized AI governance enablement playbooks and reusable artifact"
        " repositories to streamline project onboarding",
        "Develop an internal AI Governance Enablement Playbook and reusable artifact"
        " repository to streamline project onboarding",
        54,
    ),
    (
        "The organization uses a three-stage agile go-to-market model for AI topics,"
        " funneling field patterns into bi-weekly 30-minute pitch sessions",
        "The organization uses a multi-stage agile go-to-market model for AI topics,"
        " funneling field patterns into bi-weekly 30-minute pitch sessions",
        66,
    ),
    (
        "Develop a standardized cross-practice enablement framework and pitch repository"
        " for field CTOs covering Cyber, Total Experience",
        "Develop a unified cross-practice enablement matrix and standard pitch/handoff"
        " guide for Field CTOs covering Cyber, Total Experience",
        60,
    ),
]


def _prune(recent: dict[str, float], now: float) -> dict[str, float]:
    """The window prune from _save_and_send_insight, isolated from the DB."""
    return {k: v for k, v in recent.items() if now - v < _DEDUP_WINDOW_SECONDS}


class DedupWindowTests(unittest.TestCase):
    def test_window_covers_the_observed_restatement_distribution(self):
        # 90 percent of merged pairs were within 2.1 minutes; the window needs
        # headroom past that or the synthesizer keeps paying to merge them.
        self.assertGreaterEqual(_DEDUP_WINDOW_SECONDS, 126)

    def test_real_restatements_are_caught_at_their_actual_gap(self):
        for earlier, later, gap in MERGED_PAIRS:
            with self.subTest(text=earlier[:40]):
                start = time.time()
                recent = {earlier: start}
                # Fast-forward to when the restatement actually arrived.
                surviving = _prune(recent, start + gap)
                self.assertIn(
                    earlier, surviving, "entry aged out before its restatement arrived"
                )
                self.assertTrue(_texts_similar(later, earlier))

    def test_the_old_sixty_second_window_would_have_missed_them(self):
        # Documents the regression this change fixes: at 60s, two of the three
        # pairs above had already aged out of the map when the restatement came.
        aged_out = [gap for _, _, gap in MERGED_PAIRS if gap >= 60]
        self.assertTrue(aged_out)

    def test_entries_still_age_out_eventually(self):
        start = time.time()
        recent = {"some insight text": start}
        self.assertEqual({}, _prune(recent, start + _DEDUP_WINDOW_SECONDS + 1))


class TextSimilarityTests(unittest.TestCase):
    def test_unrelated_insights_are_not_merged(self):
        self.assertFalse(
            _texts_similar(
                "Develop an internal AI Governance Enablement Playbook",
                "Budget approval for the data center refresh slipped to Q3",
            )
        )

    def test_empty_text_never_matches(self):
        self.assertFalse(_texts_similar("", "anything at all"))
        self.assertFalse(_texts_similar("anything at all", ""))


if __name__ == "__main__":
    unittest.main()

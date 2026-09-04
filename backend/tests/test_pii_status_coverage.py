"""What the Privacy tab's coverage rows are allowed to claim (ALP-366).

The refinement row used to render the Transcript Refiner's on/off switch
through the same green/red badge the genuinely privacy-bearing rows use, so a
disabled optional quality agent reported a privacy gap. It is not one: the
refiner is handed the stored, already-tokenized text and tokenized speaker
labels, keeps a rewrite only when the token multiset is identical, and has no
path to reveal_text. Coverage follows the shield's switch; enablement is a
detail line.
"""

import unittest
from types import SimpleNamespace

from app.services.pii import status
from app.services.transcript_refiner import REFINER_SLUG


def _settings(enabled: bool):
    return SimpleNamespace(enabled=enabled)


def _refiner(enabled=True, model_id="gemini-3.5-flash-lite", interval_seconds=45):
    return SimpleNamespace(
        slug=REFINER_SLUG,
        enabled=enabled,
        model_id=model_id,
        interval_seconds=interval_seconds,
    )


class RefinementCoverageTests(unittest.TestCase):
    def test_a_disabled_refiner_is_still_covered_while_the_shield_is_on(self):
        row = status.refinement_coverage(_settings(True), _refiner(enabled=False))
        self.assertTrue(row["covered"], "a stage that never sees a name is not a gap")
        self.assertFalse(row["enabled"])

    def test_a_cloud_model_does_not_break_coverage(self):
        # The whole point: the refiner reads tokens, so the destination of the
        # text does not change what it can expose.
        row = status.refinement_coverage(_settings(True), _refiner(model_id="gemini-3.6-flash"))
        self.assertTrue(row["covered"])
        self.assertTrue(row["enabled"])
        self.assertEqual("gemini-3.6-flash", row["model_id"])

    def test_a_missing_refiner_row_reports_defaults_not_a_crash(self):
        row = status.refinement_coverage(_settings(True), None)
        self.assertTrue(row["covered"])
        self.assertFalse(row["enabled"])
        self.assertEqual("", row["model_id"])
        self.assertEqual(45, row["interval_seconds"])

    def test_coverage_follows_the_shield_switch(self):
        row = status.refinement_coverage(_settings(False), _refiner())
        self.assertFalse(row["covered"], "with the shield off nothing is tokenized to protect")
        self.assertTrue(row["enabled"], "the agent still runs; only the claim changes")

    def test_enablement_is_no_longer_what_the_badge_reads(self):
        # The regression this issue exists for: on == covered, off == not
        # covered. Assert the two are now independent.
        on = status.refinement_coverage(_settings(True), _refiner(enabled=True))
        off = status.refinement_coverage(_settings(True), _refiner(enabled=False))
        self.assertEqual(on["covered"], off["covered"])
        self.assertNotEqual(on["enabled"], off["enabled"])


class RefinerCannotRevealTests(unittest.TestCase):
    """The premise behind the coverage claim, pinned as a test.

    If someone later teaches the refiner to reveal, this fails and the
    coverage rule above has to be revisited rather than quietly becoming a lie.
    """

    def test_the_refiner_module_never_reaches_the_reveal_boundary(self):
        import inspect

        from app.services import transcript_refiner

        source = inspect.getsource(transcript_refiner)
        self.assertNotIn("reveal_text", source)
        self.assertNotIn("reveal_map", source)


if __name__ == "__main__":
    unittest.main()

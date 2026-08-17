import unittest
from collections import Counter
from pathlib import Path
import sys

from PIL import Image

from showcase import seed_demo


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
from app.routers.offerings import _get_seed_data

SCREENSHOTS = REPO / "showcase" / "screenshots"
SHOTS = REPO / "site" / "assets" / "shots"

FULL = {
    "live-call": (1440, 900),
    "live-ask": (1440, 900),
    "live-objections": (1440, 900),
    "live-questions": (1440, 900),
    "postcall-briefing": (1440, 900),
    "postcall-signals": (1440, 900),
    "postcall-insights": (1440, 900),
    "postcall-attributed": (1440, 900),
    "postcall-transcript": (1440, 900),
    "postcall-speakers": (1440, 900),
    "postcall-chat": (1440, 900),
    "admin-agents": (1185, 900),
    "admin-transcription": (1185, 900),
    "admin-api-keys": (1185, 900),
    "admin-about": (1185, 900),
    "offerings-catalog": (1185, 900),
    "knowledge-sources": (1185, 900),
}
CROPS = {
    "live-answered": (940, 492),
    "insights-attributed": (1032, 542),
    "session-header": (1032, 208),
    "ask-bar": (1120, 58),
}
OG_CARD = REPO / "site" / "assets" / "og-image.png"
RETIRED_MARKERS = ("Northwind Logistics", "segmentation review", "cross-dock")
PUBLIC_TEXT = (
    REPO / "showcase" / "capture.mjs",
    REPO / "showcase" / "screenshots" / "README.md",
    REPO / "site" / "index.html",
)


class ShowcaseFixtureTests(unittest.TestCase):
    def test_demo_fixture_tells_the_alderwake_recovery_story(self):
        self.assertEqual("Alderwake Health Network", seed_demo.GROUP)
        self.assertIn("recovery readiness review", seed_demo.MAIN)
        self.assertEqual(
            Counter(
                {
                    "action_item": 5,
                    "objection": 4,
                    "opportunity": 4,
                    "observation": 5,
                    "question": 6,
                }
            ),
            Counter(row[0] for row in seed_demo.CURATED_INSIGHTS),
        )
        self.assertEqual(
            Counter(
                {
                    "action_item": 24,
                    "objection": 16,
                    "opportunity": 18,
                    "observation": 31,
                    "question": 34,
                    "asked": 2,
                }
            ),
            Counter(row[0] for row in seed_demo.INSIGHTS),
        )
        self.assertEqual(125, len(seed_demo.INSIGHTS))

        # Asked rows are what the product writes for a question put to the
        # running call: no speaker, starred, answered, and captioned with the
        # model that answered. See backend/app/routers/ask.py.
        for row in seed_demo.ASKED_INSIGHTS:
            item_type, source, _question, rationale, _context, who = row[:6]
            starred, answered = row[6], row[7]
            self.assertEqual("asked", item_type)
            self.assertEqual("live_chat", source)
            self.assertEqual("", who)
            self.assertTrue(starred)
            self.assertTrue(answered)
            self.assertTrue(rationale.startswith("Answered by "), rationale)

        # The live signal cards and the kept history are what "signals
        # persist" means on screen; both must survive a fixture edit.
        for section in ("strategic_signals", "risks_blockers", "action_plan",
                        "top_opportunities", "unresolved_discovery_questions"):
            self.assertTrue(seed_demo.LIVE_SIGNALS[section], section)
        self.assertGreaterEqual(len(seed_demo.SIGNAL_HISTORY), 5)

        current_story = repr(
            (
                seed_demo.GROUP,
                seed_demo.MAIN,
                seed_demo.SPEAKERS,
                seed_demo.LINES,
                seed_demo.INSIGHTS,
                seed_demo.OTHERS,
            )
        )
        for marker in RETIRED_MARKERS:
            self.assertNotIn(marker, current_story)

    def test_catalog_supports_the_recovery_services_story(self):
        offerings = _get_seed_data()
        product_names = {offering["product_name"] for offering in offerings}
        self.assertTrue(
            {
                "Recovery Readiness Assessment",
                "Recovery Implementation Pilot",
                "Managed Recovery Operations",
            }
            <= product_names
        )
        self.assertNotIn("In-House", {offering["vendor"] for offering in offerings})


class ShowcaseAssetTests(unittest.TestCase):
    def test_public_showcase_text_does_not_reference_the_retired_story(self):
        for path in PUBLIC_TEXT:
            text = path.read_text(encoding="utf8")
            for marker in RETIRED_MARKERS:
                self.assertNotIn(marker, text, path)

    def test_source_png_manifest_is_complete(self):
        expected = {
            f"{name}{suffix}.png"
            for name in FULL
            for suffix in ("", "-dark")
        }
        actual = {path.name for path in SCREENSHOTS.glob("*.png")}
        self.assertEqual(expected, actual)
        for name in expected:
            with Image.open(SCREENSHOTS / name) as image:
                self.assertEqual((1440, 900), image.size, name)

    def test_site_webp_manifest_and_dimensions_are_complete(self):
        expected = {
            f"{name}{suffix}.webp"
            for name in FULL | CROPS
            for suffix in ("", "-dark")
        }
        actual = {path.name for path in SHOTS.glob("*.webp")}
        self.assertEqual(expected, actual)
        for stem, dimensions in (FULL | CROPS).items():
            for suffix in ("", "-dark"):
                name = f"{stem}{suffix}.webp"
                with Image.open(SHOTS / name) as image:
                    self.assertEqual(dimensions, image.size, name)

    def test_og_card_is_a_generated_asset_at_card_size(self):
        """The share card is regenerable, so it cannot go stale unnoticed.

        The first one was hand-composed around a retired real-customer
        screenshot and survived that family's retirement by five weeks.
        """
        with Image.open(OG_CARD) as image:
            self.assertEqual((1200, 630), image.size)
        generator = (REPO / "showcase" / "og_card.mjs").read_text(encoding="utf8")
        self.assertIn("showcase/screenshots/live-call-dark.png", generator)


if __name__ == "__main__":
    unittest.main()

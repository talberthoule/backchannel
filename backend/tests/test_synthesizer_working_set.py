"""Synthesizer corpus serialization and the unchanged-corpus skip (ALP-283).

Sending every non-dismissed insight in full on every cycle made this agent 48
percent of a measured meeting's token bill (954,833 input tokens over 34
cycles), growing quadratically with call length. Live insights now keep a full
record; settled ones become stubs that merge/answer can still target by id.
"""

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.agents import synthesizer
from app.services.agents.event_bus import CooldownSubscriber
from app.services.agents.synthesizer import _build_insights_json

NOW = datetime(2026, 8, 3, 20, 0, 0, tzinfo=timezone.utc)


def insight(**overrides):
    created = overrides.pop("created_at", NOW)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        item_type="observation",
        question="The client is consolidating three vendors into one contract",
        rationale="Signals a competitive displacement window",
        source_context="They said they are tired of managing three separate renewals",
        speaker_id=uuid.uuid4(),
        speaker=SimpleNamespace(speaker_type="external"),
        answered=False,
        answer_summary="",
        starred=False,
        enrichment_notes="",
        agent_source="observer",
        created_at=created,
        updated_at=overrides.pop("updated_at", created),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def records(rows, now=NOW):
    return json.loads(_build_insights_json(rows, now=now))


class WorkingSetTests(unittest.TestCase):
    def test_recent_unanswered_insight_keeps_its_full_record(self):
        [item] = records([insight()])
        self.assertNotIn("settled", item)
        self.assertIn("rationale", item)
        self.assertEqual("external", item["speaker_type"])

    def test_settled_insight_collapses_to_a_stub(self):
        old = NOW - timedelta(hours=1)
        [item] = records([insight(answered=True, created_at=old)])
        self.assertTrue(item["settled"])
        self.assertNotIn("rationale", item)
        self.assertNotIn("agent_source", item)
        # Still addressable, so merge and answer can target it.
        self.assertIn("id", item)
        self.assertIn("item_type", item)

    def test_starred_insight_stays_live_even_once_answered(self):
        old = NOW - timedelta(hours=1)
        [item] = records([insight(answered=True, starred=True, created_at=old)])
        self.assertNotIn("settled", item)
        self.assertTrue(item["starred"])

    def test_unanswered_but_stale_insight_collapses(self):
        old = NOW - timedelta(seconds=5000)
        [item] = records([insight(created_at=old)])
        self.assertTrue(item["settled"])

    def test_recent_edit_pulls_a_stale_insight_back_in(self):
        old = NOW - timedelta(hours=2)
        [item] = records([insight(created_at=old, updated_at=NOW - timedelta(seconds=30))])
        self.assertNotIn("settled", item)

    def test_source_context_and_duplicate_speaker_id_are_never_sent(self):
        # No operation the prompt offers can write source_context, and the
        # speaker UUID was previously emitted twice per item.
        payload = _build_insights_json([insight()], now=NOW)
        self.assertNotIn("source_context", payload)
        self.assertNotIn("tired of managing three separate renewals", payload)
        self.assertNotIn("speaker_id", payload)

    def test_enrichment_notes_are_truncated_from_the_front_not_the_back(self):
        """The bound is unchanged; which end survives it is not.

        This originally asserted a trailing ellipsis, i.e. the head was kept.
        That is backwards for this field: _append_note in insight_refiner
        appends, so keeping the head meant that past the limit the model saw
        only its OLDEST notes and could never see what it wrote last cycle -
        no signal that it had already enriched an insight (ALP-297).
        """
        notes = "\n".join(f"note {i}" for i in range(1, 200))
        [item] = records([insight(enrichment_notes=notes)])
        self.assertLess(len(item["enrichment_notes"]), 250)
        self.assertTrue(item["enrichment_notes"].startswith("..."))
        self.assertIn("note 199", item["enrichment_notes"])
        self.assertNotIn("note 1\n", item["enrichment_notes"])

    def test_serialization_is_byte_stable_for_an_unchanged_corpus(self):
        rows = [insight(), insight(), insight()]
        self.assertEqual(
            _build_insights_json(rows, now=NOW),
            _build_insights_json(rows, now=NOW),
        )

    def test_a_settled_record_is_far_smaller_than_the_same_live_one(self):
        # Realistic field lengths: on the reference meeting rationale was 18.6
        # percent of the payload and source_context 17.9 percent.
        fields = {
            "rationale": "They are consolidating because renewal admin overhead "
                         "is eating a quarter of the ops team's quarter." * 2,
            "source_context": "We have three separate renewals and honestly it is "
                              "burning us out, we want one throat to choke." * 2,
            "enrichment_notes": "Confirmed again later in the call." * 4,
        }
        live_row = insight(**fields)
        settled_row = insight(answered=True, created_at=NOW - timedelta(hours=1), **fields)

        live_size = len(_build_insights_json([live_row], now=NOW))
        settled_size = len(_build_insights_json([settled_row], now=NOW))

        self.assertLess(settled_size, live_size * 0.4)


class UnchangedCorpusSkipTests(unittest.TestCase):
    def setUp(self):
        synthesizer._last_fingerprints.clear()
        self.addCleanup(synthesizer._last_fingerprints.clear)

    def test_clearing_session_state_forgets_the_fingerprint(self):
        session_id = uuid.uuid4()
        synthesizer._last_fingerprints[session_id] = "abc"
        synthesizer.clear_synthesizer_state(session_id)
        self.assertNotIn(session_id, synthesizer._last_fingerprints)

    def test_clearing_an_unknown_session_is_harmless(self):
        synthesizer.clear_synthesizer_state(uuid.uuid4())


# The JsonFenceTests class that lived here covered strip_json_fence, which this
# commit extracted to fix a strip stranded after a return in both call sites.
# v0.5.0 made the synthesizer a structured-output caller (generate_json against
# SynthesizerOutput), so there is no hand-rolled fence handling left to test:
# llm.parse_json_response tolerates fences centrally for every caller.


class CooldownIdleTests(unittest.IsolatedAsyncioTestCase):
    async def test_nothing_fires_without_an_event(self):
        fired = []

        async def handler(batch):
            fired.append(batch)

        subscriber = CooldownSubscriber(handler=handler, cooldown_seconds=0.01)
        try:
            import asyncio

            await asyncio.sleep(0.05)
        finally:
            subscriber.stop()
        self.assertEqual([], fired, "idle subscriber fired a handler run")


if __name__ == "__main__":
    unittest.main()

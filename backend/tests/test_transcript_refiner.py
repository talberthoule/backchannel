"""Transcript refinement: the acceptance rule that keeps tokens intact, and
the batch flow that writes accepted rewrites back."""

import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.services import transcript_refiner as refiner  # noqa: E402


class AcceptanceTests(unittest.TestCase):
    def test_same_tokens_and_sane_length_are_accepted(self):
        self.assertTrue(refiner.accept_refinement(
            "so [PERSON_1] said uh the email [EMAIL_1] is wrong",
            "So [PERSON_1] said the email [EMAIL_1] is wrong.",
        ))

    def test_a_dropped_added_or_renumbered_token_is_refused(self):
        original = "[PERSON_1] told [PERSON_2] to call [PHONE_1]"
        self.assertFalse(refiner.accept_refinement(original, "[PERSON_1] told them to call [PHONE_1]."))
        self.assertFalse(refiner.accept_refinement(original, "[PERSON_1] told [PERSON_2] and [PERSON_3] to call [PHONE_1]."))
        self.assertFalse(refiner.accept_refinement(original, "[PERSON_2] told [PERSON_1] to call [PHONE_2]."))
        # Two mentions must stay two mentions.
        self.assertFalse(refiner.accept_refinement("[ORG_1] and [ORG_1] again", "[ORG_1] again."))

    def test_empty_unchanged_or_runaway_rewrites_are_refused(self):
        self.assertFalse(refiner.accept_refinement("hello there", ""))
        self.assertFalse(refiner.accept_refinement("hello there", "hello there"))
        self.assertFalse(refiner.accept_refinement("hello there", "hello there " * 5))
        self.assertFalse(refiner.accept_refinement("hello there my friend", "hi"))

    def test_bare_token_forms_count_the_same_as_bracketed(self):
        self.assertEqual(refiner.token_multiset("[PERSON_1] and PERSON_1"), {"PERSON_1": 2})

    def test_markers_and_already_refined_rows_are_skipped(self):
        marker = SimpleNamespace(text="--- Session Resumed (Call 2) ---", refined_at=None)
        done = SimpleNamespace(text="fine", refined_at="2026-09-02")
        fresh = SimpleNamespace(text="fine", refined_at=None)
        self.assertFalse(refiner.is_refinable(marker))
        self.assertFalse(refiner.is_refinable(done))
        self.assertTrue(refiner.is_refinable(fresh))

    def test_prompt_shows_context_separately_from_targets(self):
        prompt = refiner.build_prompt([("a1", "Me", "hi [PERSON_1]")], [("Them", "earlier line")])
        self.assertIn("for context only", prompt)
        self.assertIn("Them: earlier line", prompt)
        self.assertIn("[a1] Me: hi [PERSON_1]", prompt)


def _entry(text, sequence, speaker_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(), session_id=uuid.uuid4(), text=text, raw_text=None, refined_at=None,
        sequence=sequence, speaker_id=speaker_id,
    )


class BatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_rewrites_are_applied_and_originals_kept(self):
        sid = uuid.uuid4()
        good = _entry("um so [PERSON_1] will send it", 1)
        bad = _entry("[PERSON_2] agreed", 2)
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        reply = refiner.RefinementReply(entries=[
            refiner.RefinedEntry(id=str(good.id), text="So [PERSON_1] will send it."),
            refiner.RefinedEntry(id=str(bad.id), text="They agreed."),  # token dropped
            refiner.RefinedEntry(id="unknown", text="[PERSON_9]"),
        ])
        with patch("app.services.llm.generate_json", AsyncMock(return_value=reply)) as call:
            changed = await refiner.refine_batch(db, sid, "gemini-x", [good, bad], [])
        self.assertEqual([e.id for e in changed], [good.id])
        self.assertEqual(good.text, "So [PERSON_1] will send it.")
        self.assertEqual(good.raw_text, "um so [PERSON_1] will send it")
        self.assertIsNotNone(good.refined_at)
        self.assertEqual(bad.text, "[PERSON_2] agreed")
        self.assertIsNone(bad.refined_at)
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["session_id"], sid)
        self.assertEqual(kwargs["source"], refiner.REFINER_SOURCE)
        self.assertIn("[PERSON_1]", call.call_args.args[1])

    async def test_refine_session_batches_pending_rows_and_survives_a_failed_batch(self):
        sid = uuid.uuid4()
        rows = [_entry(f"line {i} [PERSON_1]", i) for i in range(1, 6)]
        rows[0].refined_at = "done"
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        calls = []

        async def fake_batch(db_, sid_, model, batch, context, *, source):
            calls.append(([e.sequence for e in batch], [c.sequence for c in context]))
            if batch[0].sequence == 2:
                raise RuntimeError("provider down")
            for e in batch:
                e.raw_text, e.text, e.refined_at = e.text, e.text.capitalize() + ".", "now"
            return list(batch)

        with patch.object(refiner, "refine_batch", fake_batch):
            changed = await refiner.refine_session(db, sid, "m", batch_size=2)
        self.assertEqual(calls, [([2, 3], [1]), ([4, 5], [1, 2, 3])])
        self.assertEqual([e.sequence for e in changed], [4, 5])
        self.assertEqual(rows[3].text, "Line 4 [person_1].")

    async def test_limit_takes_the_most_recent_pending_rows(self):
        sid = uuid.uuid4()
        rows = [_entry(f"line {i}", i) for i in range(1, 8)]
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        seen = []

        async def fake_batch(db_, sid_, model, batch, context, *, source):
            seen.extend(e.sequence for e in batch)
            return []

        with patch.object(refiner, "refine_batch", fake_batch):
            await refiner.refine_session(db, sid, "m", limit=3)
        self.assertEqual(seen, [5, 6, 7])


if __name__ == "__main__":
    unittest.main()

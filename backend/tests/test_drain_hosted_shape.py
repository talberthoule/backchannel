"""Hosted-model op shapes and drain heartbeats (ALP-171).

A cloud model answers with every schema key present, writing null where it has
nothing to say; a self-hosted one omits the key entirely. That difference cost a
whole synthesizer cycle to an IntegrityError, and is the hosted-shape edge
ALP-164's acceptance four warned about.
"""

import asyncio
import unittest
from types import SimpleNamespace

from app.services.agents.orchestrator import _run_drain_heartbeat
from app.services.insight_refiner import _without_nulls


class ExplicitNullOperationTests(unittest.TestCase):
    def test_an_explicit_null_falls_back_to_the_column_default(self):
        """followup_question null must not override the empty-string default."""
        op = _without_nulls(
            {
                "op": "create",
                "question": "What is the renewal date?",
                "rationale": None,
                "source_context": None,
                "followup_question": None,
            }
        )

        # The keys are gone, so every op.get(key, "") in the apply path returns
        # its default instead of a None the insert would reject.
        self.assertEqual("", op.get("rationale", ""))
        self.assertEqual("", op.get("source_context", ""))
        self.assertEqual("", op.get("followup_question", ""))
        self.assertNotIn("rationale", op)

    def test_a_self_hosted_omission_and_a_hosted_null_agree(self):
        hosted = _without_nulls({"op": "answer", "answer_summary": "Yes", "followup": None})
        self_hosted = _without_nulls({"op": "answer", "answer_summary": "Yes"})

        self.assertEqual(self_hosted, hosted)

    def test_real_values_including_falsey_ones_survive(self):
        op = _without_nulls(
            {"op": "answer", "needs_followup": False, "answer_summary": "", "vote": 0}
        )

        self.assertIs(False, op["needs_followup"])
        self.assertEqual("", op["answer_summary"])
        self.assertEqual(0, op["vote"])


class ExplicitNullInsertTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_hosted_create_op_inserts_with_defaults_not_nulls(self):
        """The exact payload that lost a synthesizer cycle to IntegrityError."""
        from app.services.insight_refiner import _apply_operations_in_db

        added: list = []
        db = SimpleNamespace(
            add=added.append,
            flush=lambda: asyncio.sleep(0),
            get=lambda *a, **k: asyncio.sleep(0),
        )

        await _apply_operations_in_db(
            db,
            "session",
            [
                {
                    "op": "create",
                    "item_type": "question",
                    "question": "When does the contract renew?",
                    "rationale": None,
                    "source_context": None,
                    "followup_question": None,
                }
            ],
            [],
        )

        self.assertEqual(1, len(added))
        created = added[0]
        # Not None: these columns are not-null with empty-string defaults, and a
        # None assigned here is what the insert rejected. followup_question is
        # not touched by create at all, so it is left for the column default.
        self.assertEqual("", created.rationale)
        self.assertEqual("", created.source_context)
        # The applied-payload count is deliberately not asserted: building it
        # reads created_at, which SQLAlchemy fills at flush, so it says nothing
        # about the null handling this test is for.

    async def test_a_hosted_answer_op_does_not_null_out_followup_question(self):
        """The field the live failure named, on the handler that assigns it."""
        import uuid as _uuid

        from app.services.insight_refiner import _apply_operations_in_db

        question_id = _uuid.uuid4()
        question = SimpleNamespace(
            id=question_id,
            dismissed=False,
            answered=False,
            answer_summary="",
            needs_followup=False,
            followup_question="",
            question="Renewal?",
            enrichment_notes="",
            revision_count=0,
            updated_at=None,
            enhanced=False,
            item_type="question",
            lens_label="",
            rationale="",
            source_context="",
            directive_id=None,
            starred=False,
            offering_match="",
            vote=0,
            created_at=__import__("datetime").datetime.now(),
            speaker_mapping_revision_id=None,
        )

        async def _get(*_a, **_k):
            return question

        db = SimpleNamespace(add=lambda o: None, flush=lambda: asyncio.sleep(0), get=_get)

        await _apply_operations_in_db(
            db,
            "session",
            [
                {
                    "op": "answer",
                    "id": str(question_id),
                    "answer_summary": "Renews in March.",
                    "needs_followup": None,
                    "followup": None,
                }
            ],
            [question],
        )

        self.assertEqual("", question.followup_question)
        self.assertIs(False, question.needs_followup)


class DrainHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, sent, latest, ticks=3, fail=False):
        async def callback(event):
            sent.append(event)
            if fail:
                raise RuntimeError("socket gone")

        task = asyncio.create_task(
            _run_drain_heartbeat(callback, latest, interval=0.01)
        )
        for _ in range(ticks * 4):
            await asyncio.sleep(0.01)
            if len(sent) >= ticks or (fail and sent):
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_it_repeats_the_running_stage_so_the_socket_is_never_silent(self):
        sent: list = []
        latest = {
            "event": {"stage": "insight_reconciliation", "message": "Reconciling...", "progress": 60}
        }

        await self._run(sent, latest, ticks=2)

        self.assertGreaterEqual(len(sent), 1)
        # It repeats the real stage rather than inventing one, and marks itself.
        self.assertEqual("insight_reconciliation", sent[0]["stage"])
        self.assertEqual(60, sent[0]["progress"])
        self.assertIs(True, sent[0]["heartbeat"])

    async def test_it_stays_quiet_until_a_stage_has_been_announced(self):
        sent: list = []

        await self._run(sent, {}, ticks=1)

        self.assertEqual([], sent)

    async def test_a_dead_socket_ends_the_heartbeat_instead_of_looping_on_errors(self):
        sent: list = []
        latest = {"event": {"stage": "call_briefing", "message": "Briefing..."}}

        await self._run(sent, latest, ticks=1, fail=True)

        # One attempt, then it gives up rather than raising every interval.
        self.assertEqual(1, len(sent))


if __name__ == "__main__":
    unittest.main()

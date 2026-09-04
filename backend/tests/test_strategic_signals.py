import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy.orm import attributes

from app.services.agents.prompts import STRATEGIC_SIGNALS_PROMPT
from app.services.agents.strategic_signals import run_strategic_signals_cycle
from app.models import SessionSynthesis
from app.services.briefing_synthesis import (
    BriefArbiterOutput,
    BriefItem,
    EvidenceRef,
    _merge_signal_history,
    _persist_synthesis,
)


class SignalHistoryMergeTests(unittest.TestCase):
    def test_merges_normalized_title_and_keeps_latest_body(self):
        first_at = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
        last_at = datetime(2026, 7, 30, 10, 1, tzinfo=timezone.utc)
        first = BriefArbiterOutput(
            risks_blockers=[
                BriefItem(
                    title="Budget Risk",
                    summary="First wording",
                    rationale="First rationale",
                    evidence_refs=[EvidenceRef(insight_id="old")],
                )
            ]
        )
        latest = BriefArbiterOutput(
            risks_blockers=[
                BriefItem(
                    title="  budget   risk. ",
                    summary="Latest wording",
                    rationale="Latest rationale",
                    owner="Finance",
                    status="open",
                    evidence_refs=[EvidenceRef(insight_id="new")],
                )
            ]
        )

        history = _merge_signal_history([], first, first_at, "model-1")
        merged = _merge_signal_history(
            json.loads(json.dumps(history)),
            latest,
            last_at,
            "model-2",
        )

        self.assertEqual(1, len(merged))
        item = merged[0]
        self.assertEqual("risks_blockers", item["section"])
        self.assertEqual("  budget   risk. ", item["title"])
        self.assertEqual("Latest wording", item["summary"])
        self.assertEqual("Latest rationale", item["rationale"])
        self.assertEqual("Finance", item["owner"])
        self.assertEqual("open", item["status"])
        self.assertEqual("model-2", item["model_id"])
        self.assertEqual("old", history[0]["evidence_refs"][0]["insight_id"])
        self.assertEqual("new", item["evidence_refs"][0]["insight_id"])
        self.assertEqual(first_at.isoformat(), item["first_seen"])
        self.assertEqual(last_at.isoformat(), item["last_seen"])
        self.assertEqual(2, item["count"])

    def test_changed_title_and_blank_title_fallback_remain_distinct(self):
        captured_at = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
        output = BriefArbiterOutput(
            strategic_signals=[
                BriefItem(title="Budget", summary="Budget is constrained"),
                BriefItem(title="Timeline", summary="Timeline is constrained"),
                BriefItem(summary="Executive sponsor engaged"),
                BriefItem(summary="Executive sponsor engaged"),
            ]
        )

        merged = _merge_signal_history([], output, captured_at, "model")

        self.assertEqual(3, len(merged))
        self.assertEqual(["Budget", "Timeline", ""], [item["title"] for item in merged])
        self.assertEqual(2, merged[-1]["count"])

    def test_caps_history_at_newest_200_entries(self):
        start = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
        existing = [
            {
                "section": "strategic_signals",
                "title": f"Signal {index}",
                "summary": "",
                "rationale": "",
                "owner": "",
                "status": "",
                "evidence_refs": [],
                "first_seen": start.isoformat(),
                "last_seen": start.replace(minute=index % 60).isoformat(),
                "count": 1,
                "model_id": "model",
            }
            for index in range(200)
        ]
        latest = BriefArbiterOutput(
            strategic_signals=[BriefItem(title="Newest signal")]
        )

        merged = _merge_signal_history(
            existing,
            latest,
            datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc),
            "model",
        )

        self.assertEqual(200, len(merged))
        self.assertNotIn("Signal 0", {item["title"] for item in merged})
        self.assertIn("Newest signal", {item["title"] for item in merged})


class _PersistenceResult:
    def __init__(self, value=None, values=None):
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.values


class _PersistenceSession:
    def __init__(self, synthesis, speakers=None):
        self.synthesis = synthesis
        self.speakers = speakers or []
        self.execute_count = 0
        self.closed = False

    async def execute(self, statement):
        del statement
        self.execute_count += 1
        if self.execute_count in {1, 3}:
            return _PersistenceResult(self.synthesis)
        if self.execute_count == 4:
            return _PersistenceResult(values=self.speakers)
        return _PersistenceResult()

    def add(self, value):
        del value

    async def flush(self):
        pass

    async def commit(self):
        pass


class _PersistenceContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        self.db.closed = True


class _AttachedPersistenceSpeaker:
    def __init__(self, db, speaker_id):
        self._db = db
        self._values = {
            "id": speaker_id,
            "name": "Speaker 1",
            "role": "",
            "speaker_type": "external",
            "display_name": "Maya Chen",
            "display_name_enabled": True,
        }

    def __getattr__(self, name):
        if self._db.closed:
            raise AssertionError("speaker rows were accessed after the session closed")
        return self._values[name]


class _DetachedPersistenceSynthesis(SimpleNamespace):
    def __init__(self, db, **values):
        self._db = db
        self._top_outcomes = values.pop("top_outcomes", [])
        super().__init__(**values)

    @property
    def top_outcomes(self):
        if not self._db.closed:
            raise AssertionError("synthesis was normalized before the session closed")
        return self._top_outcomes

    @top_outcomes.setter
    def top_outcomes(self, value):
        self._top_outcomes = value


class SignalHistoryPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def _persist(self, synthesis, mode, status, output):
        db = _PersistenceSession(synthesis)
        with (
            patch(
                "app.services.briefing_synthesis.async_session",
                return_value=_PersistenceContext(db),
            ),
            patch(
                "app.services.briefing_synthesis._lock_synthesis_scope",
                new=AsyncMock(),
            ),
        ):
            return await _persist_synthesis(
                session_id=synthesis.session_id,
                mode=mode,
                status=status,
                meeting_output=None,
                discovery_output=None,
                arbiter_output=output,
                model_ids={"strategic_signals": "signal-model"},
            )

    async def test_completed_live_persistence_reassigns_round_tripped_history(self):
        session_id = uuid4()
        synthesis = SessionSynthesis(
            id=uuid4(),
            session_id=session_id,
            mode="live",
            signal_history=[],
        )
        output = BriefArbiterOutput(
            strategic_signals=[BriefItem(title="Budget", summary="First")]
        )

        await self._persist(synthesis, "live", "completed", output)
        first = json.loads(json.dumps(synthesis.signal_history))
        attributes.set_committed_value(synthesis, "signal_history", first)
        previous_list = synthesis.signal_history
        output.strategic_signals[0].summary = "Latest"

        await self._persist(synthesis, "live", "completed", output)

        self.assertIsNot(previous_list, synthesis.signal_history)
        self.assertEqual(1, len(synthesis.signal_history))
        self.assertEqual(2, synthesis.signal_history[0]["count"])
        self.assertEqual("Latest", synthesis.signal_history[0]["summary"])
        self.assertTrue(
            attributes.instance_state(synthesis)
            .attrs.signal_history.history.has_changes()
        )

    async def test_other_modes_and_statuses_do_not_change_history(self):
        for mode, status in (
            ("post_call", "completed"),
            ("live", "partial"),
            ("live", "error"),
        ):
            with self.subTest(mode=mode, status=status):
                original = [{"section": "strategic_signals", "title": "Existing"}]
                synthesis = SessionSynthesis(
                    id=uuid4(),
                    session_id=uuid4(),
                    mode=mode,
                    signal_history=original,
                )

                await self._persist(
                    synthesis,
                    mode,
                    status,
                    BriefArbiterOutput(
                        strategic_signals=[BriefItem(title="New signal")]
                    ),
                )

                self.assertIs(original, synthesis.signal_history)

    async def test_persistence_materializes_speakers_then_normalizes_the_detached_row(self):
        session_id = uuid4()
        speaker_id = uuid4()
        db = _PersistenceSession(None)
        synthesis = _DetachedPersistenceSynthesis(
            db,
            id=uuid4(),
            session_id=session_id,
            mode="post_call",
            top_outcomes=[],
            signal_history=[],
        )
        db.synthesis = synthesis
        db.speakers = [_AttachedPersistenceSpeaker(db, speaker_id)]

        with (
            patch(
                "app.services.briefing_synthesis.async_session",
                return_value=_PersistenceContext(db),
            ),
            patch(
                "app.services.briefing_synthesis._lock_synthesis_scope",
                new=AsyncMock(),
            ),
        ):
            result = await _persist_synthesis(
                session_id=session_id,
                mode="post_call",
                status="completed",
                meeting_output=None,
                discovery_output=None,
                arbiter_output=BriefArbiterOutput(
                    top_outcomes=[BriefItem(title="Decision", owner=str(speaker_id))]
                ),
                model_ids={},
            )

        self.assertEqual("Maya Chen", result.top_outcomes[0]["owner"])


class StrategicSignalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_uses_one_model_call_and_preserves_evidence_refs(self):
        output = BriefArbiterOutput(
            strategic_signals=[
                BriefItem(
                    title="Budget is the gating signal",
                    evidence_refs=[
                        EvidenceRef(insight_id="insight-1", type="insight")
                    ],
                )
            ]
        )
        configs = {
            "strategic_signals": SimpleNamespace(
                enabled=True,
                model_id="test-model",
                prompt=STRATEGIC_SIGNALS_PROMPT,
            )
        }
        context = SimpleNamespace(
            meeting_context_text="ctx",
            transcript_text="transcript",
            directives_text="none",
            document_summaries="none",
            speakers_text="Speaker 1",
            insights_text="- insight_id=insight-1",
        )
        persisted = SimpleNamespace(
            strategic_signals=[output.strategic_signals[0].model_dump()]
        )

        with (
            patch(
                "app.services.agents.strategic_signals.is_local_only",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.agents.strategic_signals._build_context",
                new=AsyncMock(return_value=context),
            ),
            patch(
                "app.services.agents.strategic_signals.generate_json",
                new=AsyncMock(return_value=output),
            ) as generate,
            patch(
                "app.services.agents.strategic_signals._persist_synthesis",
                new=AsyncMock(return_value=persisted),
            ) as persist,
        ):
            result = await run_strategic_signals_cycle(
                uuid4(), agent_configs=configs
            )

        generate.assert_awaited_once()
        self.assertEqual("test-model", generate.await_args.args[0])
        persist.assert_awaited_once()
        # The cycle returns the panel update alongside the signal insight rows
        # it filed this round (ALP-308).
        synthesis, signal_rows = result
        self.assertEqual(
            "insight-1",
            synthesis.strategic_signals[0]["evidence_refs"][0]["insight_id"],
        )
        self.assertEqual({"created", "updated"}, set(signal_rows))

    async def test_cycle_skips_when_agent_is_disabled(self):
        with patch(
            "app.services.agents.strategic_signals.is_local_only",
            new=AsyncMock(return_value=False),
        ):
            result = await run_strategic_signals_cycle(
                uuid4(),
                agent_configs={
                    "strategic_signals": SimpleNamespace(enabled=False)
                },
            )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

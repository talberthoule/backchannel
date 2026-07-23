import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import inspect

from app.models import (
    Session,
    SpeakerMappingRevision,
    SpeakerRevalidationBatch,
    SpeakerRevalidationRun,
)
from app.services.speaker_revalidation import (
    batch_failure_reason,
    build_batch_specs,
    canonical_speaker_mapping,
    content_version,
    finalize_run_state,
    mapping_hash,
    requeue_failed_batches,
    start_or_resume_revalidation,
    summarize_run,
)


class _FakeGoogleClientError(Exception):
    """Stands in for google.genai.errors.ClientError (module starts with google)."""


_FakeGoogleClientError.__module__ = "google.genai.errors"


class BatchFailureReasonTests(unittest.TestCase):
    def test_gemini_spending_cap_429_becomes_actionable_guidance(self):
        exc = _FakeGoogleClientError(
            "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
            "'Your project has exceeded its monthly spending cap. To continue "
            "making API calls, raise the cap.', 'status': 'RESOURCE_EXHAUSTED'}}"
        )

        reason = batch_failure_reason(exc)

        self.assertEqual(
            "Gemini quota/spending cap exhausted - raise the cap in "
            "AI Studio or switch the model in Admin.",
            reason,
        )

    def test_non_google_quota_errors_get_generic_quota_guidance(self):
        reason = batch_failure_reason(RuntimeError("429 Too Many Requests"))

        self.assertEqual(
            "Model provider quota or rate limit exhausted - raise the limit "
            "or switch the model in Admin.",
            reason,
        )

    def test_auth_errors_point_to_admin_api_keys(self):
        reason = batch_failure_reason(
            RuntimeError("403 PERMISSION_DENIED: API key not valid.")
        )

        self.assertEqual(
            "The model provider rejected the API key - update it in "
            "Admin -> API Keys.",
            reason,
        )

    def test_other_errors_keep_the_first_line_of_the_original_message(self):
        reason = batch_failure_reason(
            RuntimeError("Briefing revalidation did not complete\nTraceback...")
        )

        self.assertEqual("Briefing revalidation did not complete", reason)

    def test_empty_errors_still_produce_a_message(self):
        self.assertEqual(
            "Revalidation batch failed unexpectedly.",
            batch_failure_reason(RuntimeError("")),
        )


class SpeakerRevalidationRevisionTests(unittest.TestCase):
    def test_mapping_snapshot_and_hash_are_canonical(self):
        speakers = [
            SimpleNamespace(
                id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                name="Participant 2",
                role="Client",
                speaker_type="external",
                is_user=False,
                display_name="Morgan",
                display_name_enabled=True,
            ),
            SimpleNamespace(
                id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                name="Participant 1",
                role="Seller",
                speaker_type="team",
                is_user=True,
                display_name="Alex",
                display_name_enabled=True,
            ),
        ]

        snapshot = canonical_speaker_mapping(speakers)

        self.assertEqual(
            [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
            [speaker["id"] for speaker in snapshot],
        )
        self.assertEqual(mapping_hash(snapshot), mapping_hash(list(reversed(snapshot))))

    def test_content_version_changes_with_source_content_not_input_order(self):
        question_a = SimpleNamespace(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            question="Original",
            rationale="Why",
            source_context="Evidence",
            speaker_id=None,
            dismissed=False,
            answered=False,
            answer_summary="",
            revision_count=0,
        )
        question_b = SimpleNamespace(
            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            question="Second",
            rationale="",
            source_context="",
            speaker_id=None,
            dismissed=False,
            answered=False,
            answer_summary="",
            revision_count=0,
        )
        transcript = [
            SimpleNamespace(
                id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
                sequence=1,
                text="Source statement",
                speaker_id=None,
            )
        ]
        session = SimpleNamespace(meeting_type="client_sales", meeting_context="Context")

        first = content_version(session, [question_a, question_b], transcript)
        reordered = content_version(session, [question_b, question_a], transcript)
        question_a.question = "Changed"
        changed = content_version(session, [question_a, question_b], transcript)

        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)


class SpeakerRevalidationBatchTests(unittest.TestCase):
    def test_builds_bounded_insight_batches_then_one_briefing_batch(self):
        ids = [str(uuid.uuid4()) for _ in range(5)]

        specs = build_batch_specs(ids, batch_size=2)

        self.assertEqual(
            [
                ("insights", ids[:2]),
                ("insights", ids[2:4]),
                ("insights", ids[4:]),
                ("briefing", []),
            ],
            specs,
        )

    def test_retry_requeues_failed_batches_only(self):
        completed = SimpleNamespace(
            status="completed",
            error_message="",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        failed = SimpleNamespace(
            status="failed",
            error_message="model offline",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        queued = SimpleNamespace(
            status="queued",
            error_message="",
            started_at=None,
            completed_at=None,
        )
        run = SimpleNamespace(
            status="partial",
            error_message="1 batch failed",
            completed_at=datetime.now(timezone.utc),
        )

        count = requeue_failed_batches(run, [completed, failed, queued])

        self.assertEqual(1, count)
        self.assertEqual("completed", completed.status)
        self.assertEqual("queued", failed.status)
        self.assertEqual("queued", queued.status)
        self.assertEqual("", failed.error_message)
        self.assertIsNone(failed.started_at)
        self.assertIsNone(failed.completed_at)
        self.assertEqual("running", run.status)
        self.assertEqual("", run.error_message)
        self.assertIsNone(run.completed_at)

    def test_summary_reports_batch_progress_metrics_and_failures(self):
        started = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
        completed = datetime(2026, 7, 23, 12, 0, 2, tzinfo=timezone.utc)
        batches = [
            SimpleNamespace(
                id=uuid.uuid4(),
                batch_index=0,
                kind="insights",
                status="completed",
                attempts=1,
                processed_entries=2,
                applied_operations=1,
                enhanced_insights=1,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                duration_ms=750,
                error_message="",
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                batch_index=1,
                kind="briefing",
                status="failed",
                attempts=2,
                processed_entries=0,
                applied_operations=0,
                enhanced_insights=0,
                input_tokens=30,
                output_tokens=5,
                total_tokens=35,
                duration_ms=1250,
                error_message="model offline",
            ),
        ]
        run = SimpleNamespace(
            id=uuid.uuid4(),
            status="partial",
            content_version="abc123",
            mapping_revision=SimpleNamespace(source_version=7),
            batches=batches,
            started_at=started,
            completed_at=completed,
            error_message="1 batch failed",
        )
        session = SimpleNamespace(
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )

        summary = summarize_run(run, session)

        self.assertEqual(2, summary["total_batches"])
        self.assertEqual(1, summary["completed_batches"])
        self.assertEqual(1, summary["failed_batches"])
        self.assertEqual(0.5, summary["failure_rate"])
        self.assertEqual(2, summary["processed_entries"])
        self.assertEqual(155, summary["total_tokens"])
        self.assertEqual(2000, summary["duration_ms"])
        self.assertEqual("model offline", summary["batches"][1]["error"])

    def test_finalization_carries_the_failed_batch_reason_into_the_run(self):
        now = datetime.now(timezone.utc)
        reason = batch_failure_reason(
            _FakeGoogleClientError("429 RESOURCE_EXHAUSTED: monthly spending cap")
        )
        batches = [
            SimpleNamespace(status="failed", error_message=reason),
            SimpleNamespace(status="queued", error_message=""),
        ]
        run = SimpleNamespace(status="running", error_message="", completed_at=None)
        session = SimpleNamespace(
            speaker_context_version=2,
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )

        finalize_run_state(run, batches, session, SimpleNamespace(source_version=2), now)

        self.assertEqual("partial", run.status)
        self.assertEqual(now, run.completed_at)
        self.assertEqual(
            "1 revalidation batch failed. Gemini quota/spending cap exhausted "
            "- raise the cap in AI Studio or switch the model in Admin.",
            run.error_message,
        )
        self.assertTrue(session.speaker_context_dirty)

    def test_finalization_marks_run_failed_when_every_batch_failed(self):
        run = SimpleNamespace(status="running", error_message="", completed_at=None)
        session = SimpleNamespace(
            speaker_context_version=1,
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )
        batches = [
            SimpleNamespace(status="failed", error_message="model offline"),
            SimpleNamespace(status="failed", error_message="model offline"),
        ]

        finalize_run_state(run, batches, session, SimpleNamespace(source_version=1))

        self.assertEqual("failed", run.status)
        self.assertIn("2 revalidation batches failed.", run.error_message)
        self.assertIn("model offline", run.error_message)

    def test_failed_run_summary_is_distinguishable_from_in_progress(self):
        # Production regression: one insights batch hit a provider 429, the
        # briefing batch never ran, and the UI still showed "Revalidating 0/2".
        now = datetime.now(timezone.utc)
        reason = batch_failure_reason(
            _FakeGoogleClientError(
                "429 RESOURCE_EXHAUSTED: Your project has exceeded its monthly "
                "spending cap."
            )
        )
        batches = [
            SimpleNamespace(
                id=uuid.uuid4(),
                batch_index=0,
                kind="insights",
                status="failed",
                attempts=1,
                processed_entries=0,
                applied_operations=0,
                enhanced_insights=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                duration_ms=420,
                error_message=reason,
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                batch_index=1,
                kind="briefing",
                status="queued",
                attempts=0,
                processed_entries=0,
                applied_operations=0,
                enhanced_insights=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                duration_ms=0,
                error_message="",
            ),
        ]
        run = SimpleNamespace(
            id=uuid.uuid4(),
            status="running",
            content_version="abc",
            mapping_revision=SimpleNamespace(source_version=3),
            batches=batches,
            started_at=now,
            completed_at=None,
            error_message="",
        )
        session = SimpleNamespace(
            speaker_context_version=3,
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )

        finalize_run_state(run, batches, session, run.mapping_revision, now)
        summary = summarize_run(run, session)

        self.assertEqual("partial", summary["status"])
        self.assertNotEqual("running", summary["status"])
        self.assertEqual(0, summary["completed_batches"])
        self.assertEqual(1, summary["failed_batches"])
        self.assertIn("1 revalidation batch failed.", summary["error"])
        self.assertIn("Gemini quota/spending cap exhausted", summary["error"])
        self.assertEqual(reason, summary["batches"][0]["error"])

    def test_finalization_clears_only_the_mapping_version_that_ran(self):
        now = datetime.now(timezone.utc)
        mapping = SimpleNamespace(source_version=4)
        completed_batches = [
            SimpleNamespace(status="completed"),
            SimpleNamespace(status="completed"),
        ]
        run = SimpleNamespace(status="running", error_message="", completed_at=None)
        session = SimpleNamespace(
            speaker_context_version=4,
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )

        finalize_run_state(run, completed_batches, session, mapping, now)

        self.assertEqual("completed", run.status)
        self.assertFalse(session.speaker_context_dirty)
        self.assertEqual(now, session.speaker_context_enhanced_at)

        stale_run = SimpleNamespace(
            status="running",
            error_message="",
            completed_at=None,
        )
        stale_session = SimpleNamespace(
            speaker_context_version=5,
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )

        finalize_run_state(stale_run, completed_batches, stale_session, mapping, now)

        self.assertEqual("completed", stale_run.status)
        self.assertTrue(stale_session.speaker_context_dirty)
        self.assertIn("changed again", stale_run.error_message)


class SpeakerRevalidationOrmTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_returns_a_run_with_mapping_revision_eagerly_loaded(self):
        session_id = uuid.uuid4()
        revision = SpeakerMappingRevision(
            id=uuid.uuid4(),
            session_id=session_id,
            source_version=3,
            mapping_hash="hash",
            mapping_snapshot=[],
        )
        batch = SpeakerRevalidationBatch(
            id=uuid.uuid4(),
            batch_index=0,
            kind="insights",
            status="failed",
            attempts=1,
            processed_entries=0,
            applied_operations=0,
            enhanced_insights=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            duration_ms=0,
            error_message="model offline",
        )
        unloaded_run = SpeakerRevalidationRun(
            id=uuid.uuid4(),
            session_id=session_id,
            mapping_revision_id=revision.id,
            content_version="content",
            status="partial",
            started_at=datetime.now(timezone.utc),
            batches=[batch],
        )
        loaded_run = SpeakerRevalidationRun(
            id=unloaded_run.id,
            session_id=session_id,
            mapping_revision_id=revision.id,
            content_version="content",
            status="running",
            started_at=unloaded_run.started_at,
            mapping_revision=revision,
            batches=[batch],
        )
        session = Session(
            id=session_id,
            name="Call",
            state="completed",
            speaker_context_dirty=True,
            speaker_context_version=3,
        )
        self.assertIn("mapping_revision", inspect(unloaded_run).unloaded)

        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _OrmResult(one=session),
                    _OrmResult(values=[]),
                    _OrmResult(values=[]),
                    _OrmResult(values=[]),
                    _OrmResult(one=revision),
                    _OrmResult(values=[unloaded_run]),
                    _OrmResult(one=loaded_run),
                ]
            ),
            commit=AsyncMock(),
        )

        run, should_start = await start_or_resume_revalidation(session_id, db)

        self.assertTrue(should_start)
        self.assertNotIn("mapping_revision", inspect(run).unloaded)
        self.assertEqual(3, summarize_run(run, session)["mapping_revision"])


class _OrmResult:
    def __init__(self, *, one=None, values=None):
        self.one = one
        self.values = values or []

    def scalar_one(self):
        return self.one

    def scalar_one_or_none(self):
        return self.one

    def scalars(self):
        return self

    def first(self):
        return self.values[0] if self.values else None

    def __iter__(self):
        return iter(self.values)


if __name__ == "__main__":
    unittest.main()

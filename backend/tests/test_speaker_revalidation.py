import unittest
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import inspect

from app.models import (
    Session,
    SpeakerMappingRevision,
    SpeakerRevalidationBatch,
    SpeakerRevalidationRun,
)
from app.services import speaker_revalidation
from app.services.privacy import LocalOnlyModeError
from app.services.speaker_revalidation import (
    _enhance_insights_with_fallback,
    batch_failure_reason,
    build_batch_specs,
    canonical_speaker_mapping,
    content_version,
    finalize_run_state,
    get_latest_revalidation_run,
    is_quota_error,
    is_rate_limit_error,
    mapping_hash,
    requeue_failed_batches,
    select_fallback_models,
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
            "Gemini quota/spending cap exhausted. Assign a self-hosted model "
            "in Admin -> Agents (any on-prem endpoint), or raise the cap in "
            "AI Studio.",
            reason,
        )

    def test_non_google_quota_errors_get_generic_quota_guidance(self):
        reason = batch_failure_reason(RuntimeError("429 Too Many Requests"))

        self.assertEqual(
            "Model provider quota or rate limit exhausted. Assign a self-hosted "
            "model in Admin -> Agents (any on-prem endpoint), or raise the limit "
            "in the provider console.",
            reason,
        )

    def test_auth_errors_point_to_admin_api_keys(self):
        reason = batch_failure_reason(
            RuntimeError("403 PERMISSION_DENIED: API key not valid.")
        )

        self.assertEqual(
            "The model provider rejected the API key - update it in "
            "Admin -> Connections.",
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
                requested_model_id="cloud-primary",
                model_id="endpoint:lab:qwen",
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
                requested_model_id=None,
                model_id=None,
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
        self.assertEqual("cloud-primary", summary["batches"][0]["requested_model_id"])
        self.assertEqual("endpoint:lab:qwen", summary["batches"][0]["model_id"])
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
            "1 revalidation batch failed. Gemini quota/spending cap exhausted. "
            "Assign a self-hosted model in Admin -> Agents (any on-prem "
            "endpoint), or raise the cap in AI Studio.",
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

    async def test_latest_run_query_is_limited_to_one(self):
        session_id = uuid.uuid4()
        run = SimpleNamespace(id=uuid.uuid4())
        captured = {}

        async def execute(statement):
            captured["statement"] = statement
            return _OrmResult(values=[run])

        result = await get_latest_revalidation_run(
            session_id,
            SimpleNamespace(execute=execute),
        )

        compiled = str(captured["statement"].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("LIMIT 1", compiled)
        self.assertIs(run, result)


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


class QuotaClassificationTests(unittest.TestCase):
    def test_hard_cap_is_a_quota_error_but_not_a_rate_limit(self):
        exc = RuntimeError("429 RESOURCE_EXHAUSTED: monthly spending cap")
        self.assertTrue(is_quota_error(exc))
        self.assertFalse(is_rate_limit_error(exc))

    def test_bare_429_is_treated_as_a_transient_rate_limit(self):
        exc = RuntimeError("429 Too Many Requests")
        self.assertTrue(is_quota_error(exc))
        self.assertTrue(is_rate_limit_error(exc))

    def test_a_plain_failure_is_neither_quota_nor_rate_limit(self):
        exc = RuntimeError("Connection refused")
        self.assertFalse(is_quota_error(exc))
        self.assertFalse(is_rate_limit_error(exc))


class FallbackModelSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def _select(self, endpoints, primary, local_only, admitted=None):
        admit = (
            AsyncMock(side_effect=lambda ids, lo: set(ids))
            if admitted is None
            else AsyncMock(return_value=set(admitted))
        )
        with (
            patch(
                "app.services.speaker_revalidation.endpoint_models",
                new=AsyncMock(return_value=endpoints),
            ),
            patch(
                "app.services.speaker_revalidation.admitted_model_ids",
                new=admit,
            ),
        ):
            return await select_fallback_models(primary, SimpleNamespace(), local_only)

    async def test_prefers_on_prem_then_off_prem_and_excludes_the_primary(self):
        endpoints = [
            {"id": "endpoint:lab:qwen", "runs_locally": True, "supports_text": True},
            {"id": "endpoint:cloud:gpt", "runs_locally": False, "supports_text": True},
            {"id": "endpoint:lab:self", "runs_locally": True, "supports_text": True},
        ]

        result = await self._select(endpoints, "endpoint:lab:self", local_only=False)

        self.assertEqual(["endpoint:lab:qwen", "endpoint:cloud:gpt"], result)

    async def test_privacy_first_drops_non_on_prem_endpoints(self):
        endpoints = [
            {"id": "endpoint:lab:qwen", "runs_locally": True, "supports_text": True},
            {"id": "endpoint:cloud:gpt", "runs_locally": False, "supports_text": True},
        ]

        result = await self._select(endpoints, "gemini-3.5-flash", local_only=True)

        self.assertEqual(["endpoint:lab:qwen"], result)

    async def test_unadmitted_candidates_are_dropped(self):
        endpoints = [
            {"id": "endpoint:lab:qwen", "runs_locally": True, "supports_text": True},
        ]

        result = await self._select(
            endpoints, "gemini-3.5-flash", local_only=True, admitted=[]
        )

        self.assertEqual([], result)


class EnhanceInsightsWithFallbackTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _metrics(enhanced=1):
        return {
            "processed_entries": 1,
            "applied_operations": 1,
            "enhanced_insights": enhanced,
        }

    async def _enhance(self, batch, fallbacks, *, local_only=False, sleep=None, resolve=None):
        with ExitStack() as stack:
            # The primary comes from the synthesizer agent row (ALP-157), so the
            # resolver stands in for that lookup here.
            stack.enter_context(patch(
                "app.services.speaker_revalidation.agent_model_id",
                new=resolve or AsyncMock(return_value="cloud-primary"),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.get_local_only",
                new=AsyncMock(return_value=local_only),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.select_fallback_models",
                new=AsyncMock(return_value=fallbacks),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.run_speaker_context_batch",
                new=batch,
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.asyncio.sleep",
                new=sleep or AsyncMock(),
            ))
            return await _enhance_insights_with_fallback(
                SimpleNamespace(), uuid.uuid4(), [], uuid.uuid4()
            )

    async def test_primary_is_the_synthesizer_row_not_the_global_setting(self):
        """ALP-157 must survive the ALP-129 wrapper.

        Every attempt passes an explicit model_id down to the enhancer, so if
        the primary were read from settings the hardcoded default would arrive
        as an override on every insights batch and the selectable model would
        be silently dead. This pins the resolution to the agent row.
        """
        resolve = AsyncMock(return_value="endpoint:lab:qwen")
        batch = AsyncMock(return_value=self._metrics())

        await self._enhance(batch, [], resolve=resolve)

        self.assertEqual("synthesizer", resolve.await_args.args[0])
        self.assertEqual(1, len(resolve.await_args.args))
        self.assertEqual("endpoint:lab:qwen", batch.await_args.kwargs["model_id"])

    async def test_primary_success_never_touches_a_fallback(self):
        batch = AsyncMock(return_value=self._metrics())

        metrics = await self._enhance(batch, ["endpoint:lab:qwen"])

        self.assertEqual(1, metrics["enhanced_insights"])
        self.assertEqual("cloud-primary", metrics["requested_model_id"])
        self.assertEqual("cloud-primary", metrics["model_id"])
        self.assertEqual(1, batch.await_count)
        self.assertEqual("cloud-primary", batch.await_args.kwargs["model_id"])

    async def test_hard_cap_falls_back_to_the_self_hosted_model(self):
        cap = RuntimeError("429 RESOURCE_EXHAUSTED: spending cap")
        batch = AsyncMock(side_effect=[cap, self._metrics(enhanced=2)])

        metrics = await self._enhance(batch, ["endpoint:lab:qwen"])

        self.assertEqual(2, metrics["enhanced_insights"])
        self.assertEqual("cloud-primary", metrics["requested_model_id"])
        self.assertEqual("endpoint:lab:qwen", metrics["model_id"])
        self.assertEqual(2, batch.await_count)
        self.assertEqual("cloud-primary", batch.await_args_list[0].kwargs["model_id"])
        self.assertEqual("endpoint:lab:qwen", batch.await_args_list[1].kwargs["model_id"])

    async def test_hard_cap_with_no_fallback_raises(self):
        cap = RuntimeError("429 RESOURCE_EXHAUSTED: spending cap")
        batch = AsyncMock(side_effect=cap)

        with self.assertRaises(RuntimeError):
            await self._enhance(batch, [])

        self.assertEqual(1, batch.await_count)

    async def test_transient_rate_limit_is_retried_on_the_same_model(self):
        limit = RuntimeError("429 Too Many Requests")
        batch = AsyncMock(side_effect=[limit, self._metrics()])
        sleep = AsyncMock()

        await self._enhance(batch, [], sleep=sleep)

        self.assertEqual(2, batch.await_count)
        self.assertEqual("cloud-primary", batch.await_args_list[1].kwargs["model_id"])
        self.assertEqual(1, sleep.await_count)

    async def test_a_plain_failure_does_not_fall_back(self):
        boom = RuntimeError("Connection refused")
        batch = AsyncMock(side_effect=boom)

        with self.assertRaises(RuntimeError):
            await self._enhance(batch, ["endpoint:lab:qwen"])

        self.assertEqual(1, batch.await_count)

    async def test_privacy_first_refusal_of_the_cloud_primary_falls_back(self):
        refused = LocalOnlyModeError("insight enhancement", "cloud-primary")
        batch = AsyncMock(side_effect=[refused, self._metrics(enhanced=3)])

        metrics = await self._enhance(batch, ["endpoint:lab:qwen"], local_only=True)

        self.assertEqual(3, metrics["enhanced_insights"])
        self.assertEqual(2, batch.await_count)
        self.assertEqual("endpoint:lab:qwen", batch.await_args_list[1].kwargs["model_id"])


class SelfHostedQuotaWireFormatTests(unittest.TestCase):
    """Classification against the message shape ALP-154 actually produces.

    _raise_for_status now embeds the server's own body instead of httpx's bare
    status line, so the words the split keys on come from the provider rather
    than from a reason phrase. That makes the hard-cap versus rate-limit call
    sharper, and it is worth pinning: a wording change upstream would silently
    turn hard caps back into pointless same-model retries.
    """

    URL = "https://api.example.com/v1/chat/completions"

    def test_a_body_naming_quota_is_a_hard_cap_not_a_rate_limit(self):
        error = (
            f'HTTP 429 from {self.URL}: '
            '{"error":{"message":"You exceeded your current quota."}}'
        )

        self.assertTrue(is_quota_error(error))
        self.assertFalse(is_rate_limit_error(error))

    def test_a_body_naming_only_a_rate_limit_stays_retryable(self):
        error = f"HTTP 429 from {self.URL}: Rate limit reached, retry in 2s"

        self.assertTrue(is_quota_error(error))
        self.assertTrue(is_rate_limit_error(error))

    def test_a_bodyless_429_is_still_recognized(self):
        """The reason phrase is gone now, so the status code carries it alone."""
        error = f"HTTP 429 from {self.URL}"

        self.assertTrue(is_quota_error(error))
        self.assertTrue(is_rate_limit_error(error))

    def test_a_context_refusal_is_not_a_quota_error(self):
        """ALP-154's other new shape must not be mistaken for a quota wall."""
        error = f"HTTP 400 from {self.URL}: context length 8192 exceeded"

        self.assertFalse(is_quota_error(error))
        self.assertFalse(is_rate_limit_error(error))


class RetryFailedBatchesEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """The Retry failed batches control, with the fallback in place.

    ALP-118 requeues a failed batch and re-runs it. The batch that motivated
    this issue failed on a Gemini quota wall, so the point of the fix is that
    the same retry now completes on a self-hosted model instead of failing
    again with the same banner.
    """

    def _batch(self):
        return SimpleNamespace(
            id=uuid.uuid4(),
            batch_index=0,
            kind="insights",
            item_ids=[str(uuid.uuid4())],
            status="failed",
            attempts=1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            error_message=(
                "Gemini quota/spending cap exhausted. Assign a self-hosted model "
                "in Admin -> Agents (any on-prem endpoint), or raise the cap in "
                "AI Studio."
            ),
            processed_entries=0,
            applied_operations=0,
            enhanced_insights=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            duration_ms=0,
        )

    async def test_a_quota_failed_batch_is_requeued_and_completes_on_the_fallback(self):
        run = SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            mapping_revision_id=uuid.uuid4(),
            status="partial",
            error_message="1 revalidation batch failed.",
            completed_at=datetime.now(timezone.utc),
        )
        batch = self._batch()

        # The retry control itself.
        retried = requeue_failed_batches(run, [batch])

        self.assertEqual(1, retried)
        self.assertEqual("queued", batch.status)
        self.assertEqual("", batch.error_message)
        self.assertEqual("running", run.status)

        # The re-run, with the primary still walled off.
        cap = RuntimeError("429 RESOURCE_EXHAUSTED: spending cap")
        inner = AsyncMock(side_effect=[
            cap,
            {"processed_entries": 3, "applied_operations": 4, "enhanced_insights": 2},
        ])
        db = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(),
            get=AsyncMock(return_value=batch),
            execute=AsyncMock(return_value=SimpleNamespace(one=lambda: (11, 7, 18))),
        )

        with ExitStack() as stack:
            stack.enter_context(patch(
                "app.services.speaker_revalidation.agent_model_id",
                new=AsyncMock(return_value="cloud-primary"),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.get_local_only",
                new=AsyncMock(return_value=False),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.select_fallback_models",
                new=AsyncMock(return_value=["endpoint:lab:qwen"]),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.run_speaker_context_batch",
                new=inner,
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.asyncio.sleep", new=AsyncMock(),
            ))
            await speaker_revalidation._run_batch(db, run, batch)

        self.assertEqual("completed", batch.status)
        self.assertEqual("", batch.error_message)
        self.assertEqual(2, batch.attempts)
        self.assertEqual(2, batch.enhanced_insights)
        self.assertEqual(3, batch.processed_entries)
        self.assertEqual("cloud-primary", batch.requested_model_id)
        self.assertEqual("endpoint:lab:qwen", batch.model_id)
        # Token usage is still attributed, because the fallback keeps the same
        # source label the batch query filters on.
        self.assertEqual(11, batch.input_tokens)
        self.assertEqual(18, batch.total_tokens)
        self.assertEqual("endpoint:lab:qwen", inner.await_args_list[1].kwargs["model_id"])
        db.rollback.assert_not_awaited()

    async def test_a_batch_with_no_fallback_still_fails_with_the_reworded_reason(self):
        run = SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            mapping_revision_id=uuid.uuid4(),
            status="running",
        )
        batch = self._batch()
        requeue_failed_batches(run, [batch])

        # The exact failure this issue was filed for: a Gemini spending cap.
        cap = _FakeGoogleClientError("429 RESOURCE_EXHAUSTED: spending cap")
        db = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(),
            get=AsyncMock(return_value=batch),
            execute=AsyncMock(return_value=SimpleNamespace(one=lambda: (0, 0, 0))),
        )

        with ExitStack() as stack:
            stack.enter_context(patch(
                "app.services.speaker_revalidation.agent_model_id",
                new=AsyncMock(return_value="cloud-primary"),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.get_local_only",
                new=AsyncMock(return_value=False),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.select_fallback_models",
                new=AsyncMock(return_value=[]),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.run_speaker_context_batch",
                new=AsyncMock(side_effect=cap),
            ))
            stack.enter_context(patch(
                "app.services.speaker_revalidation.asyncio.sleep", new=AsyncMock(),
            ))
            await speaker_revalidation._run_batch(db, run, batch)

        self.assertEqual("failed", batch.status)
        self.assertIn("Assign a self-hosted model", batch.error_message)
        self.assertIn("Gemini quota/spending cap exhausted", batch.error_message)


if __name__ == "__main__":
    unittest.main()

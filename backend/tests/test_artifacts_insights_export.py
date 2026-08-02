import uuid
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from openpyxl import load_workbook

from app.routers import artifacts
from app.routers.artifacts import export_insights, export_summary


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _Db:
    def __init__(self, questions):
        self.session = SimpleNamespace(name="Client Review")
        self._results = iter([_Result(questions), _Result([])])

    async def get(self, _model, _session_id):
        return self.session

    async def execute(self, _query):
        return next(self._results)


def _question(text: str, *, enhanced: bool):
    return SimpleNamespace(
        item_type="observation",
        lens_label="Discovery",
        question=text,
        rationale="Why it matters",
        source_context="Speaker 1 said it",
        vote=0,
        starred=False,
        answered=False,
        answer_summary="",
        needs_followup=False,
        followup_question="",
        offering_match="",
        enhanced=enhanced,
        dismissed=False,
        enrichment_notes="",
        agent_source="consolidated_analyst",
        revision_count=1 if enhanced else 0,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


class InsightsExportTests(IsolatedAsyncioTestCase):
    async def test_export_contains_each_base_and_enhanced_insight_once(self):
        db = _Db([
            _question("Base insight", enhanced=False),
            _question("Enhanced insight", enhanced=True),
        ])

        response = await export_insights(uuid.uuid4(), db=db)
        content = b"".join([chunk async for chunk in response.body_iterator])
        rows = list(load_workbook(BytesIO(content)).active.iter_rows(values_only=True))
        headers = rows[0]
        insight_col = headers.index("Insight")
        enhanced_col = headers.index("Enhanced")

        self.assertEqual(
            'attachment; filename="insights-Client_Review.xlsx"',
            response.headers["content-disposition"],
        )
        self.assertEqual(2, len(rows) - 1)
        self.assertEqual(
            {("Base insight", False), ("Enhanced insight", True)},
            {(row[insight_col], row[enhanced_col]) for row in rows[1:]},
        )


class _SummaryDb:
    def __init__(self, session):
        self.session = session
        self.execute = AsyncMock(side_effect=AssertionError("summary export queried synthesis directly"))

    async def get(self, _model, _session_id):
        return self.session


def _synthesis(owner):
    return SimpleNamespace(
        status="completed",
        top_outcomes=[{
            "title": "Decision",
            "summary": "Proceed with the pilot.",
            "rationale": "Evidence",
            "owner": owner,
            "status": "Pending",
        }],
        client_objectives=[],
        top_opportunities=[],
        risks_blockers=[],
        action_plan=[],
        unresolved_discovery_questions=[],
        strategic_signals=[],
        clusters=[],
        arbiter_notes="Settled",
    )


class SummaryExportTests(IsolatedAsyncioTestCase):
    async def test_export_uses_post_call_getter_and_changes_only_owner(self):
        session_id = uuid.uuid4()
        raw_owner = str(uuid.uuid4())
        session = SimpleNamespace(
            name="Client Review",
            meeting_type="general",
            started_at=None,
            ended_at=None,
        )
        raw = _synthesis(raw_owner)
        normalized = _synthesis("Maya Chen")
        db = _SummaryDb(session)

        with (
            patch.object(artifacts, "_footer", return_value="<footer>fixed</footer>"),
            patch.object(
                artifacts,
                "get_session_synthesis",
                new=AsyncMock(return_value=normalized),
            ) as get_synthesis,
        ):
            raw_html = artifacts._render_synthesis_html(session, raw)
            expected_html = raw_html.replace(raw_owner, "Maya Chen")
            response = await export_summary(session_id, db=db)
            content = b"".join([chunk async for chunk in response.body_iterator])

        self.assertEqual(expected_html.encode("utf-8"), content)
        self.assertEqual(
            'attachment; filename="briefing-Client_Review.html"',
            response.headers["content-disposition"],
        )
        get_synthesis.assert_awaited_once_with(session_id, mode="post_call")

    async def test_export_without_synthesis_keeps_legacy_response(self):
        session_id = uuid.uuid4()
        session = SimpleNamespace(name="Client Review")
        db = _SummaryDb(session)

        with (
            patch.object(
                artifacts,
                "get_session_synthesis",
                new=AsyncMock(return_value=None),
            ) as get_synthesis,
            patch.object(
                artifacts,
                "_render_legacy_summary_html",
                new=AsyncMock(return_value="<html>legacy</html>"),
            ),
        ):
            response = await export_summary(session_id, db=db)
            content = b"".join([chunk async for chunk in response.body_iterator])

        self.assertEqual(b"<html>legacy</html>", content)
        self.assertEqual(
            'attachment; filename="summary-Client_Review.html"',
            response.headers["content-disposition"],
        )
        get_synthesis.assert_awaited_once_with(session_id, mode="post_call")

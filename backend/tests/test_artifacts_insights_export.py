import uuid
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from openpyxl import load_workbook

from app.routers.artifacts import export_insights


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

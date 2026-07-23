import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.routers.sessions import enhance_insights_after_speaker_changes
from app.services.speaker_context_enhancer import (
    build_enhancement_prompt,
    mark_speaker_context_dirty_if_completed,
    run_speaker_context_enhancement,
    speaker_update_changes_enhancement_context,
)
from app.services.speaker_name_rewriter import (
    build_speaker_label_replacements,
    replace_speaker_labels,
)


class SpeakerContextEnhancerTests(unittest.TestCase):
    def test_detects_name_display_name_type_and_merge_relevant_changes(self):
        speaker = {
            "name": "Speaker 1",
            "role": "Account Manager",
            "display_name": "",
            "display_name_enabled": False,
            "speaker_type": "external",
        }

        self.assertTrue(speaker_update_changes_enhancement_context(speaker, {"name": "Sam"}))
        self.assertTrue(speaker_update_changes_enhancement_context(speaker, {"display_name": "Sam"}))
        self.assertTrue(speaker_update_changes_enhancement_context(speaker, {"display_name_enabled": True}))
        self.assertTrue(speaker_update_changes_enhancement_context(speaker, {"speaker_type": "team"}))

    def test_ignores_non_contextual_speaker_changes(self):
        speaker = {
            "name": "Speaker 1",
            "role": "Account Manager",
            "display_name": "",
            "display_name_enabled": False,
            "speaker_type": "external",
        }

        self.assertFalse(speaker_update_changes_enhancement_context(speaker, {"role": "Account Manager"}))
        self.assertFalse(speaker_update_changes_enhancement_context(speaker, {"color": "#f59e0b"}))

    def test_enhancement_prompt_includes_insights_transcript_and_speaker_context(self):
        prompt = build_enhancement_prompt(
            speakers=[
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "name": "Account Manager",
                    "role": "AM",
                    "speaker_type": "team",
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "name": "External 1",
                    "role": "CISO",
                    "speaker_type": "external",
                },
            ],
            insights=[
                {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "item_type": "opportunity",
                    "question": "Evaluate managed SIEM fit.",
                    "rationale": "Client pain was inferred.",
                    "source_context": "They need alerting help.",
                    "speaker_id": "11111111-1111-1111-1111-111111111111",
                }
            ],
            transcript_lines=[
                {
                    "text": "The client told us this is why we are here.",
                    "speaker_name": "Account Manager",
                    "speaker_id": "11111111-1111-1111-1111-111111111111",
                    "speaker_type": "team",
                },
                {
                    "text": "We still need to validate that with the client.",
                    "speaker_name": "External 1",
                    "speaker_id": "22222222-2222-2222-2222-222222222222",
                    "speaker_type": "external",
                },
            ],
        )

        self.assertIn("speaker_type=team", prompt)
        self.assertIn("speaker_type=external", prompt)
        self.assertIn("Evaluate managed SIEM fit.", prompt)
        self.assertIn("The client told us this is why we are here.", prompt)
        self.assertIn('"enhanced": true', prompt)
        self.assertIn('"op": "dismiss"', prompt)
        self.assertIn('"new_source_context"', prompt)
        self.assertIn("Do not change the item_type/category/tag of an existing insight", prompt)
        self.assertNotIn('"op": "elevate"', prompt)

    def test_speaker_label_replacement_uses_enabled_display_names(self):
        replacements = build_speaker_label_replacements([
            {
                "name": "Participant 1",
                "display_name": "Michael",
                "display_name_enabled": True,
            },
            {
                "name": "Participant 2",
                "display_name": "Disabled Name",
                "display_name_enabled": False,
            },
        ])

        text = "Participant 1 to revise. Context: participant 1 stated the ask. Participant 2 remains unchanged."

        self.assertEqual(
            "Michael to revise. Context: Michael stated the ask. Participant 2 remains unchanged.",
            replace_speaker_labels(text, replacements),
        )


class SpeakerContextEnhancerFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_session_context_change_advances_version(self):
        session = SimpleNamespace(
            state="completed",
            speaker_context_dirty=False,
            speaker_context_version=4,
        )
        db = SimpleNamespace(get=AsyncMock(return_value=session))

        changed = await mark_speaker_context_dirty_if_completed(db, uuid4())

        self.assertTrue(changed)
        self.assertTrue(session.speaker_context_dirty)
        self.assertEqual(5, session.speaker_context_version)

    async def test_insight_model_failure_is_raised_for_an_honest_api_failure(self):
        session = SimpleNamespace(meeting_type="general", meeting_context="")
        db = SimpleNamespace(
            get=AsyncMock(return_value=session),
            execute=AsyncMock(side_effect=[_ListResult([]), _ListResult([]), _ListResult([])]),
        )

        with (
            patch("app.services.speaker_context_enhancer.async_session", return_value=_AsyncContext(db)),
            patch(
                "app.services.speaker_context_enhancer.generate_text",
                new=AsyncMock(side_effect=RuntimeError("model offline")),
            ),
            patch(
                "app.services.speaker_context_enhancer._rewrite_speaker_labels",
                new=AsyncMock(return_value=set()),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "model offline"):
                await run_speaker_context_enhancement(uuid4())


class SpeakerContextEnhancementRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_unchanged_context_skips_all_ai_work(self):
        enhanced_at = datetime.now(timezone.utc)
        session = SimpleNamespace(
            state="completed",
            speaker_context_dirty=False,
            speaker_context_enhanced_at=enhanced_at,
        )
        db = SimpleNamespace(get=AsyncMock(return_value=session))

        with (
            patch(
                "app.routers.sessions.run_speaker_context_enhancement",
                new=AsyncMock(),
            ) as enhance,
            patch(
                "app.services.briefing_synthesis.run_session_synthesis",
                new=AsyncMock(),
            ) as refresh_briefing,
        ):
            result = await enhance_insights_after_speaker_changes(uuid4(), db)

        enhance.assert_not_awaited()
        refresh_briefing.assert_not_awaited()
        self.assertEqual(0, result["enhanced_insights"])
        self.assertFalse(result["briefing_updated"])
        self.assertEqual("unchanged", result["status"])
        self.assertEqual(enhanced_at, result["speaker_context_enhanced_at"])

    async def test_successful_insight_revalidation_regenerates_briefing(self):
        session = SimpleNamespace(
            state="completed",
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )
        db = SimpleNamespace(get=AsyncMock(return_value=session), commit=AsyncMock())
        enhancement_result = {
            "applied_operations": 2,
            "enhanced_insights": 4,
            "speaker_context_dirty": False,
            "speaker_context_enhanced_at": datetime.now(timezone.utc),
        }

        with (
            patch(
                "app.routers.sessions.run_speaker_context_enhancement",
                new=AsyncMock(return_value=enhancement_result),
            ),
            patch(
                "app.services.briefing_synthesis.run_session_synthesis",
                new=AsyncMock(return_value=SimpleNamespace(status="completed")),
            ) as refresh_briefing,
        ):
            result = await enhance_insights_after_speaker_changes(uuid4(), db)

        refresh_briefing.assert_awaited_once()
        self.assertTrue(result["briefing_updated"])
        self.assertEqual("completed", result["status"])
        self.assertEqual("completed", result["briefing_status"])
        self.assertFalse(result["speaker_context_dirty"])
        self.assertFalse(session.speaker_context_dirty)
        self.assertIsNotNone(session.speaker_context_enhanced_at)
        db.commit.assert_awaited_once()
        self.assertEqual(4, result["enhanced_insights"])

    async def test_partial_or_error_briefing_stays_dirty_and_retryable(self):
        for briefing_status in ("partial", "error"):
            with self.subTest(briefing_status=briefing_status):
                session = SimpleNamespace(
                    state="completed",
                    speaker_context_dirty=True,
                    speaker_context_enhanced_at=None,
                )
                db = SimpleNamespace(get=AsyncMock(return_value=session), commit=AsyncMock())
                enhancement_result = {
                    "applied_operations": 2,
                    "enhanced_insights": 4,
                    "speaker_context_dirty": False,
                    "speaker_context_enhanced_at": None,
                }

                with (
                    patch(
                        "app.routers.sessions.run_speaker_context_enhancement",
                        new=AsyncMock(return_value=enhancement_result),
                    ),
                    patch(
                        "app.services.briefing_synthesis.run_session_synthesis",
                        new=AsyncMock(return_value=SimpleNamespace(status=briefing_status)),
                    ),
                ):
                    result = await enhance_insights_after_speaker_changes(uuid4(), db)

                self.assertFalse(result["briefing_updated"])
                self.assertEqual("partial", result["status"])
                self.assertEqual(briefing_status, result["briefing_status"])
                self.assertTrue(result["speaker_context_dirty"])
                self.assertTrue(session.speaker_context_dirty)
                self.assertIsNone(session.speaker_context_enhanced_at)
                self.assertIn("Retry", result["error"])

    async def test_insight_failure_returns_actionable_error_and_keeps_retry_path(self):
        session = SimpleNamespace(
            state="completed",
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )
        db = SimpleNamespace(get=AsyncMock(return_value=session), commit=AsyncMock())

        with (
            patch(
                "app.routers.sessions.run_speaker_context_enhancement",
                new=AsyncMock(side_effect=RuntimeError("model offline")),
            ),
            patch(
                "app.services.briefing_synthesis.run_session_synthesis",
                new=AsyncMock(),
            ) as refresh_briefing,
        ):
            try:
                await enhance_insights_after_speaker_changes(uuid4(), db)
            except Exception as exc:
                error = exc
            else:
                self.fail("Expected insight revalidation failure")

        self.assertIsInstance(error, HTTPException)
        self.assertEqual(502, error.status_code)
        self.assertIn("retry", str(error.detail).lower())
        refresh_briefing.assert_not_awaited()
        self.assertTrue(session.speaker_context_dirty)


class _ListResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _AsyncContext:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


if __name__ == "__main__":
    unittest.main()

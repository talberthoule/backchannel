import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import BackgroundTasks

from app.routers.sessions import enhance_insights_after_speaker_changes
from app.services.speaker_context_enhancer import (
    build_enhancement_prompt,
    mark_speaker_context_dirty_if_completed,
    run_speaker_context_batch,
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

    async def test_batch_applies_and_stamps_only_assigned_insights_in_caller_transaction(self):
        question_id = uuid4()
        mapping_revision_id = uuid4()
        question = SimpleNamespace(
            id=question_id,
            item_type="observation",
            question="Assigned insight",
            rationale="Reason",
            source_context="Evidence",
            speaker_id=None,
            speaker=None,
            dismissed=False,
            answered=False,
            answer_summary="",
            enhanced=False,
            agent_source="general",
            speaker_mapping_revision_id=None,
        )
        session = SimpleNamespace(meeting_type="general", meeting_context="")
        speaker = SimpleNamespace(
            id=uuid4(),
            name="Participant",
            role="",
            speaker_type="external",
            display_name="",
            display_name_enabled=False,
        )
        load_db = SimpleNamespace(
            get=AsyncMock(return_value=session),
            execute=AsyncMock(
                side_effect=[
                    _ListResult([speaker]),
                    _ListResult([question]),
                    _ListResult([]),
                ]
            ),
        )
        apply_db = SimpleNamespace(get=AsyncMock(return_value=question))

        with (
            patch(
                "app.services.speaker_context_enhancer.async_session",
                return_value=_AsyncContext(load_db),
            ),
            patch(
                "app.services.speaker_context_enhancer.generate_text",
                new=AsyncMock(return_value="[]"),
            ) as generate,
            patch(
                "app.services.speaker_context_enhancer._apply_operations_in_db",
                new=AsyncMock(return_value=[]),
            ) as apply,
        ):
            result = await run_speaker_context_batch(
                uuid4(),
                [question_id],
                mapping_revision_id,
                apply_db,
            )

        self.assertIn("Assigned insight", generate.await_args.args[1])
        apply.assert_awaited_once()
        self.assertIs(apply.await_args.args[0], apply_db)
        self.assertEqual(mapping_revision_id, question.speaker_mapping_revision_id)
        self.assertEqual(1, result["processed_entries"])


class SpeakerContextEnhancementRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_unchanged_context_skips_all_ai_work(self):
        enhanced_at = datetime.now(timezone.utc)
        session = SimpleNamespace(
            state="completed",
            speaker_context_dirty=False,
            speaker_context_enhanced_at=enhanced_at,
        )
        db = SimpleNamespace(get=AsyncMock(return_value=session))

        background_tasks = BackgroundTasks()
        result = await enhance_insights_after_speaker_changes(
            uuid4(), background_tasks, db
        )

        self.assertFalse(result["briefing_updated"])
        self.assertEqual("unchanged", result["status"])
        self.assertEqual(enhanced_at, result["speaker_context_enhanced_at"])
        self.assertEqual([], background_tasks.tasks)

    async def test_dirty_context_starts_observable_background_run(self):
        run_id = uuid4()
        session = SimpleNamespace(
            state="completed",
            speaker_context_dirty=True,
            speaker_context_enhanced_at=None,
        )
        run = SimpleNamespace(id=run_id)
        db = SimpleNamespace(get=AsyncMock(return_value=session))
        summary = {
            "status": "running",
            "run_id": run_id,
            "speaker_context_dirty": True,
        }
        background_tasks = BackgroundTasks()

        with (
            patch(
                "app.routers.sessions.start_or_resume_revalidation",
                new=AsyncMock(return_value=(run, True)),
            ) as start,
            patch("app.routers.sessions.summarize_run", return_value=summary),
        ):
            result = await enhance_insights_after_speaker_changes(
                uuid4(), background_tasks, db
            )

        start.assert_awaited_once()
        self.assertEqual(summary, result)
        self.assertEqual(1, len(background_tasks.tasks))


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

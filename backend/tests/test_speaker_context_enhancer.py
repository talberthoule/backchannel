import unittest

from app.services.speaker_context_enhancer import (
    build_enhancement_prompt,
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


if __name__ == "__main__":
    unittest.main()

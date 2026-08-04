import unittest
from uuid import uuid4

from app.services.agents.base import TranscriptBuffer
from app.services.agents.consolidated_analyst import _normalize_speaker_id
from app.services.agents.speaker_context import format_speaker_context, format_speakers_list


class SpeakerAttributionTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcript_buffer_includes_speaker_id_when_available(self):
        speaker_id = str(uuid4())
        buffer = TranscriptBuffer()

        await buffer.add("We need Mark to follow up.", "Speaker 1", speaker_id=speaker_id)

        window = await buffer.get_window()
        self.assertIn("Speaker 1", window)
        self.assertIn(f"speaker_id={speaker_id}", window)

    async def test_transcript_buffer_omits_per_line_speaker_type(self):
        # speaker_type is constant per speaker and stated once in the
        # Participants legend; repeating it per line was ~11 percent of every
        # transcript payload and nothing ever parsed it back (ALP-282).
        speaker_id = str(uuid4())
        buffer = TranscriptBuffer()

        await buffer.add(
            "The client told us this is why we are here.",
            "Account Manager",
            speaker_id=speaker_id,
            speaker_type="team",
        )

        window = await buffer.get_window()
        self.assertNotIn("speaker_type", window)
        # The attribution round-trip still works: the UUID is still on the line.
        self.assertIn(f"speaker_id={speaker_id}", window)

    async def test_participants_legend_still_carries_speaker_type(self):
        speaker_id = str(uuid4())
        legend = format_speakers_list([
            {"id": speaker_id, "name": "Account Manager", "speaker_type": "team", "role": "AE"},
        ])
        self.assertIn("speaker_type=team", legend)

    async def test_transcript_buffer_omits_missing_speaker_id(self):
        buffer = TranscriptBuffer()

        await buffer.add("No speaker id yet.", "Unknown")

        window = await buffer.get_window()
        self.assertEqual("[Unknown]: No speaker id yet.", window)


class SpeakerIdNormalizationTests(unittest.TestCase):
    def test_normalize_speaker_id_accepts_valid_known_id(self):
        speaker_id = str(uuid4())

        self.assertEqual(speaker_id, _normalize_speaker_id(speaker_id, {speaker_id}))

    def test_normalize_speaker_id_rejects_unknown_or_blank_values(self):
        known_id = str(uuid4())

        self.assertIsNone(_normalize_speaker_id(str(uuid4()), {known_id}))
        self.assertIsNone(_normalize_speaker_id("", {known_id}))
        self.assertIsNone(_normalize_speaker_id(None, {known_id}))


class SpeakerContextFormattingTests(unittest.TestCase):
    def test_format_speaker_context_includes_type_and_display_name(self):
        speaker_id = str(uuid4())

        context = format_speaker_context({
            "id": speaker_id,
            "name": "Speaker 2",
            "display_name": "Dana Client",
            "display_name_enabled": True,
            "role": "CISO",
            "speaker_type": "external",
        })

        self.assertEqual(
            "- Dana Client [speaker_id="
            f"{speaker_id}; speaker_type=external] (CISO)",
            context,
        )

    def test_format_speakers_list_warns_team_summaries_are_not_client_evidence(self):
        context = format_speakers_list([
            {
                "id": str(uuid4()),
                "name": "Account Manager",
                "role": "Account Manager",
                "speaker_type": "team",
            },
            {
                "id": str(uuid4()),
                "name": "External 1",
                "role": "Client",
                "speaker_type": "external",
            },
        ])

        self.assertIn("Account Manager", context)
        self.assertIn("speaker_type=team", context)
        self.assertIn("External 1", context)
        self.assertIn("speaker_type=external", context)


if __name__ == "__main__":
    unittest.main()

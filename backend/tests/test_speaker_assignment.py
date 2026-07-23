import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.models import Speaker
from app.services.speaker_assignment import (
    auto_speaker_would_create_new_speaker,
    is_unknown_auto_speaker,
    resolve_existing_auto_speaker,
    resolve_live_mic_speaker,
    load_live_mic_voice_embedding,
)
from app.services.voice_enrollment import LOCAL_VOICE_PROFILE_ID


def _speaker(name: str, is_user: bool) -> Speaker:
    return Speaker(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        name=name,
        is_user=is_user,
    )


class SpeakerAssignmentTests(unittest.TestCase):
    def test_unknown_auto_speaker_recognizes_track_prefixes(self):
        self.assertTrue(is_unknown_auto_speaker("auto_unknown"))
        self.assertTrue(is_unknown_auto_speaker("sys_auto_unknown"))
        self.assertFalse(is_unknown_auto_speaker("auto_1"))

    def test_live_mic_resolves_to_sole_user_when_split_track_is_established(self):
        user = _speaker("Me", True)
        participant = _speaker("Remote", False)

        resolved = resolve_live_mic_speaker("auto_1", [user, participant], True)

        self.assertIs(user, resolved)

    def test_live_mic_resolution_does_not_claim_system_or_mic_only_audio(self):
        user = _speaker("Me", True)

        self.assertIsNone(resolve_live_mic_speaker("sys_auto_1", [user], True))
        self.assertIsNone(resolve_live_mic_speaker("auto_1", [user], False))

    def test_enrolled_mic_only_voice_resolves_to_sole_user(self):
        user = _speaker("Me", True)

        self.assertIs(
            user,
            resolve_live_mic_speaker(LOCAL_VOICE_PROFILE_ID, [user], False),
        )
        self.assertIsNone(resolve_live_mic_speaker("auto_1", [user], False))
        self.assertIsNone(
            resolve_live_mic_speaker(
                f"sys_{LOCAL_VOICE_PROFILE_ID}",
                [user],
                True,
            )
        )

    def test_enrolled_mic_only_voice_requires_exactly_one_user(self):
        self.assertIsNone(
            resolve_live_mic_speaker(LOCAL_VOICE_PROFILE_ID, [], False)
        )
        self.assertIsNone(
            resolve_live_mic_speaker(
                LOCAL_VOICE_PROFILE_ID,
                [_speaker("Me", True), _speaker("Other local", True)],
                False,
            )
        )

    def test_live_mic_resolution_requires_exactly_one_user(self):
        self.assertIsNone(resolve_live_mic_speaker("auto_1", [], True))
        self.assertIsNone(
            resolve_live_mic_speaker(
                "auto_1",
                [_speaker("Me", True), _speaker("Other local", True)],
                True,
            )
        )

    def test_live_mic_resolution_preserves_first_remote_slot(self):
        user = _speaker("Me", True)
        participant = _speaker("Remote", False)
        auto_speaker_map: dict[str, str] = {}

        self.assertIs(user, resolve_live_mic_speaker("auto_1", [user, participant], True))
        resolved_remote = resolve_existing_auto_speaker(
            "sys_auto_1", auto_speaker_map, [user, participant]
        )

        self.assertIs(participant, resolved_remote)
        self.assertEqual({"sys_auto_1": str(participant.id)}, auto_speaker_map)

    def test_first_auto_speaker_does_not_claim_user_without_enrollment(self):
        user = _speaker("Me", True)
        participant = _speaker("Speaker 2", False)
        auto_speaker_map: dict[str, str] = {}

        resolved = resolve_existing_auto_speaker("auto_1", auto_speaker_map, [user, participant])

        self.assertEqual(participant.id, resolved.id)
        self.assertEqual(str(participant.id), auto_speaker_map["auto_1"])

    def test_user_only_roster_forces_auto_created_speaker(self):
        auto_speaker_map: dict[str, str] = {}

        self.assertTrue(
            auto_speaker_would_create_new_speaker(
                "auto_1",
                auto_speaker_map,
                [_speaker("Me", True)],
            )
        )


class LiveMicVoiceEmbeddingTests(unittest.IsolatedAsyncioTestCase):
    @patch(
        "app.services.speaker_assignment.load_local_voice_embedding",
        new_callable=AsyncMock,
    )
    async def test_loads_enrollment_only_for_sole_user(self, load_embedding):
        expected = object()
        load_embedding.return_value = expected
        db = object()

        actual = await load_live_mic_voice_embedding(
            db,
            [_speaker("Me", True), _speaker("Remote", False)],
        )

        self.assertIs(expected, actual)
        load_embedding.assert_awaited_once_with(db)

    @patch(
        "app.services.speaker_assignment.load_local_voice_embedding",
        new_callable=AsyncMock,
    )
    async def test_skips_enrollment_without_exactly_one_user(self, load_embedding):
        self.assertIsNone(await load_live_mic_voice_embedding(object(), []))
        self.assertIsNone(
            await load_live_mic_voice_embedding(
                object(),
                [_speaker("One", True), _speaker("Two", True)],
            )
        )
        load_embedding.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

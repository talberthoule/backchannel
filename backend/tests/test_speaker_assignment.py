import unittest
import uuid

from app.models import Speaker
from app.services.speaker_assignment import auto_speaker_would_create_new_speaker, resolve_existing_auto_speaker


def _speaker(name: str, is_user: bool) -> Speaker:
    return Speaker(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        name=name,
        is_user=is_user,
    )


class SpeakerAssignmentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

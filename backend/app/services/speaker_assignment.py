"""Helpers for mapping diarizer speaker IDs to session speaker rows."""

from app.models import Speaker


def assignable_speakers(speakers: list[Speaker]) -> list[Speaker]:
    """Return speaker rows that can be assigned from live diarization.

    The diarizer has no voice enrollment for the local user, so the backend
    should not assume the first detected voice is the user.
    """
    return [speaker for speaker in speakers if not speaker.is_user]


def resolve_live_mic_speaker(
    auto_id: str,
    speakers: list[Speaker],
    split_track_established: bool,
) -> Speaker | None:
    """Return the known local user for mic audio in a split-track live call.

    This policy is intentionally limited to sessions with exactly one user
    row. Mic-only sessions keep normal diarization behavior.
    """
    if not split_track_established or auto_id.startswith("sys_"):
        return None
    users = [speaker for speaker in speakers if speaker.is_user]
    return users[0] if len(users) == 1 else None


def auto_speaker_would_create_new_speaker(
    auto_id: str,
    auto_speaker_map: dict[str, str],
    speakers: list[Speaker],
) -> bool:
    if auto_id in auto_speaker_map:
        return False
    return len(auto_speaker_map) >= len(assignable_speakers(speakers))


def resolve_existing_auto_speaker(
    auto_id: str,
    auto_speaker_map: dict[str, str],
    speakers: list[Speaker],
) -> Speaker | None:
    if auto_id in auto_speaker_map:
        speaker_id = auto_speaker_map[auto_id]
        return next((speaker for speaker in speakers if str(speaker.id) == speaker_id), None)

    candidates = assignable_speakers(speakers)
    idx = len(auto_speaker_map)
    if 0 <= idx < len(candidates):
        speaker = candidates[idx]
        auto_speaker_map[auto_id] = str(speaker.id)
        return speaker

    return None

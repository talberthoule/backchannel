TEAM_SPEAKER_TYPE = "team"
EXTERNAL_SPEAKER_TYPE = "external"
VALID_SPEAKER_TYPES = {TEAM_SPEAKER_TYPE, EXTERNAL_SPEAKER_TYPE}


def normalize_speaker_type(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() in VALID_SPEAKER_TYPES:
        return value.strip().lower()
    return EXTERNAL_SPEAKER_TYPE


def speaker_display_name(speaker: dict) -> str:
    display_name = str(speaker.get("display_name") or "").strip()
    if display_name and speaker.get("display_name_enabled"):
        return display_name
    return str(speaker.get("name") or "Unknown").strip() or "Unknown"


def format_speaker_context(speaker: dict) -> str:
    name = speaker_display_name(speaker)
    speaker_id = str(speaker.get("id") or "").strip()
    speaker_type = normalize_speaker_type(speaker.get("speaker_type"))
    role = str(speaker.get("role") or "").strip()

    identity_parts = []
    if speaker_id:
        identity_parts.append(f"speaker_id={speaker_id}")
    identity_parts.append(f"speaker_type={speaker_type}")

    line = f"- {name} [{'; '.join(identity_parts)}]"
    if role:
        line += f" ({role})"
    return line


def format_speakers_list(speakers: list[dict]) -> str:
    if not speakers:
        return "(No speaker information)"
    return "\n".join(format_speaker_context(speaker) for speaker in speakers)


def format_transcript_segment(
    text: str,
    speaker_name: str | None = None,
    speaker_id: str | None = None,
    speaker_type: str | None = None,
) -> str:
    name = speaker_name or "Unknown"
    metadata = []
    if speaker_id:
        metadata.append(f"speaker_id={speaker_id}")
    if speaker_type:
        metadata.append(f"speaker_type={normalize_speaker_type(speaker_type)}")
    if metadata:
        return f"[{name} | {'; '.join(metadata)}]: {text}"
    return f"[{name}]: {text}"

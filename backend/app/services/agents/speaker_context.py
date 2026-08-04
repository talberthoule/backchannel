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
    """Render one transcript line for a prompt.

    speaker_type is accepted for call-site compatibility but deliberately not
    emitted: it is a constant per speaker, already stated once per speaker in
    the Participants legend, and nothing parses it back out of model output.
    Repeating it on every line cost about 11 percent of every transcript
    payload, multiplied by how often each window is re-read (ALP-282).
    """
    name = speaker_name or "Unknown"
    if speaker_id:
        return f"[{name} | speaker_id={speaker_id}]: {text}"
    return f"[{name}]: {text}"

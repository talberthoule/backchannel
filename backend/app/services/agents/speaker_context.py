"""How speakers are named to a model, and how a name comes back.

Every transcript line used to carry the speaker's full 36-character UUID.
On a measured 57-minute meeting that was 48 percent of the formatted
transcript payload, and the transcript window is re-read seven to nine times
per utterance across the live agents, so the overhead was multiplied rather
than paid once. Lines now carry a short alias - ``[S3]: text`` - with one
legend per prompt binding each alias to a real name, role and side. The alias
form is about 45 percent smaller (ALP-282).

The alias map is derived, never stored. Nothing persisted depends on it:
every database write still uses the real UUID. A fresh orchestrator on a
resumed call re-derives the identical map from the same ordered roster, which
is the single most important property of the design - and the reason a rename
mid-call never shifts an alias, because the roster is only ever appended to.

On the way back the model may return either an alias or a raw UUID, and
``resolve_speaker_reference`` turns either into the canonical UUID or None.
Accepting both is what keeps a user-customized prompt that still asks for
UUIDs working, and the save boundary in the orchestrator stays UUID-only.
"""

TEAM_SPEAKER_TYPE = "team"
EXTERNAL_SPEAKER_TYPE = "external"
VALID_SPEAKER_TYPES = {TEAM_SPEAKER_TYPE, EXTERNAL_SPEAKER_TYPE}

# The alias prefix. Deliberately short and deliberately not a word, so it does
# not read as part of anyone's name if it ever leaks into prose.
ALIAS_PREFIX = "S"


def normalize_speaker_type(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() in VALID_SPEAKER_TYPES:
        return value.strip().lower()
    return EXTERNAL_SPEAKER_TYPE


def speaker_display_name(speaker: dict) -> str:
    display_name = str(speaker.get("display_name") or "").strip()
    if display_name and speaker.get("display_name_enabled"):
        return display_name
    return str(speaker.get("name") or "Unknown").strip() or "Unknown"


def build_speaker_aliases(speakers: list[dict]) -> dict[str, str]:
    """``{speaker_id: "S1"}`` in the roster's own order.

    Every loader orders by ``Speaker.created_at`` and the live roster is
    appended to in that same order, so this is stable across a rebuild without
    anything being written down. Ids repeated in the roster - which a stale
    in-memory copy can hold after a merge - keep the first alias assigned to
    them rather than consuming a second number.
    """
    aliases: dict[str, str] = {}
    for speaker in speakers or []:
        speaker_id = str(speaker.get("id") or "").strip()
        if speaker_id and speaker_id not in aliases:
            aliases[speaker_id] = f"{ALIAS_PREFIX}{len(aliases) + 1}"
    return aliases


def alias_to_id(aliases: dict[str, str]) -> dict[str, str]:
    """The reverse map, casefolded, for reading model output.

    When two ids share an alias - a merge folded one into the other - the
    surviving id is whichever the roster lists first, which is the one the
    legend named.
    """
    reverse: dict[str, str] = {}
    for speaker_id, alias in aliases.items():
        reverse.setdefault(alias.casefold(), speaker_id)
    return reverse


def resolve_speaker_reference(
    raw: object,
    aliases: dict[str, str] | None = None,
    valid_speaker_ids: set[str] | None = None,
) -> str | None:
    """An alias or a UUID from model output, as a known canonical UUID or None.

    An unknown reference fails exactly the way an unknown UUID always did: the
    insight is saved with no speaker rather than with the wrong one. That is
    easier to get right with aliases, not harder, because the model is picking
    a two-character token from a set of five rather than copying a UUID.
    """
    import uuid as _uuid

    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = raw.strip()

    resolved = alias_to_id(aliases or {}).get(candidate.casefold())
    if resolved is None:
        try:
            resolved = str(_uuid.UUID(candidate))
        except ValueError:
            return None
    if valid_speaker_ids is None:
        return resolved
    return resolved if resolved in valid_speaker_ids else None


def format_speaker_context(speaker: dict, alias: str | None = None) -> str:
    name = speaker_display_name(speaker)
    speaker_id = str(speaker.get("id") or "").strip()
    speaker_type = normalize_speaker_type(speaker.get("speaker_type"))
    role = str(speaker.get("role") or "").strip()

    if alias:
        # The legend is the only place the binding is stated, so it states it
        # once and completely; the UUID is not repeated here because nothing
        # reads it back off this line any more.
        line = f"- {alias} = {name} [{speaker_type}]"
    else:
        identity_parts = []
        if speaker_id:
            identity_parts.append(f"speaker_id={speaker_id}")
        identity_parts.append(f"speaker_type={speaker_type}")
        line = f"- {name} [{'; '.join(identity_parts)}]"
    if role:
        line += f" ({role})"
    return line


def format_speakers_list(speakers: list[dict], aliases: dict[str, str] | None = None) -> str:
    """The Participants legend.

    Without ``aliases`` this keeps the old UUID-bearing shape, which is what a
    caller that has no roster order to derive from should get.
    """
    if not speakers:
        return "(No speaker information)"
    return "\n".join(
        format_speaker_context(speaker, (aliases or {}).get(str(speaker.get("id") or "")))
        for speaker in speakers
    )


def format_transcript_segment(
    text: str,
    speaker_name: str | None = None,
    speaker_id: str | None = None,
    speaker_type: str | None = None,
    alias: str | None = None,
) -> str:
    """Render one transcript line for a prompt.

    With an alias the line is ``[S3]: text`` and the reader looks S3 up in the
    Participants legend. Without one it keeps the name-and-UUID shape, so a
    caller with no roster to derive aliases from still produces something the
    model can attribute.

    speaker_type is accepted for call-site compatibility but deliberately not
    emitted: it is a constant per speaker, already stated once per speaker in
    the legend, and nothing parses it back out of model output. Repeating it on
    every line cost about 11 percent of every transcript payload, multiplied by
    how often each window is re-read (ALP-282, phase 1).
    """
    if alias:
        return f"[{alias}]: {text}"
    name = speaker_name or "Unknown"
    if speaker_id:
        return f"[{name} | speaker_id={speaker_id}]: {text}"
    return f"[{name}]: {text}"

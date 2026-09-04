"""Stable-first prompt layout, and the split into system and user turns.

A prompt cache can only reuse a stable *prefix*. Everything downstream of the
first changed byte is re-read at full price, so a static instruction block
sitting after a volatile placeholder is instructions that can never be cached -
and worse, it pushes the material that *is* identical between cycles behind
something that never is.

Two mechanical transforms, both applied to the template *before* it is
formatted, so they see placeholders rather than substituted content:

``stable_first`` moves every section holding a per-cycle placeholder to the
end, preserving order within the stable group and within the volatile group.

``split_layers`` then cuts at the first volatile section: everything above
becomes the system instruction, everything from there down becomes the user
turn. The model receives instructions once, as instructions, and a user turn
that is the data payload and nothing else.

Why here and not in the templates. ``agent_configs.prompt`` holds a
user-editable copy of each template and that copy is what actually runs, and
seeding has never rewritten a stored prompt. Fixing the constants in
``prompts.py`` therefore reaches a fresh install and nobody else. Normalizing
at the format seam reaches every install, including one whose prompt a user
edited into a worse order, and it costs a string operation per cycle (ALP-285).

What counts as volatile is a judgement about *sharing between calls*, not about
whether a value can ever change. ``directives_text`` and ``document_summaries``
change only when someone types a directive or uploads a file, so across the
dozens of cycles in one call they are constants and belong in the prefix.
``speakers_text`` grows when a speaker is enrolled, which invalidates the
prefix from that point once per new voice - much cheaper than moving it below
the transcript, where it would be re-read every cycle regardless.

A template with no ``##`` headings is one section. It reorders to itself and
splits to an empty system instruction, which is exactly today's behavior: a
custom prompt that does not use the app's structure is passed through
untouched rather than guessed at.
"""

from __future__ import annotations

import re

# Placeholders whose value is different on essentially every cycle.
VOLATILE_PLACEHOLDERS = frozenset({
    "transcript_window",
    "transcript_text",
    "insights_json",
    "insights_text",
    "active_questions",
    "recent_objections",
    "opportunities_json",
    "signal_history_text",
    "meeting_lens_json",
    "discovery_lens_json",
})

_HEADING = re.compile(r"^##\s", re.MULTILINE)
# A doubled brace is a literal brace in a JSON example, not a placeholder.
_PLACEHOLDER = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def sections(template: str) -> list[str]:
    """Split on ``##`` headings, keeping each heading with its body.

    The text before the first heading is a section too: it is the role
    preamble, and it is the most stable thing in any of these templates.
    """
    starts = [match.start() for match in _HEADING.finditer(template)]
    if not starts:
        return [template]
    bounds = ([0] if starts[0] > 0 else []) + starts
    return [template[start:end] for start, end in zip(bounds, bounds[1:] + [len(template)])]


def is_volatile(section: str) -> bool:
    return bool(placeholders(section) & VOLATILE_PLACEHOLDERS)


def stable_first(template: str) -> str:
    """Reorder so no static section follows a volatile one.

    Returns the template unchanged when it is already in order, so a caller
    can tell whether anything moved and a stored prompt that was already
    correct is byte-identical afterwards.
    """
    parts = sections(template)
    if len(parts) < 2:
        return template
    stable = [part for part in parts if not is_volatile(part)]
    volatile = [part for part in parts if is_volatile(part)]
    if not volatile or not stable:
        return template
    return "".join(stable + volatile)


def split_layers(template: str) -> tuple[str, str]:
    """``(system, user)``: the instruction prefix, then the data payload.

    Cuts at the first volatile section of an already-reordered template. An
    empty system half means there was nothing to lift - a single-section
    custom prompt, or a template whose very first section carries volatile
    data - and the caller sends the whole thing as the user turn, exactly as
    before.
    """
    parts = sections(stable_first(template))
    for index, part in enumerate(parts):
        if is_volatile(part):
            return "".join(parts[:index]).rstrip(), "".join(parts[index:])
    # Nothing volatile at all: the whole template is instructions. Keep it in
    # the user turn rather than sending an empty request.
    return "", template


def format_layers(template: str, **values) -> tuple[str | None, str]:
    """Reorder, split, and format both halves from the same values.

    ``system`` is None, not "", when there was nothing to lift: a
    single-section custom prompt, or a template whose first section already
    carries volatile data. The caller then sends the user half alone, which is
    what every agent did before this existed.
    """
    system, user = split_layers(template)
    rendered_user = user.format(**values)
    if not system.strip():
        return None, rendered_user
    return system.format(**values), rendered_user


def trailing_static(template: str) -> str:
    """Static text after the LAST placeholder. The regression guard reads this."""
    matches = list(_PLACEHOLDER.finditer(template))
    if not matches:
        return ""
    return template[matches[-1].end():].strip()


def static_after_volatile(template: str) -> list[str]:
    """Static sections that sit after the first volatile one.

    Each is a block of instructions no prefix cache can ever reach. An empty
    list is the invariant this module exists to hold.
    """
    parts = sections(template)
    seen_volatile = False
    stranded = []
    for part in parts:
        if is_volatile(part):
            seen_volatile = True
        elif seen_volatile:
            stranded.append(part)
    return stranded

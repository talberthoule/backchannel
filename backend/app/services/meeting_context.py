"""Session-level meeting context helpers."""

from __future__ import annotations

from typing import Any

DEFAULT_MEETING_TYPE = "general"

MEETING_TYPE_LABELS = {
    "general": "General / infer from conversation",
    "client_sales": "Client or prospect conversation",
    "customer_delivery": "Customer delivery or project working session",
    "internal_enablement": "Internal enablement or training",
    "internal_checkin": "Internal check-in or relationship conversation",
    "vendor_partner": "Vendor or partner conversation",
}

MEETING_TYPE_GUIDANCE = {
    "general": [
        "Infer the conversation type from the transcript, participants, directives, and context.",
        "Do not assume this is a client, sales, or deal conversation unless the evidence supports that.",
        "Use neutral language such as participants, counterparty, objectives, topics, and follow-ups.",
    ],
    "client_sales": [
        "This may involve a client, prospect, buying committee, or account team.",
        "It is appropriate to surface client objectives, buying signals, commercial opportunities, risks, blockers, and next seller actions when supported by evidence.",
        "Treat offering or services opportunities as useful only when grounded in the conversation.",
    ],
    "customer_delivery": [
        "This is primarily about delivery, implementation, operations, or project execution.",
        "Focus on decisions, dependencies, blockers, owners, technical risks, timeline changes, and follow-up actions.",
        "Surface commercial expansion only if it is explicitly relevant, not by default.",
    ],
    "internal_enablement": [
        "This is an internal knowledge-transfer, enablement, or training conversation.",
        "Focus on learning objectives, key technical concepts, misconceptions, unanswered learner questions, enablement gaps, reusable talk tracks, and follow-up materials.",
        "Do not invent client needs, buying signals, or sales opportunities.",
    ],
    "internal_checkin": [
        "This is an internal relationship, coaching, or check-in conversation.",
        "Focus on people context, commitments, concerns, decisions, blockers, support needs, and follow-ups.",
        "Avoid turning casual internal discussion into sales opportunities unless the transcript clearly shifts there.",
    ],
    "vendor_partner": [
        "This may involve a vendor, partner, alliance contact, or program owner.",
        "Focus on vendor roadmap, program updates, partner motions, commitments, risks, dependencies, asks, and follow-up questions.",
        "Do not treat the external speaker as a client unless the transcript says they are acting as one.",
    ],
}

OFFERING_MATCH_MEETING_TYPES = {"client_sales", "customer_delivery"}


def normalize_meeting_type(value: object) -> str:
    if isinstance(value, str) and value in MEETING_TYPE_LABELS:
        return value
    return DEFAULT_MEETING_TYPE


def build_meeting_context_text(session_or_type: Any = None, meeting_context: str | None = None) -> str:
    if isinstance(session_or_type, str):
        meeting_type = normalize_meeting_type(session_or_type)
        context = meeting_context or ""
    else:
        meeting_type = normalize_meeting_type(getattr(session_or_type, "meeting_type", DEFAULT_MEETING_TYPE))
        context = meeting_context
        if context is None:
            context = getattr(session_or_type, "meeting_context", "") or getattr(session_or_type, "notes", "") or ""

    guidance = MEETING_TYPE_GUIDANCE[meeting_type]
    guidance_text = "\n".join(f"- {line}" for line in guidance)
    context_text = context.strip() if isinstance(context, str) else ""

    return "\n".join(
        [
            f"Meeting type: {MEETING_TYPE_LABELS[meeting_type]}",
            f"User-provided context: {context_text or '(No additional context provided)'}",
            "Interpretation guidance:",
            "- `speaker_type=team` means an internal participant from the user's organization.",
            "- `speaker_type=external` means external to the internal team; it may be a client, vendor, partner, candidate, or other party depending on this meeting context.",
            "- Prefer transcript evidence over assumptions from generic labels.",
            guidance_text,
        ]
    )


def ensure_meeting_context_placeholder(prompt_template: str) -> str:
    if "{meeting_context_text}" in prompt_template:
        return prompt_template
    return (
        "## Meeting Context\n{meeting_context_text}\n\n"
        "This Meeting Context overrides any generic client, sales, seller, or deal-team wording that may appear in the reusable prompt below. "
        "Adapt analysis to the actual conversation type.\n\n"
        + prompt_template
    )


def format_prompt_with_meeting_context(
    prompt_template: str,
    meeting_context_text: str,
    **values: Any,
) -> str:
    template = ensure_meeting_context_placeholder(prompt_template)
    return template.format(meeting_context_text=meeting_context_text, **values)


def should_match_offerings(meeting_type: object) -> bool:
    return normalize_meeting_type(meeting_type) in OFFERING_MATCH_MEETING_TYPES

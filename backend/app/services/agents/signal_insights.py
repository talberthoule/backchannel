"""Strategic signals as first-class live insights.

The live panel only has room for the few signals that matter right now, but a
signal that misses the panel is not noise - it is an observation the analysis
already paid for. Every signal the strategic-signals agent emits therefore also
exists as an ordinary insight row, so it can be read, starred, voted, dismissed
and exported exactly like consolidated-analyst output.

Two item types carry the lifecycle:

- ``signal``          - emitted by the most recent cycle.
- ``signal_history``  - emitted by an earlier cycle and no longer current.

The signals currently on the panel are listed alongside their cards: the
Strategic filter is the complete strategic picture, panel included (the
original ALP-308 suppression of panel rows was reversed by user request). A
row's ``updated_at`` is stamped whenever a cycle changes it - in particular
when it retires into ``signal_history`` - so the client can surface the most
recently retired signals under the Strategic filter as well.

Ownership note: these rows belong to the strategic-signals agent. They are kept
out of the context fed back to that agent (its own output is not evidence) and
out of the synthesizer's corpus, for the same reason `asked` insights are - a
second agent rewriting them would fight the one that produces them.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from app.database import async_session
from app.models import Question

logger = logging.getLogger(__name__)

SIGNAL_ITEM_TYPE = "signal"
SIGNAL_HISTORY_ITEM_TYPE = "signal_history"
SIGNAL_ITEM_TYPES = (SIGNAL_ITEM_TYPE, SIGNAL_HISTORY_ITEM_TYPE)
SIGNAL_AGENT_SOURCE = "strategic_signals"

# How many signals the live panel shows. The rest become insight rows.
LIVE_SIGNAL_PANEL_SIZE = 3

# Section order is the tie-break when the model does not rank an item, and the
# label each row carries as its badge. Mirrored by getLiveSignalCards in
# frontend/src/components/ActiveCall/SynthesisSignals.tsx - the two must agree
# on which signals are on the panel, and both are tested against it.
SIGNAL_SECTIONS: tuple[tuple[str, str], ...] = (
    ("strategic_signals", "Signal"),
    ("risks_blockers", "Risk"),
    ("unresolved_discovery_questions", "Next Question"),
    ("top_opportunities", "Opportunity"),
    ("action_plan", "Action Cue"),
)

# An unranked item sorts after every ranked one rather than ahead of rank 1.
_UNRANKED = 10_000


def signal_identity(value: Any) -> str:
    """Match _signal_identity in briefing_synthesis, so one signal is one row."""
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip().rstrip(" .,:;!?")


def _item_text(item: Any) -> str:
    return (getattr(item, "title", "") or "").strip() or (getattr(item, "summary", "") or "").strip()


def ordered_signal_items(arbiter_output) -> list[dict]:
    """Every signal in the cycle, most important first.

    Ordered by the model's own ``priority`` (1 is most important), then by
    section order for anything it left unranked.
    """
    entries: list[dict] = []
    for section_index, (section, label) in enumerate(SIGNAL_SECTIONS):
        for item in getattr(arbiter_output, section, None) or []:
            text = _item_text(item)
            if not text:
                continue
            priority = getattr(item, "priority", 0) or 0
            entries.append(
                {
                    "section": section,
                    "label": label,
                    "identity": signal_identity(text),
                    "title": text,
                    "summary": (getattr(item, "summary", "") or "").strip(),
                    "rationale": (getattr(item, "rationale", "") or "").strip(),
                    "priority": priority,
                    "_sort": (priority if priority > 0 else _UNRANKED, section_index),
                }
            )

    entries.sort(key=lambda entry: entry["_sort"])
    # Two sections can legitimately return the same observation; the first
    # (most important) wins and the duplicate is dropped rather than becoming a
    # second row saying the same thing.
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in entries:
        if entry["identity"] in seen:
            continue
        seen.add(entry["identity"])
        unique.append(entry)
    return unique


def _row_payload(question: Question) -> dict:
    return {
        "id": str(question.id),
        "item_type": question.item_type,
        "lens_label": question.lens_label,
        "question": question.question,
        "rationale": question.rationale,
        "source_context": question.source_context,
        "speaker_id": None,
        "directive_id": None,
        "is_followup": False,
        "timestamp": question.created_at.isoformat(),
        "updated_at": question.updated_at.isoformat() if question.updated_at else None,
        "agent_source": question.agent_source,
        "offering_match": "",
        "enhanced": False,
    }


async def sync_signal_insights(
    session_id: uuid.UUID,
    arbiter_output,
) -> dict[str, list[dict]]:
    """Reconcile this cycle's signals with the session's signal insight rows.

    Returns ``{"created": [...], "updated": [...]}`` payloads for broadcast.
    Rows the user dismissed stay dismissed: the agent re-emitting a signal the
    user has already waved away must not resurrect it.
    """
    entries = ordered_signal_items(arbiter_output)
    current_by_identity = {entry["identity"]: entry for entry in entries}

    created: list[dict] = []
    updated: list[dict] = []

    async with async_session() as db:
        result = await db.execute(
            select(Question).where(
                Question.session_id == session_id,
                Question.item_type.in_(SIGNAL_ITEM_TYPES),
            )
        )
        rows = list(result.scalars().all())
        by_identity = {signal_identity(row.question): row for row in rows}

        for identity, entry in current_by_identity.items():
            row = by_identity.get(identity)
            if row is None:
                row = Question(
                    session_id=session_id,
                    item_type=SIGNAL_ITEM_TYPE,
                    lens_label=entry["label"][:120],
                    question=entry["title"],
                    rationale=entry["rationale"] or entry["summary"],
                    source_context="",
                    agent_source=SIGNAL_AGENT_SOURCE,
                )
                db.add(row)
                await db.flush()
                await db.refresh(row)
                created.append(_row_payload(row))
                continue

            if row.dismissed:
                continue
            changed = False
            if row.item_type != SIGNAL_ITEM_TYPE:
                row.item_type = SIGNAL_ITEM_TYPE
                changed = True
            fresh_rationale = entry["rationale"] or entry["summary"]
            if fresh_rationale and row.rationale != fresh_rationale:
                row.rationale = fresh_rationale
                changed = True
            if changed:
                row.updated_at = datetime.now(timezone.utc)
                updated.append(_row_payload(row))

        # Anything the current cycle did not emit has aged out into history.
        for identity, row in by_identity.items():
            if identity in current_by_identity or row.dismissed:
                continue
            if row.item_type != SIGNAL_HISTORY_ITEM_TYPE:
                row.item_type = SIGNAL_HISTORY_ITEM_TYPE
                # The retirement moment, so the client can show the most
                # recently retired signals under the Strategic filter.
                row.updated_at = datetime.now(timezone.utc)
                updated.append(_row_payload(row))

        await db.commit()

    if created or updated:
        logger.info(
            "[strategic_signals] signal insights: %d created, %d updated",
            len(created),
            len(updated),
        )
    return {"created": created, "updated": updated}


def excluded_item_types() -> Iterable[str]:
    """Item types no other agent should treat as its own material."""
    return SIGNAL_ITEM_TYPES

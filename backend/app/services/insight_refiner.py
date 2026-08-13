"""Insight refinement operations.

The periodic refinement loop this module was built around is gone: the
synthesizer agent replaced it, and its cycle function had no callers left. What
survives is the operation vocabulary both the synthesizer and the speaker
context enhancer apply against saved insights - answer, enrich, elevate,
adjust, create, dismiss, and merge.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.database import async_session
from app.models import Question

logger = logging.getLogger(__name__)

async def _apply_operations(
    session_id: uuid.UUID,
    ops: list[dict],
    questions: list[Question],
    agent_source: str = "refiner",
    enhanced: bool = False,
) -> list[dict]:
    """Apply refinement operations to the database. Returns list of applied ops with results."""
    async with async_session() as db:
        applied = await _apply_operations_in_db(
            db,
            session_id,
            ops,
            questions,
            agent_source=agent_source,
            enhanced=enhanced,
        )
        await db.commit()
        return applied


async def _apply_operations_in_db(
    db,
    session_id: uuid.UUID,
    ops: list[dict],
    questions: list[Question],
    agent_source: str = "refiner",
    enhanced: bool = False,
) -> list[dict]:
    """Apply operations in the caller's transaction."""
    q_map = {str(q.id): q for q in questions}
    applied = []
    now = datetime.now(timezone.utc)
    handlers = {
        "answer": _apply_answer_operation,
        "enrich": _apply_enrich_operation,
        "elevate": _apply_elevate_operation,
        "adjust": _apply_adjust_operation,
        "create": _apply_create_operation,
        "dismiss": _apply_dismiss_operation,
        "merge": _apply_merge_operation,
    }

    for op in ops:
        if not isinstance(op, dict):
            continue

        op = _without_nulls(op)
        op_type = op.get("op")
        handler = handlers.get(op_type)
        if handler is None or _touches_dismissed_question(op, q_map):
            continue

        try:
            applied.extend(
                await handler(
                    db,
                    session_id,
                    op,
                    q_map,
                    agent_source,
                    enhanced,
                    now,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to apply refinement op {op_type}: {e}")
            continue
    return applied


def _without_nulls(op: dict) -> dict:
    """Drop keys an operation set to an explicit null.

    Hosted models emit every field of the schema and write null where they have
    nothing to say; self-hosted ones simply omit the key. Every handler below
    reads through op.get(key, default), which returns the default for a missing
    key but the null for a present one - so the hosted shape carried None into
    the insert and overrode a not-null column's empty-string default, losing a
    whole synthesizer cycle to an IntegrityError (ALP-171, the hosted-shape edge
    ALP-164's acceptance four flagged).

    Dropping the key makes the two shapes identical at this boundary, which is
    cheaper and safer than teaching twenty call sites to coalesce. No handler
    treats an explicit null as meaningful, so nothing is lost by it.
    """
    return {key: value for key, value in op.items() if value is not None}


def _touches_dismissed_question(op: dict, q_map: dict[str, Question]) -> bool:
    ids = [op.get("id"), op.get("keep_id"), op.get("remove_id")]
    return any(item_id in q_map and q_map[item_id].dismissed for item_id in ids)


def _mark_revised(q: Question, now: datetime, enhanced: bool):
    q.updated_at = now
    q.revision_count = (q.revision_count or 0) + 1
    if enhanced:
        q.enhanced = True


def _append_note(q: Question, note: str):
    if q.enrichment_notes:
        q.enrichment_notes += f"\n{note}"
    else:
        q.enrichment_notes = note


def _reason_note(prefix: str, reason: str) -> str:
    return f"{prefix}: {reason}" if reason else prefix


def _update_payload(op: dict, q: Question, ws_type: str = "insight_updated", **extra) -> dict:
    return {
        **op,
        **extra,
        "applied": True,
        "ws_type": ws_type,
        "ws_data": _question_ws_payload(q),
    }


async def _apply_answer_operation(db, session_id, op, q_map, agent_source, enhanced, now):
    target_id = op.get("id")
    if target_id not in q_map:
        return []
    q = await db.get(Question, uuid.UUID(target_id))
    if not q or q.answered:
        return []

    q.answered = True
    q.answer_summary = op.get("answer_summary", "")
    q.needs_followup = op.get("needs_followup", False)
    q.followup_question = op.get("followup", "")
    _mark_revised(q, now, enhanced)
    applied = [_update_payload(op, q)]

    if q.needs_followup and q.followup_question:
        followup = Question(
            session_id=session_id,
            question=q.followup_question,
            rationale=f"Follow-up to: {q.question}",
            source_context=f"Original answer: {q.answer_summary}",
            needs_followup=True,
            enhanced=enhanced,
            agent_source=agent_source,
        )
        db.add(followup)
        await db.flush()
        applied.append({
            "op": "create",
            "applied": True,
            "ws_type": "question",
            "ws_data": _question_ws_payload(followup, is_followup=True),
        })
    return applied


async def _apply_enrich_operation(db, session_id, op, q_map, agent_source, enhanced, now):
    target_id = op.get("id")
    if target_id not in q_map:
        return []
    q = await db.get(Question, uuid.UUID(target_id))
    if not q:
        return []

    additional = op.get("additional_context", "")
    reason = op.get("reason", "")
    note = f"{additional}"
    if reason:
        note += f" ({reason})"
    _append_note(q, note)
    _mark_revised(q, now, enhanced)
    return [_update_payload(op, q)]


async def _apply_elevate_operation(db, session_id, op, q_map, agent_source, enhanced, now):
    target_id = op.get("id")
    new_type = op.get("new_type", "")
    if target_id not in q_map or new_type not in ("question", "observation", "opportunity", "action_item"):
        return []
    q = await db.get(Question, uuid.UUID(target_id))
    if not q:
        return []

    old_type = q.item_type
    if new_type == old_type:
        # A same-type elevate is not a change. Applying it anyway bumps
        # revision_count, lights the "Refined" badge, and writes "Elevated from
        # observation to observation" into the notes the model reads back next
        # cycle. _apply_adjust_operation already returns empty on a no-op; this
        # follows it (ALP-297).
        return []
    if enhanced:
        _mark_revised(q, now, enhanced)
        _append_note(
            q,
            _reason_note(
                f"Enhancement preserved original type {old_type}; model suggested {new_type}",
                op.get("reason", ""),
            ),
        )
        return [
            _update_payload(
                op,
                q,
                old_type=old_type,
                suggested_type=new_type,
                type_preserved=True,
            )
        ]

    q.item_type = new_type
    q.lens_label = ""  # lens provenance no longer matches after a type change
    _mark_revised(q, now, enhanced)
    _append_note(q, _reason_note(f"Elevated from {old_type} to {new_type}", op.get("reason", "")))
    payload = _update_payload(op, q, ws_type="insight_elevated", old_type=old_type)
    payload["ws_data"] = {**payload["ws_data"], "old_type": old_type}
    return [payload]


async def _apply_adjust_operation(db, session_id, op, q_map, agent_source, enhanced, now):
    target_id = op.get("id")
    if target_id not in q_map:
        return []
    q = await db.get(Question, uuid.UUID(target_id))
    if not q:
        return []

    field_updates = _adjust_field_updates(op)
    old_values = {}
    for field, value in field_updates.items():
        old_value = getattr(q, field, "") or ""
        if value == old_value:
            continue
        old_values[field] = old_value
        setattr(q, field, value)

    if not old_values:
        return []

    _mark_revised(q, now, enhanced)
    _append_note(q, _reason_note("Adjusted", op.get("reason", "")))
    return [_update_payload(op, q, old_values=old_values)]


def _adjust_field_updates(op: dict) -> dict[str, str]:
    fields = {
        "question": ("new_text", "question"),
        "rationale": ("new_rationale", "rationale"),
        "source_context": ("new_source_context", "source_context"),
        "answer_summary": ("new_answer_summary", "answer_summary"),
        "followup_question": ("new_followup_question", "new_followup", "followup_question", "followup"),
        "offering_match": ("new_offering_match", "offering_match"),
    }
    updates: dict[str, str] = {}
    for field, keys in fields.items():
        for key in keys:
            if key not in op:
                continue
            value = op.get(key)
            if isinstance(value, str) and value.strip():
                updates[field] = value.strip()
            break
    return updates


async def _apply_create_operation(db, session_id, op, q_map, agent_source, enhanced, now):
    question_text = op.get("question", "")
    if not question_text:
        return []
    q = Question(
        session_id=session_id,
        item_type=op.get("item_type", "question"),
        question=question_text,
        rationale=op.get("rationale", ""),
        source_context=op.get("source_context", ""),
        enrichment_notes=f"Surfaced by {agent_source}",
        agent_source=agent_source,
        enhanced=enhanced,
    )
    db.add(q)
    await db.flush()
    return [_update_payload(op, q, ws_type="question")]


async def _apply_dismiss_operation(db, session_id, op, q_map, agent_source, enhanced, now):
    target_id = op.get("id")
    if target_id not in q_map:
        return []
    q = await db.get(Question, uuid.UUID(target_id))
    if not q or q.dismissed:
        return []

    q.dismissed = True
    _mark_revised(q, now, enhanced)
    prefix = "Dismissed by enhancement" if enhanced else "Dismissed by refiner"
    _append_note(q, _reason_note(prefix, op.get("reason", "")))
    return [_update_payload(op, q)]


async def _apply_merge_operation(db, session_id, op, q_map, agent_source, enhanced, now):
    keep_id = op.get("keep_id")
    remove_id = op.get("remove_id")
    if keep_id not in q_map or remove_id not in q_map:
        return []
    if keep_id == remove_id:
        # Both ids resolve to the same row, so the merge below would rewrite
        # that insight to merged_text and then dismiss it - deleting what the
        # user was reading, with a note claiming it was merged into something
        # that does not exist. Nothing stops the model emitting this: both
        # fields are free-form uuids and the correct pair are, by definition,
        # two insights that look almost identical (ALP-297).
        logger.warning("[insight_refiner] ignoring self-merge of %s", keep_id)
        return []

    keep_q = await db.get(Question, uuid.UUID(keep_id))
    remove_q = await db.get(Question, uuid.UUID(remove_id))
    if not keep_q or not remove_q:
        return []

    reason = op.get("reason", "")
    keep_q.question = op.get("merged_text", keep_q.question)
    _mark_revised(keep_q, now, enhanced)
    _append_note(keep_q, _reason_note("Merged with another insight", reason))

    remove_q.dismissed = True
    _mark_revised(remove_q, now, enhanced)
    prefix = "Dismissed by enhancement merge" if enhanced else "Dismissed by merge"
    _append_note(remove_q, _reason_note(prefix, reason))

    return [
        _update_payload(op, keep_q),
        {
            "op": "dismiss",
            "id": remove_id,
            "applied": True,
            "ws_type": "insight_updated",
            "ws_data": _question_ws_payload(remove_q),
        },
    ]


def _question_ws_payload(q: Question, is_followup: bool = False) -> dict:
    return {
        "id": str(q.id),
        "item_type": q.item_type,
        "lens_label": q.lens_label or "",
        "question": q.question,
        "rationale": q.rationale,
        "source_context": q.source_context,
        "directive_id": str(q.directive_id) if q.directive_id else None,
        "starred": q.starred,
        "dismissed": q.dismissed,
        "answered": q.answered,
        "answer_summary": q.answer_summary,
        "needs_followup": q.needs_followup,
        "followup_question": q.followup_question,
        "enrichment_notes": q.enrichment_notes or "",
        "revision_count": q.revision_count,
        "updated_at": q.updated_at.isoformat() if q.updated_at else None,
        "created_at": q.created_at.isoformat(),
        "is_followup": is_followup,
        "timestamp": q.created_at.isoformat(),
        "agent_source": q.agent_source,
        "offering_match": q.offering_match or "",
        "vote": q.vote,
        "enhanced": q.enhanced,
    }

"""Opportunity Specialist agent.

Reads opportunities from the session DB and maps them to entries from the
agent's configured knowledge sources (the offerings catalog by default,
or one or more user-created collection/files sources).
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.services.llm import generate_text
from app.database import async_session
from app.models import KnowledgeSource, Question, Session
from app.services.agents.prompts import OPPORTUNITY_SPECIALIST_PROMPT
from app.services.knowledge import get_adapter
from app.services.meeting_context import build_meeting_context_text, format_prompt_layers

logger = logging.getLogger(__name__)


def _build_opportunities_json(questions: list[Question]) -> str:
    """Format unmapped opportunities for the prompt."""
    items = []
    for q in questions:
        items.append({
            "id": str(q.id),
            "opportunity": q.question,
            "rationale": q.rationale,
            "source_context": q.source_context,
        })
    return json.dumps(items, indent=2)


def _parse_mappings(raw: str) -> list | None:
    """Parse the LLM response into a list of mapping dicts (tolerant)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    if not raw or raw == "[]":
        return []

    try:
        mappings = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return None
        try:
            mappings = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None

    if not isinstance(mappings, list):
        return []
    return mappings


async def _fetch_knowledge_context(
    db, knowledge_source_ids: list[uuid.UUID] | None
) -> str:
    """Resolve the configured knowledge sources and merge their contexts.

    Sources that are missing, inactive, or empty are skipped. When no
    configured source yields context, falls back to the offerings catalog.
    """
    sources: list[KnowledgeSource] = []
    for source_id in knowledge_source_ids or []:
        source = await db.get(KnowledgeSource, source_id)
        if source is None or not source.active:
            logger.warning(
                f"[opportunity_specialist] knowledge source {source_id} missing or inactive, skipping"
            )
            continue
        sources.append(source)

    contexts: list[str] = []
    for source in sources:
        adapter = get_adapter(source)
        if adapter is None:
            continue
        context = await adapter.fetch_context(db)
        if not context:
            logger.warning(f"[opportunity_specialist] knowledge source '{source.name}' empty, skipping")
            continue
        contexts.append(f"## Source: {adapter.source_name}\n{context}" if len(sources) > 1 else context)

    if contexts:
        return "\n\n".join(contexts)

    # No usable configured source: legacy fallback to the offerings catalog
    if not sources:
        adapter = get_adapter(None)
        if adapter is not None:
            return await adapter.fetch_context(db)
    return ""


async def run_opportunity_specialist_cycle(
    session_id: uuid.UUID,
    model_override: str | None = None,
    knowledge_source_ids: list[uuid.UUID] | None = None,
) -> list[dict]:
    """Execute one Opportunity Specialist cycle.

    Finds opportunities without offering_match and maps them to entries from
    the configured knowledge sources. Returns list of updated opportunity
    dicts for WS broadcast.
    """
    async with async_session() as db:
        # This agent formatted its template directly for as long as it has
        # existed, so it was the one text agent running with no meeting
        # context at all -- it read every conversation as a sales call
        # (ALP-285). It goes through the shared seam now like the rest.
        session = await db.get(Session, session_id)
        meeting_context_text = build_meeting_context_text(session)
        # Load unmapped opportunities for this session
        result = await db.execute(
            select(Question).where(
                Question.session_id == session_id,
                Question.item_type == "opportunity",
                Question.dismissed.is_(False),
                Question.offering_match == "",
            )
        )
        unmapped = list(result.scalars().all())

        if not unmapped:
            return []

        knowledge_context = await _fetch_knowledge_context(db, knowledge_source_ids)

    if not knowledge_context:
        logger.warning("[opportunity_specialist] knowledge sources empty, skipping cycle")
        return []

    opportunities_json = _build_opportunities_json(unmapped)

    system, prompt = format_prompt_layers(
        OPPORTUNITY_SPECIALIST_PROMPT,
        meeting_context_text,
        knowledge_context=knowledge_context,
        opportunities_json=opportunities_json,
    )

    model_id = settings.REFINEMENT_MODEL if model_override is None else model_override

    try:
        raw = await generate_text(
            model_id,
            prompt,
            system=system,
            session_id=session_id,
            source="opportunity_specialist",
        )
    except Exception as e:
        logger.error(f"[opportunity_specialist] API call failed: {e}")
        return []

    mappings = _parse_mappings(raw)
    if mappings is None:
        logger.warning(f"[opportunity_specialist] parse failed: {raw[:200]}")
        return []
    if not mappings:
        return []

    # Apply mappings to DB
    applied = []
    q_map = {str(q.id): q for q in unmapped}
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue

            target_id = mapping.get("id")
            offering_match = mapping.get("offering_match", "")

            if not target_id or not offering_match or target_id not in q_map:
                continue

            q = await db.get(Question, uuid.UUID(target_id))
            if q and not q.offering_match:
                q.offering_match = offering_match
                q.updated_at = now
                q.revision_count += 1

                match_quality = mapping.get("match_quality", "")
                note = f"Offering mapped ({match_quality})" if match_quality else "Offering mapped"
                if q.enrichment_notes:
                    q.enrichment_notes += f"\n{note}"
                else:
                    q.enrichment_notes = note

                applied.append({
                    "op": "offering_match",
                    "id": target_id,
                    "ws_type": "insight_updated",
                    "ws_data": {
                        "id": str(q.id),
                        "item_type": q.item_type,
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
                        "is_followup": False,
                        "timestamp": q.created_at.isoformat(),
                        "agent_source": q.agent_source,
                        "offering_match": q.offering_match,
                        "enhanced": q.enhanced,
                    },
                })

        await db.commit()

    if applied:
        logger.info(f"[opportunity_specialist] mapped {len(applied)} opportunities to offerings")

    return applied

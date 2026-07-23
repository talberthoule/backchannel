"""Shared synthesis storage plus the post-call dual-lens briefing pipeline."""

from __future__ import annotations

import json
import logging
import uuid
from hashlib import blake2b
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models import AgentConfig, Directive, InsightCluster, Question, Session, SessionAgentOverride, SessionSynthesis, Speaker, TranscriptEntry
from app.services.agents.prompts import BRIEF_ARBITER_PROMPT, BRIEF_DISCOVERY_LENS_PROMPT, BRIEF_MEETING_LENS_PROMPT
from app.services.agents.speaker_context import format_speakers_list, format_transcript_segment
from app.services.llm import generate_json, provider_for
from app.services.meeting_context import build_meeting_context_text, format_prompt_with_meeting_context
from app.services.provider_errors import PROVIDER_ERROR_TYPES, provider_error_message
from app.services.session_manager import get_document_summaries

logger = logging.getLogger(__name__)

BRIEF_MEETING_LENS_SLUG = "brief_meeting_lens"
BRIEF_DISCOVERY_LENS_SLUG = "brief_discovery_lens"
BRIEF_ARBITER_SLUG = "brief_arbiter"
BRIEF_AGENT_SLUGS = {BRIEF_MEETING_LENS_SLUG, BRIEF_DISCOVERY_LENS_SLUG, BRIEF_ARBITER_SLUG}
SYNTHESIS_MODES = {"live", "post_call"}
SynthesisMode = Literal["live", "post_call"]


class EvidenceRef(BaseModel):
    id: str = ""
    transcript_id: str = ""
    insight_id: str = ""
    source_id: str = ""
    type: str = ""
    quote: str = ""
    note: str = ""


class BriefItem(BaseModel):
    title: str = ""
    summary: str = ""
    rationale: str = ""
    owner: str = ""
    status: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class BriefLensOutput(BaseModel):
    top_outcomes: list[BriefItem] = Field(default_factory=list)
    client_objectives: list[BriefItem] = Field(default_factory=list)
    top_opportunities: list[BriefItem] = Field(default_factory=list)
    risks_blockers: list[BriefItem] = Field(default_factory=list)
    action_plan: list[BriefItem] = Field(default_factory=list)
    unresolved_discovery_questions: list[BriefItem] = Field(default_factory=list)
    strategic_signals: list[BriefItem] = Field(default_factory=list)
    notes: str = ""


class BriefClusterOutput(BaseModel):
    title: str = ""
    summary: str = ""
    priority: int = 0
    confidence: str = "medium"
    related_question_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class BriefArbiterOutput(BriefLensOutput):
    insight_clusters: list[BriefClusterOutput] = Field(default_factory=list)
    arbiter_notes: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class SynthesisContext(BaseModel):
    meeting_context_text: str
    transcript_text: str
    directives_text: str
    document_summaries: str
    speakers_text: str
    insights_text: str


def agent_config_enabled(agent_configs: dict[str, Any], slug: str) -> bool:
    cfg = agent_configs.get(slug)
    return bool(cfg and cfg.enabled)


async def load_agent_configs(session_id: uuid.UUID | None = None) -> dict[str, Any]:
    async with async_session() as db:
        result = await db.execute(select(AgentConfig).order_by(AgentConfig.display_order))
        configs = {agent.slug: _agent_config_snapshot(agent) for agent in result.scalars().all()}

        if session_id:
            override_result = await db.execute(
                select(SessionAgentOverride).where(SessionAgentOverride.session_id == session_id)
            )
            overrides = {override.agent_slug: override.enabled for override in override_result.scalars().all()}
            for slug, enabled in overrides.items():
                if slug in configs:
                    configs[slug].enabled = enabled

        return configs


def _agent_config_snapshot(agent: AgentConfig):
    return SimpleNamespace(
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        agent_type=agent.agent_type,
        model_id=agent.model_id,
        prompt=agent.prompt,
        enabled=agent.enabled,
        sub_types=agent.sub_types,
        lenses=getattr(agent, "lenses", ""),
        interval_seconds=agent.interval_seconds,
        display_order=agent.display_order,
    )


async def get_session_synthesis(session_id: uuid.UUID, mode: str = "post_call") -> SessionSynthesis | None:
    _validate_synthesis_mode(mode)
    async with async_session() as db:
        result = await db.execute(
            select(SessionSynthesis)
            .where(SessionSynthesis.session_id == session_id, SessionSynthesis.mode == mode)
            .options(selectinload(SessionSynthesis.clusters))
        )
        return result.scalar_one_or_none()


async def run_session_synthesis(
    session_id: uuid.UUID,
    mode: SynthesisMode = "post_call",
    agent_configs: dict[str, Any] | None = None,
    transcript_window: str | None = None,
    directives: list[str] | None = None,
    doc_summaries: str | None = None,
    speakers: list[dict] | None = None,
    active_questions: list[dict] | None = None,
) -> SessionSynthesis | None:
    """Run the dual-lens briefing pipeline and persist the settled synthesis."""
    _validate_synthesis_mode(mode)
    if mode != "post_call":
        raise ValueError("Live synthesis is owned by the strategic_signals agent")
    from app.services.privacy import LocalOnlyModeError, is_local_only

    if await is_local_only():
        raise LocalOnlyModeError("call briefing synthesis")
    agent_configs = agent_configs or await load_agent_configs(session_id)
    if not agent_config_enabled(agent_configs, BRIEF_ARBITER_SLUG):
        logger.info("Briefing synthesis skipped: arbiter agent is disabled or missing")
        return None

    context = await _build_context(
        session_id,
        mode=mode,
        transcript_window=transcript_window,
        directives=directives,
        doc_summaries=doc_summaries,
        speakers=speakers,
        active_questions=active_questions,
    )
    if not context.transcript_text or context.transcript_text == "(No transcript yet)":
        return None

    meeting_cfg = agent_configs.get(BRIEF_MEETING_LENS_SLUG)
    discovery_cfg = agent_configs.get(BRIEF_DISCOVERY_LENS_SLUG)
    arbiter_cfg = agent_configs[BRIEF_ARBITER_SLUG]

    meeting_output = None
    discovery_output = None
    errors: list[str] = []

    async def run_lens(slug: str, cfg: AgentConfig | None, default_prompt: str) -> BriefLensOutput | None:
        if not cfg or not cfg.enabled:
            return None
        prompt = format_prompt_with_meeting_context(
            cfg.prompt or default_prompt,
            context.meeting_context_text,
            mode=mode,
            speakers_text=context.speakers_text,
            directives_text=context.directives_text,
            document_summaries=context.document_summaries,
            insights_text=context.insights_text,
            transcript_text=context.transcript_text,
        )
        try:
            return await generate_json(
                cfg.model_id,
                prompt,
                BriefLensOutput,
                schema_hint=_response_contract(BriefLensOutput),
                session_id=session_id,
                source=slug,
            )
        except Exception as exc:
            logger.error("[%s] briefing lens failed: %s", slug, exc)
            errors.append(f"{slug}: {_failure_text(cfg.model_id, exc)}")
            return None

    import asyncio

    meeting_output, discovery_output = await asyncio.gather(
        run_lens(BRIEF_MEETING_LENS_SLUG, meeting_cfg, BRIEF_MEETING_LENS_PROMPT),
        run_lens(BRIEF_DISCOVERY_LENS_SLUG, discovery_cfg, BRIEF_DISCOVERY_LENS_PROMPT),
    )

    if meeting_output is None and discovery_output is None:
        return await _persist_error_synthesis(
            session_id,
            mode,
            "; ".join(errors) or "Both briefing lenses failed or are disabled.",
            {
                BRIEF_MEETING_LENS_SLUG: getattr(meeting_cfg, "model_id", ""),
                BRIEF_DISCOVERY_LENS_SLUG: getattr(discovery_cfg, "model_id", ""),
                BRIEF_ARBITER_SLUG: arbiter_cfg.model_id,
            },
        )

    arbiter_prompt = format_prompt_with_meeting_context(
        arbiter_cfg.prompt or BRIEF_ARBITER_PROMPT,
        context.meeting_context_text,
        mode=mode,
        meeting_lens_json=_model_json(meeting_output),
        discovery_lens_json=_model_json(discovery_output),
    )
    try:
        arbiter_output = await generate_json(
            arbiter_cfg.model_id,
            arbiter_prompt,
            BriefArbiterOutput,
            schema_hint=_response_contract(BriefArbiterOutput),
            session_id=session_id,
            source=BRIEF_ARBITER_SLUG,
        )
    except Exception as exc:
        logger.error("[brief_arbiter] failed: %s", exc)
        errors.append(f"{BRIEF_ARBITER_SLUG}: {_failure_text(arbiter_cfg.model_id, exc)}")
        return await _persist_error_synthesis(
            session_id,
            mode,
            "; ".join(errors) or str(exc),
            {
                BRIEF_MEETING_LENS_SLUG: getattr(meeting_cfg, "model_id", ""),
                BRIEF_DISCOVERY_LENS_SLUG: getattr(discovery_cfg, "model_id", ""),
                BRIEF_ARBITER_SLUG: arbiter_cfg.model_id,
            },
            meeting_output=meeting_output,
            discovery_output=discovery_output,
        )

    status = "partial" if errors or meeting_output is None or discovery_output is None else "completed"
    return await _persist_synthesis(
        session_id=session_id,
        mode=mode,
        status=status,
        meeting_output=meeting_output,
        discovery_output=discovery_output,
        arbiter_output=arbiter_output,
        model_ids={
            BRIEF_MEETING_LENS_SLUG: getattr(meeting_cfg, "model_id", ""),
            BRIEF_DISCOVERY_LENS_SLUG: getattr(discovery_cfg, "model_id", ""),
            BRIEF_ARBITER_SLUG: arbiter_cfg.model_id,
        },
        error_message="; ".join(errors),
    )


async def _build_context(
    session_id: uuid.UUID,
    mode: str,
    transcript_window: str | None,
    directives: list[str] | None,
    doc_summaries: str | None,
    speakers: list[dict] | None,
    active_questions: list[dict] | None,
) -> SynthesisContext:
    async with async_session() as db:
        session = await db.get(Session, session_id)
        meeting_context_text = build_meeting_context_text(session)

        if directives is None:
            result = await db.execute(
                select(Directive.text).where(Directive.session_id == session_id, Directive.active.is_(True))
            )
            directives = list(result.scalars().all())

        if doc_summaries is None:
            doc_summaries = await get_document_summaries(session_id, db)

        if speakers is None:
            result = await db.execute(
                select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
            )
            speakers = [_speaker_dict(s) for s in result.scalars().all()]

        if active_questions is None:
            result = await db.execute(
                select(Question)
                .where(Question.session_id == session_id, Question.dismissed.is_(False))
                .order_by(Question.created_at)
            )
            questions = list(result.scalars().all())
            active_questions = [_question_dict(q) for q in questions]

        if transcript_window is None:
            result = await db.execute(
                select(TranscriptEntry)
                .where(TranscriptEntry.session_id == session_id)
                .options(selectinload(TranscriptEntry.speaker))
                .order_by(TranscriptEntry.sequence)
            )
            transcript_entries = list(result.scalars().all())
            transcript_text = _format_transcript_entries(transcript_entries)
        else:
            transcript_text = transcript_window

    return SynthesisContext(
        meeting_context_text=meeting_context_text,
        transcript_text=transcript_text,
        directives_text="\n".join(f"- {d}" for d in directives) if directives else "(No directives set)",
        document_summaries=doc_summaries or "(No documents uploaded)",
        speakers_text=format_speakers_list(speakers or []),
        insights_text=_format_insights(active_questions or []),
    )


def _speaker_dict(speaker: Speaker) -> dict:
    return {
        "id": str(speaker.id),
        "name": speaker.name,
        "role": speaker.role,
        "speaker_type": speaker.speaker_type,
        "display_name": speaker.display_name,
        "display_name_enabled": speaker.display_name_enabled,
    }


def _question_dict(question: Question) -> dict:
    return {
        "id": str(question.id),
        "item_type": question.item_type,
        "question": question.question,
        "rationale": question.rationale,
        "source_context": question.source_context,
        "answered": question.answered,
        "needs_followup": question.needs_followup,
        "offering_match": question.offering_match,
        "vote": question.vote,
    }


def _format_transcript_entries(entries: list[TranscriptEntry]) -> str:
    if not entries:
        return "(No transcript yet)"
    lines = []
    for entry in entries:
        speaker = _speaker_dict(entry.speaker) if entry.speaker else None
        prefix = f"transcript_id={entry.id}; sequence={entry.sequence}"
        segment = format_transcript_segment(
            entry.text,
            speaker.get("name") if speaker else "Unknown",
            speaker_id=str(entry.speaker_id) if entry.speaker_id else None,
            speaker_type=speaker.get("speaker_type") if speaker else None,
        )
        lines.append(f"[{prefix}] {segment}")
    return "\n".join(lines)


def _format_insights(items: list[dict]) -> str:
    if not items:
        return "(No saved insights yet)"
    lines = []
    for item in items:
        item_id = item.get("id", "")
        item_type = item.get("item_type", "question")
        text = item.get("question") or item.get("text") or ""
        rationale = item.get("rationale") or ""
        lines.append(f"- insight_id={item_id}; type={item_type}: {text} ({rationale})")
    return "\n".join(lines)


def _failure_text(model_id: str, exc: Exception) -> str:
    """Actionable one-line failure text for briefing status strings."""
    if isinstance(exc, PROVIDER_ERROR_TYPES):
        return provider_error_message(provider_for(model_id), exc)
    return str(exc)


def _response_contract(response_schema: type[BaseModel]) -> str:
    item = {
        "title": "short label",
        "summary": "one or two concise sentences",
        "rationale": "why this matters",
        "owner": "person or team if known, else empty string",
        "status": "open|blocked|done|unknown or empty string",
        "evidence_refs": [
            {
                "id": "transcript_id or insight_id if available",
                "transcript_id": "transcript id if available",
                "insight_id": "insight id if available",
                "source_id": "other source id if available",
                "type": "transcript|insight|document|directive or empty string",
                "quote": "short supporting quote if available",
                "note": "brief evidence note if useful",
            }
        ],
    }
    contract: dict[str, Any] = {
        "top_outcomes": [item],
        "client_objectives": [item],
        "top_opportunities": [item],
        "risks_blockers": [item],
        "action_plan": [item],
        "unresolved_discovery_questions": [item],
        "strategic_signals": [item],
        "notes": "brief lens notes or empty string",
    }
    if issubclass(response_schema, BriefArbiterOutput):
        contract["insight_clusters"] = [
            {
                "title": "theme name",
                "summary": "how related findings connect",
                "priority": 1,
                "confidence": "high|medium|low",
                "related_question_ids": ["insight uuid if available"],
                "evidence_refs": item["evidence_refs"],
            }
        ]
        contract["arbiter_notes"] = "how the lenses agreed, differed, and how the settled view was chosen"
        contract["evidence_refs"] = item["evidence_refs"]
    return (
        "Return exactly one valid JSON object. Use these keys and value shapes; use empty arrays or empty strings "
        "when there is no supported evidence. Do not include markdown or commentary.\n"
        f"{json.dumps(contract, indent=2)}"
    )


async def _persist_error_synthesis(
    session_id: uuid.UUID,
    mode: str,
    error_message: str,
    model_ids: dict[str, str],
    meeting_output: BriefLensOutput | None = None,
    discovery_output: BriefLensOutput | None = None,
) -> SessionSynthesis:
    return await _persist_synthesis(
        session_id=session_id,
        mode=mode,
        status="error",
        meeting_output=meeting_output,
        discovery_output=discovery_output,
        arbiter_output=BriefArbiterOutput(arbiter_notes="Briefing synthesis failed."),
        model_ids=model_ids,
        error_message=error_message,
    )


async def _persist_synthesis(
    session_id: uuid.UUID,
    mode: str,
    status: str,
    meeting_output: BriefLensOutput | None,
    discovery_output: BriefLensOutput | None,
    arbiter_output: BriefArbiterOutput,
    model_ids: dict[str, str],
    error_message: str = "",
) -> SessionSynthesis:
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        await _lock_synthesis_scope(db, session_id, mode)
        result = await db.execute(
            select(SessionSynthesis)
            .where(SessionSynthesis.session_id == session_id, SessionSynthesis.mode == mode)
            .with_for_update()
        )
        synthesis = result.scalar_one_or_none()
        if synthesis is None:
            synthesis = SessionSynthesis(session_id=session_id, mode=mode, created_at=now)
            db.add(synthesis)

        synthesis.status = status
        synthesis.top_outcomes = _items_json(arbiter_output.top_outcomes)
        synthesis.client_objectives = _items_json(arbiter_output.client_objectives)
        synthesis.top_opportunities = _items_json(arbiter_output.top_opportunities)
        synthesis.risks_blockers = _items_json(arbiter_output.risks_blockers)
        synthesis.action_plan = _items_json(arbiter_output.action_plan)
        synthesis.unresolved_discovery_questions = _items_json(arbiter_output.unresolved_discovery_questions)
        synthesis.strategic_signals = _items_json(arbiter_output.strategic_signals)
        synthesis.evidence_refs = _evidence_refs_json(arbiter_output.evidence_refs)
        synthesis.lens_meeting = _model_dict(meeting_output)
        synthesis.lens_discovery = _model_dict(discovery_output)
        synthesis.arbiter_notes = arbiter_output.arbiter_notes
        synthesis.model_ids = model_ids
        synthesis.error_message = error_message
        synthesis.updated_at = now

        await db.flush()
        await db.execute(delete(InsightCluster).where(InsightCluster.synthesis_id == synthesis.id))
        for index, cluster in enumerate(arbiter_output.insight_clusters):
            db.add(
                InsightCluster(
                    synthesis_id=synthesis.id,
                    session_id=session_id,
                    title=cluster.title or f"Theme {index + 1}",
                    summary=cluster.summary,
                    priority=cluster.priority or index + 1,
                    confidence=cluster.confidence or "medium",
                    related_question_ids=cluster.related_question_ids,
                    evidence_refs=_evidence_refs_json(cluster.evidence_refs),
                )
            )

        await db.commit()

        result = await db.execute(
            select(SessionSynthesis)
            .where(SessionSynthesis.id == synthesis.id)
            .options(selectinload(SessionSynthesis.clusters))
        )
        return result.scalar_one()


def _items_json(items: list[BriefItem]) -> list[dict]:
    return [item.model_dump() for item in items]


def _evidence_refs_json(items: list[EvidenceRef]) -> list[dict]:
    return [item.model_dump() for item in items]


def _model_dict(model: BaseModel | None) -> dict:
    return model.model_dump() if model else {}


def _model_json(model: BaseModel | None) -> str:
    return json.dumps(_model_dict(model), indent=2)


def _validate_synthesis_mode(mode: str):
    if mode not in SYNTHESIS_MODES:
        raise ValueError(f"Unsupported synthesis mode: {mode}")


async def _lock_synthesis_scope(db, session_id: uuid.UUID, mode: str):
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    key = _synthesis_lock_key(session_id, mode)
    await db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": key})


def _synthesis_lock_key(session_id: uuid.UUID, mode: str) -> int:
    digest = blake2b(f"session_synthesis:{session_id}:{mode}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)

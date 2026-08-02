import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.secrets import data_dir
from app.models import AgentConfig, CallSegment, Session, SessionAgentOverride, TokenUsage
from app.schemas import (
    CallSegmentOut,
    EnhanceInsightsOut,
    SessionAgentOut,
    SessionAgentOverrideSet,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    TokenUsageSummaryOut,
)
from app.services.agents.orchestrator import get_live_orchestrator
from app.services.briefing_synthesis import agent_model_id
from app.services.llm import LLMModelNotSelected
from app.services.meeting_context import normalize_meeting_type
from app.services.speaker_revalidation import (
    get_latest_revalidation_run,
    get_revalidation_run,
    run_revalidation,
    start_or_resume_revalidation,
    summarize_run,
)
from app.services.token_usage import summarize_usage

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(body: SessionCreate, db: AsyncSession = Depends(get_db)):
    session = Session(
        name=body.name,
        notes=body.notes,
        meeting_type=normalize_meeting_type(body.meeting_type),
        meeting_context=body.meeting_context,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).order_by(Session.created_at.desc()))
    return result.scalars().all()


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(session_id: uuid.UUID, body: SessionUpdate, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if body.name is not None:
        session.name = body.name
    if body.state is not None:
        if body.state == "active" and session.state == "pre_call":
            session.started_at = datetime.now(timezone.utc)
        elif body.state == "active" and session.state == "completed":
            # Resume a completed session
            session.ended_at = None
        elif body.state == "completed" and session.state == "active":
            session.ended_at = datetime.now(timezone.utc)
        session.state = body.state
    if body.notes is not None:
        session.notes = body.notes
    if body.meeting_type is not None:
        session.meeting_type = normalize_meeting_type(body.meeting_type)
    if body.meeting_context is not None:
        session.meeting_context = body.meeting_context
    if body.group_id is not None:
        session.group_id = body.group_id
    await db.commit()
    await db.refresh(session)

    # Push mid-call context edits into the running agents, if this session is live.
    if body.meeting_type is not None or body.meeting_context is not None:
        orchestrator = get_live_orchestrator(session_id)
        if orchestrator:
            orchestrator.update_meeting_context(
                meeting_type=body.meeting_type,
                meeting_context=body.meeting_context,
            )
    return session


@router.get("/{session_id}/segments", response_model=list[CallSegmentOut])
async def list_segments(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CallSegment)
        .where(CallSegment.session_id == session_id)
        .order_by(CallSegment.segment_number)
    )
    return result.scalars().all()


@router.get("/{session_id}/token-usage", response_model=TokenUsageSummaryOut)
async def get_token_usage(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if not await db.get(Session, session_id):
        raise HTTPException(404, "Session not found")
    result = await db.execute(select(TokenUsage).where(TokenUsage.session_id == session_id))
    return summarize_usage(result.scalars().all())


@router.get("/{session_id}/segments/{segment_number}/audio")
async def get_segment_audio(session_id: uuid.UUID, segment_number: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CallSegment).where(
            CallSegment.session_id == session_id,
            CallSegment.segment_number == segment_number,
        )
    )
    segment = result.scalar_one_or_none()
    if not segment or not segment.audio_path:
        raise HTTPException(404, "No stored audio for this segment")
    path = data_dir() / segment.audio_path
    if not path.exists():
        raise HTTPException(404, "Stored audio file is missing")
    return FileResponse(path, media_type="audio/wav")


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await db.delete(session)
    await db.commit()


@router.post("/{session_id}/enhance-insights", response_model=EnhanceInsightsOut)
async def enhance_insights_after_speaker_changes(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.state != "completed":
        raise HTTPException(400, "Insight enhancement is available after the session is completed")
    if not session.speaker_context_dirty:
        return {
            "status": "unchanged",
            "speaker_context_dirty": False,
            "speaker_context_enhanced_at": session.speaker_context_enhanced_at,
            "briefing_updated": False,
            "briefing_status": None,
            "error": None,
        }
    if not await agent_model_id("synthesizer"):
        raise LLMModelNotSelected("Synthesizer")
    run, should_start = await start_or_resume_revalidation(session_id, db)
    if should_start:
        background_tasks.add_task(run_revalidation, run.id)
    return summarize_run(run, session)


@router.get(
    "/{session_id}/enhance-insights/latest",
    response_model=EnhanceInsightsOut | None,
)
async def get_latest_enhance_insights_status(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    run = await get_latest_revalidation_run(session_id, db)
    return summarize_run(run, session) if run else None


@router.get(
    "/{session_id}/enhance-insights/{run_id}",
    response_model=EnhanceInsightsOut,
)
async def get_enhance_insights_status(
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(Session, session_id)
    run = await get_revalidation_run(run_id, db)
    if not session or not run or run.session_id != session_id:
        raise HTTPException(404, "Speaker revalidation run not found")
    return summarize_run(run, session)


# --- Per-session agent overrides ---

@router.get("/{session_id}/agents", response_model=list[SessionAgentOut])
async def list_session_agents(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get effective agent list for this session (global defaults merged with overrides)."""
    agents_result = await db.execute(
        select(AgentConfig).order_by(AgentConfig.display_order)
    )
    agents = agents_result.scalars().all()

    overrides_result = await db.execute(
        select(SessionAgentOverride).where(SessionAgentOverride.session_id == session_id)
    )
    overrides = {o.agent_slug: o.enabled for o in overrides_result.scalars().all()}

    result = []
    for a in agents:
        is_override = a.slug in overrides
        enabled = overrides[a.slug] if is_override else a.enabled
        result.append(SessionAgentOut(
            slug=a.slug,
            name=a.name,
            description=a.description,
            agent_type=a.agent_type,
            enabled=enabled,
            is_override=is_override,
        ))
    return result


@router.put("/{session_id}/agents", response_model=list[SessionAgentOut])
async def set_session_agents(
    session_id: uuid.UUID,
    overrides: list[SessionAgentOverrideSet],
    db: AsyncSession = Depends(get_db),
):
    """Set per-session agent overrides. Replaces all existing overrides."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # Delete existing overrides
    existing = await db.execute(
        select(SessionAgentOverride).where(SessionAgentOverride.session_id == session_id)
    )
    for o in existing.scalars().all():
        await db.delete(o)

    # Insert new overrides
    for ov in overrides:
        db.add(SessionAgentOverride(
            session_id=session_id,
            agent_slug=ov.agent_slug,
            enabled=ov.enabled,
        ))

    await db.commit()

    # Return the effective list
    return await list_session_agents(session_id, db)

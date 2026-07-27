import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Session
from app.schemas import SessionSynthesisOut
from app.services.agents.strategic_signals import run_strategic_signals_cycle
from app.services.briefing_synthesis import get_session_synthesis, run_session_synthesis

router = APIRouter(prefix="/api/sessions/{session_id}/synthesis", tags=["synthesis"])


@router.get("", response_model=SessionSynthesisOut | None)
async def get_synthesis(
    session_id: uuid.UUID,
    mode: Literal["live", "post_call"] = "post_call",
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return await get_session_synthesis(session_id, mode=mode)


@router.post(
    "/refresh",
    response_model=SessionSynthesisOut,
)
async def refresh_synthesis(
    session_id: uuid.UUID,
    mode: Literal["live", "post_call"] = "post_call",
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    synthesis = (
        await run_strategic_signals_cycle(session_id)
        if mode == "live"
        else await run_session_synthesis(session_id, mode="post_call")
    )
    if not synthesis:
        raise HTTPException(400, "Briefing synthesis is disabled or no transcript is available")
    return synthesis

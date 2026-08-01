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
    include_history: bool = False,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    synthesis = await get_session_synthesis(session_id, mode=mode)
    return _synthesis_response(synthesis, include_history=include_history)


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
    return _synthesis_response(synthesis)


def _synthesis_response(
    synthesis,
    *,
    include_history: bool = False,
) -> SessionSynthesisOut | None:
    if synthesis is None:
        return None
    history = synthesis.signal_history or []
    response = SessionSynthesisOut.model_validate(synthesis)
    response.signal_history_count = len(history)
    response.signal_history = history if include_history else []
    return response

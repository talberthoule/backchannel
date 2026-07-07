import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Speaker
from app.schemas import SpeakerCreate, SpeakerMergeOut, SpeakerMergeRequest, SpeakerOut, SpeakerUpdate
from app.services.speaker_context_enhancer import (
    mark_speaker_context_dirty_if_completed,
    speaker_update_changes_enhancement_context,
)
from app.services.speaker_merge import SpeakerMergeError, merge_speakers

router = APIRouter(prefix="/api/sessions/{session_id}/speakers", tags=["speakers"])


@router.post("", response_model=SpeakerOut, status_code=201)
async def create_speaker(session_id: uuid.UUID, body: SpeakerCreate, db: AsyncSession = Depends(get_db)):
    speaker = Speaker(
        session_id=session_id,
        name=body.name,
        role=body.role,
        color=body.color,
        is_user=body.is_user,
        speaker_type="team" if body.is_user else body.speaker_type,
    )
    db.add(speaker)
    await db.commit()
    await db.refresh(speaker)
    return speaker


@router.get("", response_model=list[SpeakerOut])
async def list_speakers(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Speaker).where(Speaker.session_id == session_id).order_by(Speaker.created_at)
    )
    return result.scalars().all()


@router.patch("/{speaker_id}", response_model=SpeakerOut)
async def update_speaker(
    session_id: uuid.UUID,
    speaker_id: uuid.UUID,
    body: SpeakerUpdate,
    db: AsyncSession = Depends(get_db),
):
    speaker = await db.get(Speaker, speaker_id)
    if not speaker or speaker.session_id != session_id:
        raise HTTPException(status_code=404, detail="Speaker not found")
    updates = body.model_dump(exclude_unset=True)
    if updates.get("is_user") is True:
        updates["speaker_type"] = "team"
    context_changed = speaker_update_changes_enhancement_context(speaker, updates)
    for field, value in updates.items():
        setattr(speaker, field, value)
    if context_changed:
        await mark_speaker_context_dirty_if_completed(db, session_id)
    await db.commit()
    await db.refresh(speaker)
    return speaker


@router.post("/{speaker_id}/merge", response_model=SpeakerMergeOut)
async def merge_speaker(
    session_id: uuid.UUID,
    speaker_id: uuid.UUID,
    body: SpeakerMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await merge_speakers(db, session_id, speaker_id, body.target_speaker_id)
        if await mark_speaker_context_dirty_if_completed(db, session_id):
            await db.commit()
        return result
    except SpeakerMergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{speaker_id}", status_code=204)
async def delete_speaker(
    session_id: uuid.UUID,
    speaker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    speaker = await db.get(Speaker, speaker_id)
    if not speaker or speaker.session_id != session_id:
        raise HTTPException(status_code=404, detail="Speaker not found")
    await mark_speaker_context_dirty_if_completed(db, session_id)
    await db.delete(speaker)
    await db.commit()

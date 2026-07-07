"""Session group CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Session, SessionGroup
from app.schemas import SessionGroupCreate, SessionGroupOut, SessionGroupUpdate

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.get("", response_model=list[SessionGroupOut])
async def list_groups(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SessionGroup).order_by(SessionGroup.display_order, SessionGroup.name)
    )
    return result.scalars().all()


@router.post("", response_model=SessionGroupOut, status_code=201)
async def create_group(body: SessionGroupCreate, db: AsyncSession = Depends(get_db)):
    group = SessionGroup(name=body.name)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


@router.patch("/{group_id}", response_model=SessionGroupOut)
async def update_group(
    group_id: uuid.UUID, body: SessionGroupUpdate, db: AsyncSession = Depends(get_db)
):
    group = await db.get(SessionGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.commit()
    await db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    group = await db.get(SessionGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    # Ungroup sessions (don't delete them)
    await db.execute(
        update(Session).where(Session.group_id == group_id).values(group_id=None)
    )
    await db.delete(group)
    await db.commit()

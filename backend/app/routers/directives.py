import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Directive
from app.schemas import DirectiveCreate, DirectiveOut, DirectiveUpdate
from app.services.pii import shield

router = APIRouter(prefix="/api/sessions/{session_id}/directives", tags=["directives"])


@router.post("", response_model=DirectiveOut, status_code=201)
async def create_directive(session_id: uuid.UUID, body: DirectiveCreate, db: AsyncSession = Depends(get_db)):
    directive = Directive(session_id=session_id, text=await shield.protect_text(db, session_id, body.text))
    db.add(directive)
    await db.commit()
    await db.refresh(directive)
    return directive


@router.get("", response_model=list[DirectiveOut])
async def list_directives(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Directive).where(Directive.session_id == session_id).order_by(Directive.created_at)
    )
    return result.scalars().all()


@router.patch("/{directive_id}", response_model=DirectiveOut)
async def update_directive(
    session_id: uuid.UUID, directive_id: uuid.UUID, body: DirectiveUpdate, db: AsyncSession = Depends(get_db)
):
    directive = await db.get(Directive, directive_id)
    if not directive or directive.session_id != session_id:
        raise HTTPException(404, "Directive not found")
    if body.text is not None:
        directive.text = await shield.protect_text(db, session_id, body.text)
    if body.active is not None:
        directive.active = body.active
    await db.commit()
    await db.refresh(directive)
    return directive


@router.delete("/{directive_id}", status_code=204)
async def delete_directive(session_id: uuid.UUID, directive_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    directive = await db.get(Directive, directive_id)
    if not directive or directive.session_id != session_id:
        raise HTTPException(404, "Directive not found")
    await db.delete(directive)
    await db.commit()

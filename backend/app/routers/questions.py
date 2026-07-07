import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Question
from app.schemas import QuestionOut, QuestionUpdate

router = APIRouter(prefix="/api/sessions/{session_id}/questions", tags=["questions"])


@router.get("", response_model=list[QuestionOut])
async def list_questions(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Question).where(Question.session_id == session_id).order_by(Question.created_at.desc())
    )
    return result.scalars().all()


@router.patch("/{question_id}", response_model=QuestionOut)
async def update_question(
    session_id: uuid.UUID, question_id: uuid.UUID, body: QuestionUpdate, db: AsyncSession = Depends(get_db)
):
    question = await db.get(Question, question_id)
    if not question or question.session_id != session_id:
        raise HTTPException(404, "Question not found")
    if body.starred is not None:
        question.starred = body.starred
    if body.dismissed is not None:
        question.dismissed = body.dismissed
    if body.vote is not None:
        question.vote = body.vote
    await db.commit()
    await db.refresh(question)
    return question

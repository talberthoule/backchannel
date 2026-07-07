import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document
from app.schemas import DocumentOut
from app.services.gemini_files import upload_and_summarize

router = APIRouter(prefix="/api/sessions/{session_id}/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(session_id: uuid.UUID, file: UploadFile, db: AsyncSession = Depends(get_db)):
    content = await file.read()
    gemini_uri = await upload_and_summarize(content, file.filename, file.content_type)

    doc = Document(
        session_id=session_id,
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        gemini_file_uri=gemini_uri,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("", response_model=list[DocumentOut])
async def list_documents(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document).where(Document.session_id == session_id).order_by(Document.uploaded_at)
    )
    return result.scalars().all()


@router.delete("/{document_id}", status_code=204)
async def delete_document(session_id: uuid.UUID, document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, document_id)
    if not doc or doc.session_id != session_id:
        raise HTTPException(404, "Document not found")
    await db.delete(doc)
    await db.commit()

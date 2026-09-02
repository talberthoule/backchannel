import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document
from app.schemas import DocumentOut
from app.services.pii import shield
from app.services.file_parsing import parse_docx, parse_markdown, parse_text
from app.services.gemini_files import upload_and_summarize
from app.services.privacy import is_local_only

router = APIRouter(prefix="/api/sessions/{session_id}/documents", tags=["documents"])

# Bound for the Privacy First local excerpt stored as the document summary.
LOCAL_EXTRACT_CHARS = 4000

_LOCAL_EXTRACT_EXTS = {".txt", ".md", ".markdown", ".docx"}


def local_extract_summary(content: bytes, filename: str, shielded: bool = False) -> str:
    """Bounded plain-text excerpt for Privacy First uploads; no cloud calls.

    ponytail: excerpt, not a summary - compressing through an admitted local
    text model is the upgrade path if excerpts prove too coarse (ALP-181).
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in _LOCAL_EXTRACT_EXTS:
        mode = "The PII Shield is on" if shielded else "Privacy First is on"
        remedy = "turn the PII Shield off" if shielded else "turn Privacy First off"
        raise HTTPException(
            400,
            f"{mode}, so documents are read on this machine instead "
            "of being uploaded. Only .txt, .md, and .docx files can be read "
            f"locally; {remedy} to attach other formats.",
        )
    if ext == ".docx":
        segments = parse_docx(content)
    elif ext == ".txt":
        segments = parse_text(content.decode("utf-8", errors="replace"))
    else:
        segments = parse_markdown(content.decode("utf-8", errors="replace"))

    excerpt = ""
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        if excerpt and len(excerpt) + len(segment) + 2 > LOCAL_EXTRACT_CHARS:
            break
        excerpt = f"{excerpt}\n\n{segment}" if excerpt else segment
    return excerpt[:LOCAL_EXTRACT_CHARS]


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(session_id: uuid.UUID, file: UploadFile, db: AsyncSession = Depends(get_db)):
    content = await file.read()
    shielded = (await shield.get_settings(db)).enabled
    if await is_local_only() or shielded:
        # With the PII Shield on, the file itself never leaves the machine:
        # its text is read here and protected before it is stored or shown
        # to any model.
        doc = Document(
            session_id=session_id,
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            gemini_file_uri="",
            summary=await shield.protect_text(
                db, session_id, local_extract_summary(content, file.filename, shielded=shielded)
            ),
            summary_source="local_extract",
        )
    else:
        doc = Document(
            session_id=session_id,
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            gemini_file_uri=await upload_and_summarize(content, file.filename, file.content_type),
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

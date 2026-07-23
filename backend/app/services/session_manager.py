import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Directive, Document, TranscriptEntry
from app.services.gemini_files import summarize_document

logger = logging.getLogger(__name__)


async def get_active_directives(session_id: uuid.UUID, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Directive.text).where(Directive.session_id == session_id, Directive.active.is_(True))
    )
    return list(result.scalars().all())


async def get_document_summaries(session_id: uuid.UUID, db: AsyncSession) -> str:
    result = await db.execute(
        select(Document).where(Document.session_id == session_id)
    )
    docs = result.scalars().all()
    if not docs:
        return ""

    summaries = []
    for doc in docs:
        if doc.gemini_file_uri:
            try:
                summary = await summarize_document(doc.gemini_file_uri, session_id=session_id)
                summaries.append(f"### {doc.filename}\n{summary}")
            except Exception as e:
                logger.error(f"Failed to summarize {doc.filename}: {e}")
                summaries.append(f"### {doc.filename}\n(Summary unavailable)")

    return "\n\n".join(summaries)


async def get_next_sequence(session_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(TranscriptEntry.sequence)
        .where(TranscriptEntry.session_id == session_id)
        .order_by(TranscriptEntry.sequence.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    return (last or 0) + 1

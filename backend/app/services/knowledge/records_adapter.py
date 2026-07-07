"""Knowledge adapter over KnowledgeRecord rows (collection and files sources)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeRecord, KnowledgeSource
from app.services.knowledge.base import char_budget, truncate_to_budget


def render_records(records: list[KnowledgeRecord]) -> str:
    """Format knowledge records as markdown sections for the prompt."""
    blocks = []
    for r in records:
        title = (r.title or "").strip()
        body = (r.body or "").strip()
        if not body:
            continue
        blocks.append(f"### {title}\n{body}" if title else body)
    return "\n\n".join(blocks)


class RecordsAdapter:
    def __init__(self, source: KnowledgeSource):
        self._source = source
        self.source_name = source.name

    async def fetch_context(self, db: AsyncSession) -> str:
        result = await db.execute(
            select(KnowledgeRecord)
            .where(
                KnowledgeRecord.source_id == self._source.id,
                KnowledgeRecord.active.is_(True),
            )
            .order_by(KnowledgeRecord.title, KnowledgeRecord.created_at)
        )
        records = list(result.scalars().all())
        text = render_records(records)
        if not text:
            return ""
        return truncate_to_budget(text, char_budget(self._source), self.source_name)

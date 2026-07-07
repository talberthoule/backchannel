"""Built-in knowledge adapter over the Offering catalog table."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeSource, Offering
from app.services.knowledge.base import char_budget, truncate_to_budget


def render_offerings(offerings: list[Offering]) -> str:
    """Format the offerings catalog for the prompt."""
    if not offerings:
        return "(No offerings in catalog)"

    lines = []
    current_vendor = ""
    for o in offerings:
        if o.vendor != current_vendor:
            current_vendor = o.vendor
            lines.append(f"\n### {o.vendor}")
        lines.append(
            f"- **{o.product_name}** [{o.category}"
            + (f" > {o.subcategory}" if o.subcategory else "")
            + f"]: {o.description}"
            + (f" Use cases: {o.use_cases}" if o.use_cases else "")
            + (f" Note: {o.note}" if o.note else "")
            + (f" Tags: {o.tags}" if o.tags else "")
        )
    return "\n".join(lines)


class OfferingsAdapter:
    """Reads the active Offering rows; source=None is the legacy default."""

    def __init__(self, source: KnowledgeSource | None):
        self._source = source
        self.source_name = source.name if source else "Offerings"

    async def fetch_context(self, db: AsyncSession) -> str:
        result = await db.execute(
            select(Offering)
            .where(Offering.active.is_(True))
            .order_by(Offering.vendor, Offering.category, Offering.product_name)
        )
        offerings = list(result.scalars().all())
        if not offerings:
            return ""
        text = render_offerings(offerings)
        return truncate_to_budget(text, char_budget(self._source), self.source_name)

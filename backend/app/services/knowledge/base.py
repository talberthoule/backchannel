"""Knowledge source adapter protocol and shared helpers.

A knowledge adapter turns a KnowledgeSource row into ready-to-stuff prompt
context for the matching agent. Adapters are registered by source_type in
app.services.knowledge.registry.
"""

import json
import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import KnowledgeSource

logger = logging.getLogger(__name__)


class KnowledgeAdapter(Protocol):
    source_name: str

    async def fetch_context(self, db: AsyncSession) -> str:
        """Return markdown context to stuff into the matching prompt.

        An empty string means there is nothing to match against and the
        agent cycle should skip.
        """
        ...


def char_budget(source: KnowledgeSource | None) -> int:
    """Resolve the character budget for a source (config override or default)."""
    if source is not None:
        try:
            override = json.loads(source.config or "{}").get("char_budget")
            if isinstance(override, int) and override > 0:
                return override
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"[knowledge] invalid config JSON on source '{source.name}', using default budget")
    return settings.KNOWLEDGE_CONTEXT_CHAR_BUDGET


def truncate_to_budget(text: str, budget: int, source_name: str) -> str:
    """Cap context at the budget, cutting at the last newline before it."""
    if len(text) <= budget:
        return text
    cut = text.rfind("\n", 0, budget)
    if cut <= 0:
        cut = budget
    logger.warning(
        f"[knowledge] context for '{source_name}' truncated {len(text)} -> {cut} chars"
    )
    return text[:cut]

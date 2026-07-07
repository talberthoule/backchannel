"""Seed the built-in knowledge source and link the opportunity specialist."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConfig, KnowledgeSource

logger = logging.getLogger(__name__)

BUILTIN_OFFERINGS_SOURCE_NAME = "Offerings"
LEGACY_OFFERINGS_SOURCE_NAME = "Presidio Offerings"


async def seed_knowledge_sources(db: AsyncSession):
    """Insert the built-in offerings source if missing and point the
    opportunity specialist at it when it has no source configured."""
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.source_type == "offerings")
    )
    source = result.scalars().first()
    if source is None:
        source = KnowledgeSource(
            name=BUILTIN_OFFERINGS_SOURCE_NAME,
            source_type="offerings",
            description="Built-in adapter over the offerings catalog table",
        )
        db.add(source)
        await db.flush()
        logger.info("[knowledge] seeded built-in offerings knowledge source")
    elif source.name == LEGACY_OFFERINGS_SOURCE_NAME:
        source.name = BUILTIN_OFFERINGS_SOURCE_NAME
        source.description = "Built-in adapter over the offerings catalog table"
        logger.info("[knowledge] renamed built-in offerings source to 'Offerings'")

    result = await db.execute(
        select(AgentConfig).where(AgentConfig.slug == "opportunity_specialist")
    )
    agent = result.scalar_one_or_none()
    if agent is not None and not agent.knowledge_source_ids:
        agent.knowledge_source_ids = str(source.id)

    await db.commit()

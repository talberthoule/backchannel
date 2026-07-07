"""Agent configuration CRUD endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.database import get_db
from app.models import AgentConfig, KnowledgeSource
from app.schemas import AgentConfigOut, AgentConfigUpdate
from app.services.seed_agents import DEFAULT_PROMPTS

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentConfigOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentConfig).order_by(AgentConfig.display_order)
    )
    return result.scalars().all()


@router.get("/{slug}", response_model=AgentConfigOut)
async def get_agent(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.slug == slug)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.patch("/{slug}", response_model=AgentConfigOut)
async def update_agent(slug: str, body: AgentConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.slug == slug)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "model_id" and value:
            valid_ids = {m["id"] for m in MODEL_REGISTRY}
            if value not in valid_ids:
                raise HTTPException(400, f"Unknown model_id: {value}")
        if field == "knowledge_source_ids" and value:
            for raw_id in [part.strip() for part in value.split(",") if part.strip()]:
                try:
                    source_id = uuid.UUID(raw_id)
                except ValueError:
                    raise HTTPException(400, f"Invalid knowledge source id: {raw_id}")
                source = await db.get(KnowledgeSource, source_id)
                if source is None:
                    raise HTTPException(400, f"Unknown knowledge source id: {raw_id}")
        setattr(agent, field, value)

    agent.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.post("/reset/{slug}", response_model=AgentConfigOut)
async def reset_agent_prompt(slug: str, db: AsyncSession = Depends(get_db)):
    """Reset an agent's prompt to the hardcoded default."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.slug == slug)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    default_prompt = DEFAULT_PROMPTS.get(slug)
    if not default_prompt:
        raise HTTPException(400, "No default prompt available for this agent")

    agent.prompt = default_prompt
    agent.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(agent)
    return agent

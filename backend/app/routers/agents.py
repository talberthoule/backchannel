"""Agent configuration CRUD endpoints."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.database import get_db
from app.models import AgentConfig, KnowledgeSource
from app.schemas import AgentConfigOut, AgentConfigUpdate
from app.services.agents.consolidated_analyst import VALID_TYPES
from app.services.seed_agents import DEFAULT_LENSES_BY_SLUG, DEFAULT_PROMPTS

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _validate_lenses(value: str) -> None:
    """Reject malformed lens configs so a bad save can't break prompt composition."""
    try:
        lenses = json.loads(value)
    except json.JSONDecodeError:
        raise HTTPException(400, "lenses must be a valid JSON array")
    if not isinstance(lenses, list):
        raise HTTPException(400, "lenses must be a JSON array of lens objects")
    seen_keys = set()
    for lens in lenses:
        if not isinstance(lens, dict):
            raise HTTPException(400, "each lens must be an object")
        key = str(lens.get("key") or "").strip()
        label = str(lens.get("label") or "").strip()
        if not key or not label:
            raise HTTPException(400, "each lens needs a non-empty key and label")
        if key in seen_keys:
            raise HTTPException(400, f"duplicate lens key: {key}")
        seen_keys.add(key)
        if lens.get("item_type") not in VALID_TYPES:
            raise HTTPException(
                400, f"lens '{label}' has invalid item_type; must be one of {sorted(VALID_TYPES)}"
            )
        if not isinstance(lens.get("prompt", ""), str):
            raise HTTPException(400, f"lens '{label}' prompt must be a string")
        if not isinstance(lens.get("enabled", True), bool):
            raise HTTPException(400, f"lens '{label}' enabled must be a boolean")


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
        if field == "lenses" and value:
            _validate_lenses(value)
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
    default_lenses = DEFAULT_LENSES_BY_SLUG.get(slug)
    if default_lenses is not None:
        agent.lenses = json.dumps(default_lenses)
    agent.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(agent)
    return agent

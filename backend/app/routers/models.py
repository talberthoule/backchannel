from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.database import get_db
from app.services.provider_health import provider_key_availability

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelOut(BaseModel):
    id: str
    name: str
    provider: str
    description: str
    tier: str
    requires_key: str | None = None
    key_available: bool = True
    supports_text: bool = False
    supports_batch_audio: bool = False
    supports_live_audio: bool = False


@router.get("", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    """Return all models in the registry, with per-provider key availability.

    A provider is available when a key exists (stored or env) and that key
    has not failed its connection test.
    """
    key_available = await provider_key_availability(db)
    return [
        {
            **model,
            "key_available": key_available.get(model["requires_key"], True)
            if model["requires_key"]
            else True,
        }
        for model in MODEL_REGISTRY
    ]

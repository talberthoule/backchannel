from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.database import get_db
from app.services.model_pricing import MODEL_PRICING, PRICING_AS_OF
from app.services.provider_health import provider_key_availability

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelPricing(BaseModel):
    # USD per 1M tokens, standard text-tier rates (see services/model_pricing.py
    # for the simplifications). None = no published rate for that dimension.
    input_per_million: float | None = None
    output_per_million: float | None = None
    cached_input_per_million: float | None = None
    audio_input_per_million: float | None = None


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


class ModelPricingOut(BaseModel):
    as_of: str
    models: dict[str, ModelPricing | None]


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


@router.get("/pricing", response_model=ModelPricingOut)
def get_model_pricing():
    """Return published per-token pricing keyed by model id.

    Kept separate from GET /api/models because that endpoint returns a bare
    list (no top-level spot for the shared as-of date) and cost consumers
    (the post-call Tokens tab) only need a model_id -> rates map.
    """
    return {"as_of": PRICING_AS_OF, "models": MODEL_PRICING}

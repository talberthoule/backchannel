from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_MODEL_RECOMMENDATION_ROLES, MODEL_REGISTRY
from app.database import get_db
from app.services.custom_endpoints import endpoint_models
from app.services.llm_endpoint import OPENAI_COMPATIBLE_MODEL, legacy_endpoint_configured
from app.services.model_pricing import MODEL_PRICING, PRICING_AS_OF
from app.services.local_fit import local_model_recommendations
from app.services.provider_health import provider_key_availability

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelPricing(BaseModel):
    # USD per 1M tokens, standard text-tier rates (see services/model_pricing.py
    # for the simplifications). None = no published rate for that dimension.
    input_per_million: float | None = None
    output_per_million: float | None = None
    cached_input_per_million: float | None = None
    audio_input_per_million: float | None = None
    # USD per minute of audio, for models billed by duration rather than
    # tokens. Omitting it here silently stripped the live gateway's only
    # published rate from the response (ALP-300).
    per_minute: float | None = None
    # Audio output tokens (the live gateway answers in audio) bill above the
    # text output rate where published.
    audio_output_per_million: float | None = None


class ModelRecommendation(BaseModel):
    role: str
    provider: str
    recommended: bool = True
    source: str
    interval_seconds: int | None = None
    reasoning_effort: str | None = None


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
    # True when the model runs on this machine or its network, so it stays
    # usable in Privacy First mode. Covers both the bundled ONNX models and
    # models served by an on-prem endpoint.
    runs_locally: bool = False
    # Set for models served by a saved custom endpoint.
    endpoint_id: str | None = None
    recommendations: list[ModelRecommendation] = Field(default_factory=list)


class ModelPricingOut(BaseModel):
    as_of: str
    models: dict[str, ModelPricing | None]


@router.get("", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    """Registry models plus every model served by a saved custom endpoint.

    A provider is available when a key exists (stored or env) and that key
    has not failed its connection test. The legacy single-endpoint placeholder
    is only listed while it is actually configured, so workspaces using named
    endpoints never see it competing with their real model names.
    """
    key_available = await provider_key_availability(db)
    show_legacy = await legacy_endpoint_configured(db)
    local_recommendations = await local_model_recommendations(db)
    registry = [
        {
            **model,
            "key_available": key_available.get(model["requires_key"], True)
            if model["requires_key"]
            else True,
            "runs_locally": model["provider"].lower() == "local",
            "recommendations": [
                {
                    "role": role,
                    "provider": model["requires_key"] or model["provider"].lower(),
                    "recommended": True,
                    "source": "provider_default",
                    **(
                        {"reasoning_effort": "high"}
                        if model["id"] == "gpt-5.6-sol" and role == "brief_arbiter"
                        else {}
                    ),
                }
                for role in DEFAULT_MODEL_RECOMMENDATION_ROLES.get(model["id"], ())
            ],
        }
        for model in MODEL_REGISTRY
        if model["id"] != OPENAI_COMPATIBLE_MODEL or show_legacy
    ]
    endpoints = await endpoint_models(db)
    for model in registry + endpoints:
        model["recommendations"] = (
            model.get("recommendations", [])
            + local_recommendations.get(model["id"], [])
        )
    return registry + endpoints


@router.get("/pricing", response_model=ModelPricingOut)
def get_model_pricing():
    """Return published per-token pricing keyed by model id.

    Kept separate from GET /api/models because that endpoint returns a bare
    list (no top-level spot for the shared as-of date) and cost consumers
    (the post-call Tokens tab) only need a model_id -> rates map.
    """
    return {"as_of": PRICING_AS_OF, "models": MODEL_PRICING}

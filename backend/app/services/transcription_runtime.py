from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.models import AgentConfig
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.privacy import DEFAULT_LOCAL_BATCH_MODEL, get_local_only, is_local_model

SETTING_BATCH_TRANSCRIBER_MODEL = "transcription.batch.model_id"
AUDIO_GATEWAY_SLUG = "audio_gateway"
@dataclass(frozen=True)
class TranscriptionRuntimeConfig:
    batch_model_id: str
    live_preview_model_id: str
    description: str

    def to_dict(self) -> dict:
        return {
            "batch_model_id": self.batch_model_id,
            "live_preview_model_id": self.live_preview_model_id,
            "description": self.description,
        }


def is_supported_transcription_model(model_id: str) -> bool:
    model = next((model for model in MODEL_REGISTRY if model["id"] == model_id), None)
    return bool(model and model.get("supports_batch_audio"))


def is_supported_live_model(model_id: str) -> bool:
    model = next((model for model in MODEL_REGISTRY if model["id"] == model_id), None)
    return bool(model and model.get("supports_live_audio"))


async def _get_audio_gateway_config(db: AsyncSession) -> AgentConfig | None:
    result = await db.execute(select(AgentConfig).where(AgentConfig.slug == AUDIO_GATEWAY_SLUG))
    return result.scalar_one_or_none()


async def get_transcription_runtime_config(db: AsyncSession) -> TranscriptionRuntimeConfig:
    configured_model = await get_app_setting(
        db,
        SETTING_BATCH_TRANSCRIBER_MODEL,
        "",
    )
    if (
        is_supported_transcription_model(configured_model)
        and not is_local_model(configured_model)
        and await get_local_only(db)
    ):
        # Privacy First mode: never send audio to a cloud transcriber.
        configured_model = DEFAULT_LOCAL_BATCH_MODEL

    # The live preview model is the Audio Gateway agent's model; keep the two
    # views (this card and the agent list) reading and writing the same row.
    gateway = await _get_audio_gateway_config(db)
    live_model = gateway.model_id if gateway else ""

    return TranscriptionRuntimeConfig(
        batch_model_id=configured_model,
        live_preview_model_id=live_model,
        description=(
            "Batch transcription creates finalized transcript text for audio imports "
            "and diarized live segments. Live preview transcription is the separate "
            "audio gateway agent used only for interim captions while a call is active."
        ),
    )


async def set_batch_transcriber_model(db: AsyncSession, model_id: str) -> TranscriptionRuntimeConfig:
    if not is_supported_transcription_model(model_id):
        raise ValueError("Selected model is not available for batch audio transcription.")
    if not is_local_model(model_id) and await get_local_only(db):
        raise ValueError(
            "Privacy First mode is on: only local transcription models can be selected."
        )
    await set_app_setting(db, SETTING_BATCH_TRANSCRIBER_MODEL, model_id)
    await db.commit()
    return await get_transcription_runtime_config(db)


async def set_live_preview_model(db: AsyncSession, model_id: str) -> TranscriptionRuntimeConfig:
    if not is_supported_live_model(model_id):
        raise ValueError("Selected model is not available for live interim transcription.")
    if not is_local_model(model_id) and await get_local_only(db):
        raise ValueError(
            "Privacy First mode is on: the live audio gateway is disabled and only "
            "local models can be selected."
        )
    gateway = await _get_audio_gateway_config(db)
    if gateway is None:
        raise ValueError("Audio gateway agent is not configured.")
    gateway.model_id = model_id
    await db.commit()
    return await get_transcription_runtime_config(db)

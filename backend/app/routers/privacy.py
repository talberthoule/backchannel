from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.privacy import get_local_only, privacy_impact, set_local_only
from app.services.transcription_runtime import get_transcription_runtime_config

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


class PrivacyUpdate(BaseModel):
    local_only: bool


async def _config_payload(db: AsyncSession) -> dict:
    runtime = await get_transcription_runtime_config(db)
    return {
        "local_only": await get_local_only(db),
        "batch_model_id": runtime.batch_model_id,
        "impact": privacy_impact(),
    }


@router.get("")
async def get_privacy_config(db: AsyncSession = Depends(get_db)):
    """Current Privacy First state plus what enabling it keeps and disables."""
    return await _config_payload(db)


@router.put("")
async def update_privacy_config(update: PrivacyUpdate, db: AsyncSession = Depends(get_db)):
    # The stored batch-model choice is left untouched: while the flag is on the
    # runtime coerces it to a local model, and turning the flag off restores it.
    await set_local_only(db, update.local_only)
    await db.commit()
    return await _config_payload(db)

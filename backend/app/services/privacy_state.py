"""Persistence for the Privacy First flag."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_settings import get_app_setting, set_app_setting

logger = logging.getLogger(__name__)

PRIVACY_LOCAL_ONLY_KEY = "privacy.local_only"


async def get_local_only(db: AsyncSession) -> bool:
    return await get_app_setting(db, PRIVACY_LOCAL_ONLY_KEY, "false") == "true"


async def set_local_only(db: AsyncSession, enabled: bool) -> None:
    await set_app_setting(db, PRIVACY_LOCAL_ONLY_KEY, "true" if enabled else "false")
    logger.info(f"Privacy First (local-only) mode {'enabled' if enabled else 'disabled'}")

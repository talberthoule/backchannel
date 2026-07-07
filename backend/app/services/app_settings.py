from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting


async def get_app_setting(db: AsyncSession, key: str, default: str = "") -> str:
    setting = await db.get(AppSetting, key)
    return setting.value if setting else default


async def set_app_setting(db: AsyncSession, key: str, value: str) -> AppSetting:
    setting = await db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    setting.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return setting

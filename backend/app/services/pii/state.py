"""The PII Shield's persisted switch, readable without importing the shield.

``transcription_runtime`` needs to know whether the shield is on to lock
audio to local models, and the shield's own status report needs the
transcription runtime. Keeping the flag reader here, with no dependency on
either, is what keeps that from being a cycle.
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_settings import get_app_setting

SETTINGS_KEY = "pii.shield"


async def shield_enabled(db: AsyncSession) -> bool:
    try:
        raw = await get_app_setting(db, SETTINGS_KEY, "")
        return bool(raw) and bool(json.loads(raw).get("enabled", False))
    except (TypeError, AttributeError, ValueError):
        # A stand-in session in tests, or a malformed row: the shield is off.
        return False

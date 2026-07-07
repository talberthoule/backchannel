"""Encrypted workspace credentials stored in app_settings.

Values are Fernet tokens; the master key lives OUTSIDE the database, either
in the CREDENTIALS_MASTER_KEY env var or auto-generated at DATA_DIR/master.key.
"""

import hashlib
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.services.app_settings import get_app_setting, set_app_setting

logger = logging.getLogger(__name__)

PROVIDERS = ["google", "openai"]

_fernet: Fernet | None = None


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/app/data"))


def _master_key() -> bytes:
    env_key = os.environ.get("CREDENTIALS_MASTER_KEY")
    if env_key:
        return env_key.encode()
    key_file = data_dir() / "master.key"
    if key_file.exists():
        return key_file.read_bytes().strip()
    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    logger.info(f"Generated new credentials master key at {key_file}")
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_master_key())
    return _fernet


async def get_secret(db, key: str) -> str:
    token = await get_app_setting(db, key)
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.warning(
            f"Could not decrypt {key}; master key changed? "
            f"(env CREDENTIALS_MASTER_KEY or {data_dir() / 'master.key'})"
        )
        return ""


async def set_secret(db, key: str, value: str) -> None:
    token = _get_fernet().encrypt(value.encode()).decode() if value else ""
    await set_app_setting(db, key, token)


def env_provider_key(provider: str) -> str:
    if provider == "google":
        return settings.GEMINI_API_KEY
    if provider == "openai":
        return settings.OPENAI_API_KEY
    return ""


async def get_provider_key(db, provider: str) -> str:
    stored = await get_secret(db, f"credentials.{provider}.api_key")
    if stored:
        return stored
    return env_provider_key(provider)


async def resolve_provider_key(provider: str) -> str:
    """get_provider_key with its own short-lived DB session."""
    from app.database import async_session

    async with async_session() as db:
        return await get_provider_key(db, provider)


def mask_key(value: str) -> str:
    if len(value) < 12:
        return ""
    return f"{value[:4]}...{value[-4:]}"


def key_fingerprint(value: str) -> str:
    """Non-reversible identity for a key, used to tie a passed connection
    test to the exact key that passed it."""
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()

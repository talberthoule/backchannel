"""Provider API-key connection health.

A key counts as "connected" once that exact key (matched by fingerprint) has
passed a connection test. Keys that have never been tested are treated as
available so the UI does not lock working setups; a background task at
startup tests them and records the outcome, after which a bad key locks its
provider's models until it is replaced or passes a test.
"""

import logging

import httpx

from app.services.app_settings import get_app_setting, set_app_setting
from app.services.llm_endpoint import (
    auth_headers,
    fallback_base_url,
    normalize_base_url,
    resolve_base_url,
)
from app.services.secrets import (
    PROVIDERS,
    env_provider_key,
    get_provider_key,
    get_secret,
    key_fingerprint,
    mask_key,
)

logger = logging.getLogger(__name__)

_FAILED_PREFIX = "failed:"


def _status_key(provider: str) -> str:
    return f"credentials.{provider}.verified_fingerprint"


async def run_connection_test(provider: str, key: str, base_url: str = "") -> tuple[bool, str]:
    """Probe a provider. base_url defaults to the hosted OpenAI API, so the
    Google and OpenAI paths behave exactly as they did before it existed."""
    try:
        if provider == "google":
            from google import genai

            client = genai.Client(api_key=key)
            await client.aio.models.list(config={"page_size": 1})
        else:
            url = normalize_base_url(base_url) or fallback_base_url()
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{url}/models", headers=auth_headers(key))
                resp.raise_for_status()
        return True, "Connection successful"
    except Exception as e:
        return False, str(e)[:300]


async def record_test_outcome(db, provider: str, key: str, ok: bool) -> None:
    fingerprint = key_fingerprint(key)
    value = fingerprint if ok else f"{_FAILED_PREFIX}{fingerprint}"
    await set_app_setting(db, _status_key(provider), value)
    await db.commit()


async def clear_test_outcome(db, provider: str) -> None:
    await set_app_setting(db, _status_key(provider), "")
    await db.commit()


async def get_provider_status(db, provider: str) -> dict:
    stored = await get_secret(db, f"credentials.{provider}.api_key")
    effective = stored or env_provider_key(provider)
    record = await get_app_setting(db, _status_key(provider))
    fingerprint = key_fingerprint(effective)
    connected = bool(effective) and record == fingerprint
    known_bad = bool(effective) and record == f"{_FAILED_PREFIX}{fingerprint}"
    return {
        "provider": provider,
        "configured": bool(stored),
        "env_fallback": bool(not stored and effective),
        "masked": mask_key(effective),
        "connected": connected,
        "key_available": bool(effective) and not known_bad,
    }


async def provider_key_availability(db) -> dict[str, bool]:
    availability: dict[str, bool] = {}
    for provider in PROVIDERS:
        status = await get_provider_status(db, provider)
        availability[provider] = status["key_available"]
    return availability


async def verify_untested_provider_keys() -> None:
    """Test provider keys that have no recorded outcome for their current value."""
    from app.database import async_session

    from app.services.privacy import get_local_only

    try:
        async with async_session() as db:
            if await get_local_only(db):
                logger.info("Privacy First mode is on; skipping provider key verification")
                return
            for provider in PROVIDERS:
                key = await get_provider_key(db, provider)
                # Keyless providers (a local OpenAI-compatible server) are not
                # probed at startup; the Test button in Admin covers them.
                if not key:
                    continue
                record = await get_app_setting(db, _status_key(provider))
                fingerprint = key_fingerprint(key)
                if record in (fingerprint, f"{_FAILED_PREFIX}{fingerprint}"):
                    continue
                base_url = await resolve_base_url(db, provider)
                ok, message = await run_connection_test(provider, key, base_url)
                await record_test_outcome(db, provider, key, ok)
                if ok:
                    logger.info(f"Verified {provider} API key connection at startup")
                else:
                    logger.warning(f"{provider} API key failed its connection test: {message}")
    except Exception:
        logger.exception("Startup provider key verification failed")

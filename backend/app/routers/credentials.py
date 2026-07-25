from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.llm_endpoint import (
    OPENAI_COMPATIBLE_PROVIDER,
    get_endpoint_config,
    requires_api_key,
    resolve_base_url,
    set_endpoint_config,
)
from app.services.provider_health import (
    clear_test_outcome,
    get_provider_status,
    record_test_outcome,
    run_connection_test,
)
from app.services.secrets import PROVIDERS, get_provider_key, set_secret

router = APIRouter(prefix="/api/credentials", tags=["credentials"])

_ENDPOINT_PATH = f"/{OPENAI_COMPATIBLE_PROVIDER}/endpoint"


class CredentialIn(BaseModel):
    api_key: str


class TextEndpointIn(BaseModel):
    # Omitted fields are left untouched; an empty string clears the setting
    # back to the environment variable or built-in default.
    base_url: str | None = None
    model_id: str | None = None


def _check_provider(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")


@router.get("")
async def list_credentials(db: AsyncSession = Depends(get_db)):
    return [await get_provider_status(db, provider) for provider in PROVIDERS]


@router.get(_ENDPOINT_PATH)
async def read_text_endpoint(db: AsyncSession = Depends(get_db)):
    """Base URL and wire model id for the OpenAI-compatible text provider."""
    return await get_endpoint_config(db)


@router.put(_ENDPOINT_PATH)
async def update_text_endpoint(body: TextEndpointIn, db: AsyncSession = Depends(get_db)):
    try:
        config = await set_endpoint_config(db, base_url=body.base_url, model_id=body.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return config


@router.put("/{provider}")
async def save_credential(provider: str, body: CredentialIn, db: AsyncSession = Depends(get_db)):
    _check_provider(provider)
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key must not be empty")
    await set_secret(db, f"credentials.{provider}.api_key", key)
    await db.commit()
    ok, message = await run_connection_test(provider, key, await resolve_base_url(db, provider))
    await record_test_outcome(db, provider, key, ok)
    info = await get_provider_status(db, provider)
    info["message"] = "Saved - connection verified" if ok else f"Saved, but the connection test failed: {message}"
    return info


@router.delete("/{provider}", status_code=204)
async def delete_credential(provider: str, db: AsyncSession = Depends(get_db)):
    _check_provider(provider)
    await set_secret(db, f"credentials.{provider}.api_key", "")
    await clear_test_outcome(db, provider)


@router.post("/{provider}/test")
async def test_credential(provider: str, db: AsyncSession = Depends(get_db)):
    _check_provider(provider)
    key = await get_provider_key(db, provider)
    # A self-hosted OpenAI-compatible server is usually unauthenticated, so a
    # missing key must not short-circuit its connection test.
    if not key and requires_api_key(provider):
        return {"ok": False, "message": "No API key configured"}
    ok, message = await run_connection_test(provider, key, await resolve_base_url(db, provider))
    await record_test_outcome(db, provider, key, ok)
    return {"ok": ok, "message": message}

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.provider_health import (
    clear_test_outcome,
    get_provider_status,
    record_test_outcome,
    run_connection_test,
)
from app.services.secrets import PROVIDERS, get_provider_key, set_secret

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


class CredentialIn(BaseModel):
    api_key: str


def _check_provider(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")


@router.get("")
async def list_credentials(db: AsyncSession = Depends(get_db)):
    return [await get_provider_status(db, provider) for provider in PROVIDERS]


@router.put("/{provider}")
async def save_credential(provider: str, body: CredentialIn, db: AsyncSession = Depends(get_db)):
    _check_provider(provider)
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key must not be empty")
    await set_secret(db, f"credentials.{provider}.api_key", key)
    await db.commit()
    ok, message = await run_connection_test(provider, key)
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
    if not key:
        return {"ok": False, "message": "No API key configured"}
    ok, message = await run_connection_test(provider, key)
    await record_test_outcome(db, provider, key, ok)
    return {"ok": ok, "message": message}

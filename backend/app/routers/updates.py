import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Session
from app.services import runtime_activity
from app.services.update_service import UpdateService, get_update_service


router = APIRouter(prefix="/api/updates", tags=["updates"])


class GrantIn(BaseModel):
    grant: str


def require_instance_token(
    token: str | None = Header(default=None, alias="X-Backchannel-Instance"),
) -> None:
    expected = os.environ.get("BACKCHANNEL_INSTANCE_TOKEN", "")
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(403, "Desktop instance authorization failed")


@router.get("")
def update_status(service: UpdateService = Depends(get_update_service)):
    status = service.status()
    if status.get("state") == "ready":
        status["blocked_reason"] = runtime_activity.busy_reason()
    return status


@router.post("/check", dependencies=[Depends(require_instance_token)])
def check_update(service: UpdateService = Depends(get_update_service)):
    return service.check(force=True)


@router.post("/grant", dependencies=[Depends(require_instance_token)])
def accept_update_grant(
    body: GrantIn,
    service: UpdateService = Depends(get_update_service),
):
    try:
        return service.start_download(body.grant)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(409, str(error)) from error


@router.delete("/download", dependencies=[Depends(require_instance_token)])
def cancel_update(service: UpdateService = Depends(get_update_service)):
    return service.cancel_download()


@router.post("/apply", dependencies=[Depends(require_instance_token)])
async def apply_update(
    db: AsyncSession = Depends(get_db),
    service: UpdateService = Depends(get_update_service),
):
    if not runtime_activity.reserve_shutdown():
        reason = runtime_activity.busy_reason() or "active work"
        raise HTTPException(409, f"Finish {reason} before installing.")
    accepted = False
    try:
        active = await db.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.state == "active")
        )
        if active:
            raise HTTPException(409, "Finish the active call before installing.")
        try:
            result = service.request_apply()
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        accepted = True
        return result
    finally:
        if not accepted:
            runtime_activity.release_shutdown()

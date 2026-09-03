"""The shield's status report for the Privacy tab.

Presentation over several services (the shield settings, the transcription
runtime, the audio gateway and refiner agent rows, the vault and audit
tables). It lives beside the shield rather than inside it so the shield
module itself depends on nothing that depends on it.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConfig, PiiRevealEvent, PiiVaultEntry
from app.services import model_downloads
from app.services.local_live_captioner import is_local_live_model
from app.services.pii import ner
from app.services.pii.recognizers import CATEGORIES, CATEGORY_LABELS
from app.services.pii.shield import get_settings
from app.services.privacy import is_local_model
from app.services.transcript_refiner import REFINER_SLUG
from app.services.transcription_runtime import get_transcription_runtime_config


async def _agent(db: AsyncSession, slug: str) -> AgentConfig | None:
    return (await db.execute(select(AgentConfig).where(AgentConfig.slug == slug))).scalar_one_or_none()


def _ner_state(settings) -> str:
    if not settings.ner:
        return "off"
    if ner.is_installed() and not ner.load_error():
        return "ready"
    if model_downloads.is_running(ner.DOWNLOAD_KEY):
        return "downloading"
    return "unavailable" if ner.load_error() else "not_downloaded"


async def status(db: AsyncSession) -> dict:
    """Settings plus an honest coverage report.

    Text is covered whenever the shield is on. With the shield on the
    transcription runtime coerces the batch model to a local one and the
    orchestrator skips a cloud gateway, so both audio rows are covered by
    enforcement; a cloud gateway choice is reported as paused.
    """
    settings = await get_settings(db)
    runtime = await get_transcription_runtime_config(db)
    gateway = await _agent(db, "audio_gateway")
    gateway_model = gateway.model_id if gateway and gateway.enabled else ""
    gateway_is_local = not gateway_model or is_local_live_model(gateway_model)
    refiner = await _agent(db, REFINER_SLUG)

    vault_total = (await db.execute(select(func.count(PiiVaultEntry.id)))).scalar_one() or 0
    since = datetime.now(timezone.utc) - timedelta(days=1)
    reveals = (
        await db.execute(
            select(func.count(PiiRevealEvent.id), func.coalesce(func.sum(PiiRevealEvent.token_count), 0))
            .where(PiiRevealEvent.at >= since)
        )
    ).one()

    return {
        "settings": asdict(settings),
        "categories": [{"id": c, "label": CATEGORY_LABELS[c]} for c in CATEGORIES],
        "ner": {
            "state": _ner_state(settings),
            "error": ner.load_error(),
            "model": ner.MODEL_REPO,
            "download": model_downloads.get(ner.DOWNLOAD_KEY),
        },
        "coverage": {
            "text": settings.enabled,
            "enforced": settings.enabled,
            "transcription": {"covered": is_local_model(runtime.batch_model_id), "model_id": runtime.batch_model_id},
            "live_gateway": {
                "covered": gateway_is_local or settings.enabled,
                "model_id": gateway_model,
                "paused": bool(gateway_model) and not gateway_is_local and settings.enabled,
            },
            "documents": settings.enabled,
            "refinement": {
                "enabled": bool(refiner and refiner.enabled and refiner.model_id),
                "model_id": refiner.model_id if refiner else "",
                "interval_seconds": refiner.interval_seconds if refiner else 45,
            },
        },
        "vault": {"entries": int(vault_total)},
        "reveals_24h": {"requests": int(reveals[0] or 0), "tokens": int(reveals[1] or 0)},
    }

"""Privacy First (local-only) mode.

When enabled, every feature that needs an outside API call is turned off and
processing is restricted to models that run on this machine. The flag is a
persisted app setting so it survives restarts and applies to all sessions.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.services.app_settings import get_app_setting, set_app_setting

logger = logging.getLogger(__name__)

PRIVACY_LOCAL_ONLY_KEY = "privacy.local_only"

# Preferred fallback when the configured batch transcriber is a cloud model.
DEFAULT_LOCAL_BATCH_MODEL = "local-whisper-base"


class LocalOnlyModeError(ValueError):
    """Raised when a cloud-only feature is used while Privacy First mode is on."""

    def __init__(self, feature: str):
        super().__init__(
            f"Privacy First mode is on: {feature} requires an outside API call and "
            "has no local alternative. Disable Privacy First mode in Admin to use it."
        )
        self.feature = feature


def is_local_model(model_id: str) -> bool:
    entry = next((m for m in MODEL_REGISTRY if m["id"] == model_id), None)
    if entry:
        return entry["provider"].lower() == "local"
    return model_id.startswith("local-")


def local_models(capability: str) -> list[dict]:
    """Registry entries with the given capability that run locally."""
    return [
        m for m in MODEL_REGISTRY
        if m["provider"].lower() == "local" and m.get(capability)
    ]


async def get_local_only(db: AsyncSession) -> bool:
    return await get_app_setting(db, PRIVACY_LOCAL_ONLY_KEY, "false") == "true"


async def is_local_only() -> bool:
    """Read the flag with a standalone session (for call sites without a db)."""
    from app.database import async_session

    async with async_session() as db:
        return await get_local_only(db)


async def set_local_only(db: AsyncSession, enabled: bool) -> None:
    await set_app_setting(db, PRIVACY_LOCAL_ONLY_KEY, "true" if enabled else "false")
    logger.info(f"Privacy First (local-only) mode {'enabled' if enabled else 'disabled'}")


def privacy_impact() -> dict:
    """What keeps working and what stops, derived from the model registry.

    Computed dynamically so the lists stay accurate if local models gain
    text or live-audio support later.
    """
    local_batch = local_models("supports_batch_audio")
    local_text = local_models("supports_text")
    local_live = local_models("supports_live_audio")

    available = [
        {
            "feature": "Live call recording & speaker diarization",
            "detail": "Silero VAD and WeSpeaker embeddings already run locally via ONNX.",
        },
        {
            "feature": "Transcription (live segments, audio import, re-transcription)",
            "detail": (
                "Switches to local ONNX models: "
                + ", ".join(m["name"] for m in local_batch)
                + ". Weights download once, then run offline."
            )
            if local_batch
            else "No local transcription model installed.",
        },
        {
            "feature": "Transcript file import, knowledge file conversion, and exports",
            "detail": "File parsing (MarkItDown, docx) and TXT/XLSX/HTML exports are local.",
        },
        {
            "feature": "Sessions, speakers, directives, and offerings management",
            "detail": "All stored in the local PostgreSQL database.",
        },
    ]

    disabled = []
    if not local_live:
        disabled.append({
            "feature": "Live interim captions (audio gateway)",
            "detail": "Streams call audio to Gemini Live or OpenAI Realtime; no local option.",
        })
    if not local_text:
        disabled.extend([
            {
                "feature": "AI analysis agents",
                "detail": (
                    "Consolidated Analyst, Objection Handler, Synthesizer, Opportunity "
                    "Specialist, and Call Briefing all need a cloud text model."
                ),
            },
            {
                "feature": "Post-import transcript analysis",
                "detail": "The Analyze action sends the transcript to a cloud model.",
            },
            {
                "feature": "Meeting chat",
                "detail": "Chat over past transcripts routes through a cloud text model.",
            },
            {
                "feature": "Document upload & summarization",
                "detail": "Session documents are uploaded to the Gemini Files API.",
            },
            {
                "feature": "Insight enhancement",
                "detail": "Speaker-context insight enrichment uses a cloud text model.",
            },
        ])

    return {"available": available, "disabled": disabled}

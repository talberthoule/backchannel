"""Privacy First (local-only) mode.

When enabled, every feature that needs an outside API call is turned off and
processing is restricted to models that run on this machine. The flag is a
persisted app setting so it survives restarts and applies to all sessions.
"""

import logging
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MODEL_REGISTRY
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.custom_endpoints import is_endpoint_model, resolve_target_standalone

logger = logging.getLogger(__name__)

PRIVACY_LOCAL_ONLY_KEY = "privacy.local_only"

# Preferred fallback when the configured batch transcriber is a cloud model.
DEFAULT_LOCAL_BATCH_MODEL = "local-whisper-base"


class LocalOnlyModeError(ValueError):
    """Raised when Privacy First refuses the model a feature was asked to use.

    The remedy that matters first is pointing the agent at a self-hosted model,
    because that keeps the guarantee the mode exists to make. Turning the mode
    off is the fallback, not the headline. When the caller knows which agent and
    model were refused, naming them saves the user hunting through Admin.
    """

    def __init__(self, feature: str, model_id: str = "", agent: str = ""):
        target = f"'{agent}' is set to {model_id}" if agent and model_id else (
            f"it is set to {model_id}" if model_id else ""
        )
        cause = (
            f", and {target}, which sends data off this machine and its network"
            if target
            else ", which requires an outside API call"
        )
        super().__init__(
            f"Privacy First mode is on: {feature} is unavailable{cause}. "
            "Assign a self-hosted model in Admin -> Agents (any endpoint on this "
            "machine or your LAN qualifies), or turn off Privacy First mode in "
            "Admin -> Transcription & Audio."
        )
        self.feature = feature
        self.model_id = model_id
        self.agent = agent


def is_local_model(model_id: str) -> bool:
    entry = next((m for m in MODEL_REGISTRY if m["id"] == model_id), None)
    if entry:
        return entry["provider"].lower() == "local"
    return model_id.startswith("local-")


async def allows_local_only(model_id: str) -> bool:
    """True when this model can still run with Privacy First mode on.

    Bundled ONNX models qualify, and so does any model served by an endpoint
    on this machine or its network: the audio and text never leave the
    perimeter, which is the guarantee the mode exists to make. An endpoint
    reachable only over the public internet does not qualify.
    """
    if is_local_model(model_id):
        return True
    if not is_endpoint_model(model_id):
        return False
    target = await resolve_target_standalone(model_id)
    return bool(target and target.on_prem)


async def admitted_model_ids(model_ids: Iterable[str], local_only: bool = True) -> set[str]:
    """The subset of model_ids Privacy First still admits.

    Callers that gate several agents at once (the orchestrator, the briefing
    pipeline) need the verdict for every assigned model before they can decide
    what runs. Resolving an endpoint model is a database read, so each distinct
    id is resolved exactly once here rather than on every agent tick.

    With the mode off every model is admitted, which lets callers use the same
    membership test on both paths instead of branching on the flag.
    """
    unique = {m for m in model_ids if m}
    if not local_only:
        return unique
    admitted = set()
    for model_id in unique:
        try:
            if await allows_local_only(model_id):
                admitted.add(model_id)
        except Exception:
            # One unresolvable model (a transient database error reading its
            # endpoint) pauses only its own agent instead of aborting call
            # setup. Leaving it out of the set is the fail-closed choice: an
            # unverified model is never admitted.
            logger.warning(
                "Could not resolve %s for Privacy First; treating it as not admitted",
                model_id,
                exc_info=True,
            )
    return admitted


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


def privacy_impact(on_prem_text_models: list[dict] | None = None) -> dict:
    """What keeps working and what stops, derived from the model registry.

    Computed dynamically so the lists stay accurate if local models gain
    text or live-audio support later. on_prem_text_models are the models
    served by endpoints on this machine or its network (see
    services/custom_endpoints.py): configuring one moves the analysis agents
    from the disabled list to the available list, because a self-hosted model
    can do that work without an outside API call.

    A feature only moves when a self-hosted model can actually carry it. That
    covers everything routed through services/llm.py, including the two
    features that borrow an agent row's model (post-import Analyze and speaker
    context enhancement). Document summarization never moves: it calls the
    Gemini Files API directly rather than choosing a text model.
    """
    local_batch = local_models("supports_batch_audio")
    local_text = local_models("supports_text") + list(on_prem_text_models or [])
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

    if local_text:
        available.append({
            "feature": (
                "AI analysis agents, transcript analysis, insight enhancement, "
                "and meeting chat"
            ),
            "detail": (
                "Point them at a self-hosted model: "
                + ", ".join(m["name"] for m in local_text)
                + ". Prompts and transcripts stay on your network."
            ),
        })

    if local_live:
        available.append({
            "feature": "Live interim captions (on-device)",
            "detail": (
                "Experimental on-device captioner: "
                + ", ".join(m["name"] for m in local_live)
                + " transcribes short audio chunks locally. CPU-heavy; check the fit test first."
            ),
        })

    disabled = []
    if not local_live:
        disabled.append({
            "feature": "Live interim captions (audio gateway)",
            "detail": "Streams call audio to Gemini Live or OpenAI Realtime; no local option.",
        })
    # Unconditional: this one is not a text-model choice. It calls the Gemini
    # Files API itself, so no self-hosted model can stand in for it and the
    # entry must not disappear the moment an on-prem text model is configured.
    disabled.append({
        "feature": "Document upload & summarization",
        "detail": (
            "Session documents are uploaded to the Gemini Files API, which has "
            "no self-hosted equivalent. Configuring a local text model does not "
            "enable it."
        ),
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
                "feature": "Insight enhancement",
                "detail": "Speaker-context insight enrichment uses a cloud text model.",
            },
        ])

    return {"available": available, "disabled": disabled}

"""Base URL and wire-model resolution for OpenAI-shaped text endpoints.

The text router speaks two OpenAI-shaped dialects. Provider "openai" is the
hosted OpenAI API; provider "openai-compatible" is any OpenAI-compatible chat
server -- Ollama (http://localhost:11434/v1), LM Studio
(http://localhost:1234/v1), vLLM, LiteLLM. Both POST to
{base_url}/chat/completions, so only the base URL, the wire model name, and
the API key differ.

Resolution is layered exactly like the batch transcriber model
(BATCH_TRANSCRIBER_MODEL vs the persisted transcription.batch.model_id app
setting): the app setting wins, the environment variable is the fallback, and
the built-in default keeps every existing install pointed at
https://api.openai.com/v1 when nothing is configured.

The openai-compatible registry entry is a single stable id, because a local
server's model names (llama3.1:8b, qwen2.5-coder, ...) are unknown at build
time. The name actually sent on the wire comes from the model-id setting.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.app_settings import get_app_setting, set_app_setting

OPENAI_PROVIDER = "openai"
OPENAI_COMPATIBLE_PROVIDER = "openai-compatible"
# Registry id of the placeholder model whose wire name comes from a setting.
OPENAI_COMPATIBLE_MODEL = "openai-compatible"

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

SETTING_BASE_URL = "llm.openai_compatible.base_url"
SETTING_MODEL_ID = "llm.openai_compatible.model_id"


class TextEndpointNotConfigured(ValueError):
    """The OpenAI-compatible endpoint is selected but not fully configured."""


@dataclass(frozen=True)
class OpenAIEndpoint:
    base_url: str
    model: str


def is_openai_shaped(provider: str) -> bool:
    return provider in (OPENAI_PROVIDER, OPENAI_COMPATIBLE_PROVIDER)


def requires_api_key(provider: str) -> bool:
    """Local OpenAI-compatible servers usually accept unauthenticated calls."""
    return provider != OPENAI_COMPATIBLE_PROVIDER


def normalize_base_url(raw: str) -> str:
    return (raw or "").strip().rstrip("/")


def fallback_base_url() -> str:
    """Env var value, or the built-in default when it is unset or blank."""
    return normalize_base_url(settings.OPENAI_BASE_URL) or DEFAULT_OPENAI_BASE_URL


def auth_headers(key: str) -> dict:
    """Bearer header, omitted entirely when no key is configured.

    Some local servers reject a request that carries an empty bearer token,
    so a keyless endpoint must send no Authorization header at all.
    """
    return {"Authorization": f"Bearer {key}"} if key else {}


def validate_base_url(raw: str) -> str:
    url = normalize_base_url(raw)
    if url and not url.startswith(("http://", "https://")):
        raise ValueError("Base URL must start with http:// or https://")
    return url


async def resolve_base_url(db: AsyncSession, provider: str) -> str:
    """Setting (openai-compatible only) > OPENAI_BASE_URL env > built-in default."""
    if provider != OPENAI_COMPATIBLE_PROVIDER:
        return fallback_base_url()
    stored = normalize_base_url(await get_app_setting(db, SETTING_BASE_URL))
    return stored or fallback_base_url()


async def resolve_wire_model(db: AsyncSession, provider: str, model_id: str) -> str:
    """The model name sent to the server.

    Every provider but openai-compatible sends its registry id unchanged.
    """
    if provider != OPENAI_COMPATIBLE_PROVIDER:
        return model_id
    stored = (await get_app_setting(db, SETTING_MODEL_ID)).strip()
    resolved = stored or settings.OPENAI_COMPATIBLE_MODEL_ID.strip()
    if not resolved:
        raise TextEndpointNotConfigured(
            "No model id configured for the OpenAI-compatible endpoint; set the "
            "model your server exposes in Admin -> API Keys"
        )
    return resolved


async def resolve_endpoint_with(
    db: AsyncSession, provider: str, model_id: str
) -> OpenAIEndpoint:
    return OpenAIEndpoint(
        base_url=await resolve_base_url(db, provider),
        model=await resolve_wire_model(db, provider, model_id),
    )


async def resolve_endpoint(provider: str, model_id: str) -> OpenAIEndpoint:
    """resolve_endpoint_with() using its own short-lived DB session.

    Providers other than openai-compatible never read the database, so the
    hosted OpenAI path stays exactly as cheap as before this setting existed.
    """
    if provider != OPENAI_COMPATIBLE_PROVIDER:
        return OpenAIEndpoint(base_url=fallback_base_url(), model=model_id)

    from app.database import async_session

    async with async_session() as db:
        return await resolve_endpoint_with(db, provider, model_id)


async def get_endpoint_config(db: AsyncSession) -> dict:
    stored_url = normalize_base_url(await get_app_setting(db, SETTING_BASE_URL))
    stored_model = (await get_app_setting(db, SETTING_MODEL_ID)).strip()
    return {
        "provider": OPENAI_COMPATIBLE_PROVIDER,
        "model_registry_id": OPENAI_COMPATIBLE_MODEL,
        # What is persisted; empty means "fall back".
        "base_url": stored_url,
        "model_id": stored_model,
        # What requests actually use.
        "effective_base_url": stored_url or fallback_base_url(),
        "effective_model_id": stored_model or settings.OPENAI_COMPATIBLE_MODEL_ID.strip(),
        "fallback_base_url": fallback_base_url(),
    }


async def set_endpoint_config(
    db: AsyncSession,
    base_url: str | None = None,
    model_id: str | None = None,
) -> dict:
    """Persist either field; an empty string clears it back to the fallback."""
    if base_url is not None:
        await set_app_setting(db, SETTING_BASE_URL, validate_base_url(base_url))
    if model_id is not None:
        await set_app_setting(db, SETTING_MODEL_ID, model_id.strip())
    return await get_endpoint_config(db)

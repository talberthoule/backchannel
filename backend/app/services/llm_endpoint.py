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

Two shapes of openai-compatible model coexist. Models with an "endpoint:..."
id name one of the workspace's saved endpoints (services/custom_endpoints.py)
and carry their own base URL and key, so several servers can be configured at
once. The bare "openai-compatible" registry id is the original single-endpoint
path, kept working for installs configured through OPENAI_BASE_URL and
OPENAI_COMPATIBLE_MODEL_ID environment variables.
"""

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AgentConfig
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.custom_endpoints import (
    build_model_id,
    create_endpoint,
    is_endpoint_model,
    list_endpoints,
    resolve_target,
    resolve_target_standalone,
)
from app.services.secrets import get_secret

logger = logging.getLogger(__name__)

OPENAI_PROVIDER = "openai"
OPENAI_COMPATIBLE_PROVIDER = "openai-compatible"
# Registry id of the placeholder model whose wire name comes from a setting.
OPENAI_COMPATIBLE_MODEL = "openai-compatible"

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

SETTING_BASE_URL = "llm.openai_compatible.base_url"
SETTING_MODEL_ID = "llm.openai_compatible.model_id"


class TextEndpointNotConfigured(ValueError):
    """The OpenAI-compatible endpoint is selected but not fully configured."""


class EndpointUnavailable(ValueError):
    """A saved endpoint model points at an endpoint that is gone or disabled."""


@dataclass(frozen=True)
class OpenAIEndpoint:
    base_url: str
    model: str
    # Key for this specific endpoint. None means "use the provider-wide key",
    # which is what every hosted model and the legacy single endpoint do.
    api_key: str | None = None


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
            "model your server exposes in Admin -> Connections"
        )
    return resolved


def _from_target(target, model_id: str) -> OpenAIEndpoint:
    if target is None:
        raise EndpointUnavailable(
            f"The endpoint behind {model_id} no longer exists; pick another model "
            "or re-add the endpoint in Admin -> Connections"
        )
    if not target.enabled:
        raise EndpointUnavailable(
            f"Endpoint '{target.name}' is turned off; enable it in Admin -> Connections "
            f"or pick another model"
        )
    return OpenAIEndpoint(base_url=target.base_url, model=target.model, api_key=target.api_key)


async def resolve_endpoint_with(
    db: AsyncSession, provider: str, model_id: str
) -> OpenAIEndpoint:
    if is_endpoint_model(model_id):
        return _from_target(await resolve_target(db, model_id), model_id)
    return OpenAIEndpoint(
        base_url=await resolve_base_url(db, provider),
        model=await resolve_wire_model(db, provider, model_id),
    )


async def resolve_endpoint(provider: str, model_id: str) -> OpenAIEndpoint:
    """resolve_endpoint_with() using its own short-lived DB session.

    Hosted models never read the database, so the OpenAI and Gemini paths stay
    exactly as cheap as before any of this configuration existed.
    """
    if is_endpoint_model(model_id):
        return _from_target(await resolve_target_standalone(model_id), model_id)
    if provider != OPENAI_COMPATIBLE_PROVIDER:
        return OpenAIEndpoint(base_url=fallback_base_url(), model=model_id)

    from app.database import async_session

    async with async_session() as db:
        return await resolve_endpoint_with(db, provider, model_id)


async def legacy_endpoint_configured(db: AsyncSession) -> bool:
    """Whether the single pre-endpoints text endpoint is still in use.

    True only when a base URL or wire model is set for it, through either the
    app settings or the environment variables. Installs that have moved to
    named endpoints answer False, which is what hides the placeholder model
    from the pickers.
    """
    if normalize_base_url(await get_app_setting(db, SETTING_BASE_URL)):
        return True
    if (await get_app_setting(db, SETTING_MODEL_ID)).strip():
        return True
    return bool(settings.OPENAI_COMPATIBLE_MODEL_ID.strip())


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


# Default ports of the servers this feature was built against, used only to
# give a migrated endpoint a recognizable name.
_PORT_NAMES = {"1234": "LM Studio", "11434": "Ollama", "8000": "vLLM", "4000": "LiteLLM"}


def _guess_endpoint_name(base_url: str) -> str:
    port = urlparse(base_url).port
    return _PORT_NAMES.get(str(port), "Custom endpoint")


async def migrate_legacy_endpoint(db: AsyncSession) -> str | None:
    """Turn a configured single endpoint into a named endpoint row.

    Runs once, at startup, only when the old settings hold a complete
    configuration and no named endpoints exist yet. Agents pointed at the
    placeholder model are repointed at the migrated model so the workspace
    behaves identically, except the model now appears in the pickers under
    its own name. Returns the new model id, or None when nothing was migrated.
    """
    if await list_endpoints(db):
        return None
    base_url = normalize_base_url(await get_app_setting(db, SETTING_BASE_URL))
    wire_model = (await get_app_setting(db, SETTING_MODEL_ID)).strip()
    if not base_url or not wire_model:
        return None

    endpoint = await create_endpoint(
        db,
        name=_guess_endpoint_name(base_url),
        base_url=base_url,
        # The provider-wide compatible key becomes this endpoint's key; the
        # credential row is left alone so the env fallback keeps working.
        api_key=await get_secret(db, f"credentials.{OPENAI_COMPATIBLE_PROVIDER}.api_key"),
        models=[{"id": wire_model}],
    )
    new_model_id = build_model_id(endpoint.id, wire_model)
    await db.execute(
        update(AgentConfig)
        .where(AgentConfig.model_id == OPENAI_COMPATIBLE_MODEL)
        .values(model_id=new_model_id)
    )
    # Clearing the settings retires the placeholder from the model pickers.
    await set_app_setting(db, SETTING_BASE_URL, "")
    await set_app_setting(db, SETTING_MODEL_ID, "")
    await db.commit()
    logger.info(
        "Migrated the legacy OpenAI-compatible endpoint to '%s' (%s) serving %s",
        endpoint.name,
        base_url,
        wire_model,
    )
    return new_model_id

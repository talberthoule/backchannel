"""Self-hosted OpenAI-compatible endpoints and the models they expose.

An endpoint is any OpenAI-shaped chat server the workspace can reach: LM Studio
(http://localhost:1234/v1), Ollama (http://localhost:11434/v1), vLLM, LiteLLM,
or a shared GPU box on the LAN. Each endpoint row lists the models it serves,
and every one of those becomes a first-class, named entry in the model
registry, so a lab-hosted model appears in the agent pickers next to the hosted
Gemini and OpenAI models instead of hiding behind one opaque placeholder.

Model ids are "endpoint:<endpoint slug>:<wire model name>". The slug identifies
which server to call, the remainder is the name sent in the chat-completions
payload, and the prefix lets the synchronous parts of the registry (llm.provider_for)
route an id to the OpenAI-compatible dialect without touching the database.
"""

import ipaddress
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CustomEndpoint
from app.services.secrets import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

MODEL_PREFIX = "endpoint"
# agent_configs.model_id is varchar(160); leave room so a long served model
# name fails validation with a clear message instead of a database error.
MAX_MODEL_ID_LENGTH = 160
MAX_ENDPOINT_SLUG = 24

# Hostname suffixes that only resolve inside a home, lab, or office network.
_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")
# Docker Desktop's alias for the machine hosting the container.
_DOCKER_HOST_ALIASES = ("host.docker.internal", "gateway.docker.internal")


class EndpointError(ValueError):
    """Invalid endpoint definition; routers translate this into a 400."""


@dataclass(frozen=True)
class EndpointTarget:
    """Everything a chat-completions call needs for one endpoint model."""

    endpoint_id: str
    name: str
    base_url: str
    model: str
    api_key: str
    on_prem: bool
    enabled: bool


def is_endpoint_model(model_id: str) -> bool:
    return model_id.startswith(f"{MODEL_PREFIX}:")


def build_model_id(endpoint_id: str, wire_model: str) -> str:
    return f"{MODEL_PREFIX}:{endpoint_id}:{wire_model}"


def parse_model_id(model_id: str) -> tuple[str, str] | None:
    """Split an endpoint model id into (endpoint slug, wire model name).

    Only the first two colons are structural: Ollama tags such as
    "llama3.1:8b" keep their own colons in the wire name.
    """
    parts = model_id.split(":", 2)
    if len(parts) != 3 or parts[0] != MODEL_PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:MAX_ENDPOINT_SLUG].strip("-")


def normalize_base_url(raw: str) -> str:
    return (raw or "").strip().rstrip("/")


def validate_base_url(raw: str) -> str:
    url = normalize_base_url(raw)
    if not url:
        raise EndpointError("Base URL is required")
    if not url.startswith(("http://", "https://")):
        raise EndpointError("Base URL must start with http:// or https://")
    if not urlparse(url).netloc:
        raise EndpointError("Base URL must include a host, e.g. http://localhost:1234/v1")
    return url


def _numeric_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Interpret a dot-less host as a single-integer inet_aton IPv4.

    glibc/musl ``getaddrinfo`` (which httpx uses) still routes a bare-integer,
    ``0x`` hex, or leading-zero octal host to a real address, so both
    "134744072" and "0x08080808" reach 8.8.8.8. Those must be judged by their
    value, not mistaken for a single-label LAN hostname. Returns the address, or
    None when the host is not such a numeric form (e.g. a genuine hostname).
    """
    h = host.lower()
    try:
        if h.startswith("0x"):
            value = int(h, 16)
        elif h.startswith("0") and len(h) > 1:
            value = int(h, 8)
        else:
            value = int(h, 10)
    except ValueError:
        return None
    if not 0 <= value <= 0xFFFFFFFF:
        return None
    return ipaddress.IPv4Address(value)


def is_on_prem(base_url: str) -> bool:
    """True when the URL can only be reached from this machine or its network.

    Drives Privacy First: a model served from localhost or the LAN never leaves
    the perimeter, so it stays usable when outside API calls are turned off. A
    public hostname is treated as off-prem even though it speaks the same
    protocol, because it may well be a hosted inference provider.
    """
    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        return False
    if host in _DOCKER_HOST_ALIASES or host.endswith(_PRIVATE_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." in host:
            # A dotted name that is not a canonical IP is a public hostname.
            return False
        # No dot: either an alternate IP encoding (judge by its real value) or a
        # genuine single-label LAN hostname.
        numeric = _numeric_ipv4(host)
        if numeric is None:
            return True
        address = numeric
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        # ::ffff:8.8.8.8 must be judged by its embedded IPv4 on every
        # interpreter version, not by the IPv6 wrapper.
        address = address.ipv4_mapped
    return address.is_loopback or address.is_private or address.is_link_local


def normalize_models(raw: list | None) -> list[dict]:
    """Clean a submitted model list into [{"id", "label"}] with no duplicates."""
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, dict):
            continue
        wire = str(item.get("id") or "").strip()
        if not wire or wire in seen:
            continue
        seen.add(wire)
        normalized.append({"id": wire, "label": str(item.get("label") or "").strip() or wire})
    return normalized


def _validate_model_ids(endpoint_id: str, models: list[dict]) -> None:
    for model in models:
        model_id = build_model_id(endpoint_id, model["id"])
        if len(model_id) > MAX_MODEL_ID_LENGTH:
            raise EndpointError(
                f"Model name '{model['id']}' is too long for this endpoint; "
                f"shorten it or use a shorter endpoint name"
            )


def to_dict(endpoint: CustomEndpoint) -> dict:
    """API shape. The stored key is never returned, only whether one exists."""
    models = [
        {
            "id": model["id"],
            "label": model.get("label") or model["id"],
            "model_id": build_model_id(endpoint.id, model["id"]),
        }
        for model in normalize_models(endpoint.models)
    ]
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "base_url": endpoint.base_url,
        "has_api_key": bool(endpoint.api_key),
        "models": models,
        "enabled": endpoint.enabled,
        "on_prem": is_on_prem(endpoint.base_url),
        "last_status": endpoint.last_status,
        "last_error": endpoint.last_error,
        "last_checked_at": endpoint.last_checked_at.isoformat() if endpoint.last_checked_at else None,
    }


async def list_endpoints(db: AsyncSession) -> list[CustomEndpoint]:
    result = await db.execute(
        select(CustomEndpoint)
        .where(CustomEndpoint.deleted_at.is_(None))
        .order_by(CustomEndpoint.display_order, CustomEndpoint.created_at)
    )
    return list(result.scalars().all())


async def get_endpoint(db: AsyncSession, endpoint_id: str) -> CustomEndpoint | None:
    endpoint = await db.get(CustomEndpoint, endpoint_id)
    return endpoint if endpoint is not None and endpoint.deleted_at is None else None


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name) or "endpoint"
    slug = base
    suffix = 2
    while await db.get(CustomEndpoint, slug) is not None:
        slug = f"{base[: MAX_ENDPOINT_SLUG - len(str(suffix)) - 1]}-{suffix}"
        suffix += 1
    return slug


async def create_endpoint(
    db: AsyncSession,
    *,
    name: str,
    base_url: str,
    api_key: str = "",
    models: list | None = None,
    enabled: bool = True,
) -> CustomEndpoint:
    label = (name or "").strip()
    if not label:
        raise EndpointError("Name is required")
    url = validate_base_url(base_url)
    slug = await _unique_slug(db, label)
    entries = normalize_models(models)
    _validate_model_ids(slug, entries)
    existing = await list_endpoints(db)
    endpoint = CustomEndpoint(
        id=slug,
        name=label[:80],
        base_url=url,
        api_key=encrypt_value(api_key.strip()),
        models=entries,
        enabled=enabled,
        display_order=len(existing),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(endpoint)
    await db.flush()
    logger.info("Added custom endpoint %s (%s) with %d model(s)", slug, url, len(entries))
    return endpoint


async def update_endpoint(
    db: AsyncSession,
    endpoint: CustomEndpoint,
    *,
    name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    models: list | None = None,
    enabled: bool | None = None,
    confirm_off_prem: bool = False,
) -> CustomEndpoint:
    """Patch semantics: omitted fields keep their stored value.

    api_key is the exception worth noting - an empty string clears the stored
    key, which is how a user turns an authenticated proxy back into a keyless
    local server.
    """
    if name is not None:
        label = name.strip()
        if not label:
            raise EndpointError("Name is required")
        endpoint.name = label[:80]
    if base_url is not None:
        new_url = validate_base_url(base_url)
        # Reaching a different server invalidates the recorded test outcome.
        if new_url != endpoint.base_url:
            if is_on_prem(endpoint.base_url) and not is_on_prem(new_url):
                from app.services.privacy import get_local_only

                if await get_local_only(db):
                    raise EndpointError(
                        "Privacy First is on; this endpoint cannot move from on-prem "
                        "to an off-prem base URL. Turn off Privacy First first or keep "
                        "the endpoint on this machine or network."
                    )
                if not confirm_off_prem:
                    raise EndpointError(
                        "This change moves the endpoint off-prem and can send call data "
                        "outside this machine or network. Repeat with "
                        "confirm_off_prem=true to confirm."
                    )
            endpoint.last_status = ""
            endpoint.last_error = ""
            endpoint.last_checked_at = None
        endpoint.base_url = new_url
    if api_key is not None:
        endpoint.api_key = encrypt_value(api_key.strip())
    if models is not None:
        entries = normalize_models(models)
        _validate_model_ids(endpoint.id, entries)
        endpoint.models = entries
    if enabled is not None:
        endpoint.enabled = enabled
    endpoint.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return endpoint


async def delete_endpoint(db: AsyncSession, endpoint: CustomEndpoint) -> None:
    endpoint.deleted_at = datetime.now(timezone.utc)
    endpoint.api_key = ""
    await db.flush()
    logger.info("Retired custom endpoint %s", endpoint.id)


async def record_probe(db: AsyncSession, endpoint: CustomEndpoint, ok: bool, message: str) -> None:
    endpoint.last_status = "ok" if ok else "error"
    endpoint.last_error = "" if ok else message[:500]
    endpoint.last_checked_at = datetime.now(timezone.utc)
    await db.flush()


def auth_headers(api_key: str) -> dict:
    """Bearer header, omitted entirely when the endpoint is keyless.

    Some local servers reject a request carrying an empty bearer token, so a
    keyless endpoint must send no Authorization header at all.
    """
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def probe(base_url: str, api_key: str = "", timeout: float = 10.0) -> tuple[bool, str, list[str]]:
    """GET {base_url}/models. Returns (reachable, message, served model names)."""
    try:
        url = validate_base_url(base_url)
    except EndpointError as exc:
        return False, str(exc), []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{url}/models", headers=auth_headers(api_key))
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        return False, f"Server returned HTTP {exc.response.status_code}", []
    except httpx.ConnectError:
        return False, f"Could not connect to {url}. Is the server running and reachable?", []
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the operator
        return False, str(exc)[:300], []
    served = [
        str(item.get("id"))
        for item in (payload.get("data") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    return True, f"Connected. {len(served)} model(s) available.", served


def _registry_entry(
    endpoint_id: str, endpoint_name: str, base_url: str, wire: str, label: str
) -> dict:
    """One model's capability metadata, shaped like a MODEL_REGISTRY row.

    Endpoints are chat servers, so their models are text-only: audio
    transcription stays with the bundled ONNX models and the cloud
    speech-to-text models.
    """
    on_prem = is_on_prem(base_url)
    return {
        "id": build_model_id(endpoint_id, wire),
        "name": label or wire,
        "provider": endpoint_name,
        "description": (
            f"{wire} served by {endpoint_name} at {base_url}" + (" (on-prem)" if on_prem else "")
        ),
        "tier": "stable",
        "requires_key": None,
        "key_available": True,
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
        "runs_locally": on_prem,
        "endpoint_id": endpoint_id,
    }


async def endpoint_models(db: AsyncSession) -> list[dict]:
    """Registry-shaped entries for every model on every enabled endpoint."""
    entries: list[dict] = []
    for endpoint in await list_endpoints(db):
        if not endpoint.enabled:
            continue
        for model in normalize_models(endpoint.models):
            entries.append(
                _registry_entry(
                    endpoint.id, endpoint.name, endpoint.base_url, model["id"], model.get("label")
                )
            )
    return entries


async def endpoint_model_entry(db: AsyncSession, model_id: str) -> dict | None:
    """Capability metadata for one endpoint model id, or None if unusable.

    Routers that validate a submitted model id against MODEL_REGISTRY call
    this for the ids that are not in it, so a self-hosted model is accepted
    everywhere a registry model is. Validation is strict about the model
    actually being listed on an enabled endpoint; resolve_target stays lenient
    so an agent already pointed at a model keeps working if that list is
    edited later.
    """
    parsed = parse_model_id(model_id)
    if parsed is None:
        return None
    endpoint_id, wire = parsed
    endpoint = await db.get(CustomEndpoint, endpoint_id)
    if endpoint is None or endpoint.deleted_at is not None or not endpoint.enabled:
        return None
    model = next((m for m in normalize_models(endpoint.models) if m["id"] == wire), None)
    if model is None:
        return None
    return _registry_entry(endpoint.id, endpoint.name, endpoint.base_url, wire, model["label"])


async def resolve_target(db: AsyncSession, model_id: str) -> EndpointTarget | None:
    """The endpoint behind an "endpoint:..." model id, or None if it is gone."""
    parsed = parse_model_id(model_id)
    if parsed is None:
        return None
    endpoint_id, wire_model = parsed
    endpoint = await db.get(CustomEndpoint, endpoint_id)
    if endpoint is None:
        return None
    if endpoint.deleted_at is not None:
        raise EndpointError(
            f"Endpoint '{endpoint.name}' was deleted at {endpoint.deleted_at.isoformat()}; "
            "pick another model or add a new endpoint in Admin -> Connections."
        )
    return EndpointTarget(
        endpoint_id=endpoint.id,
        name=endpoint.name,
        base_url=endpoint.base_url,
        model=wire_model,
        api_key=decrypt_value(endpoint.api_key),
        on_prem=is_on_prem(endpoint.base_url),
        enabled=endpoint.enabled,
    )


async def resolve_target_standalone(model_id: str) -> EndpointTarget | None:
    """resolve_target() with its own short-lived session, for callers without a db."""
    from app.database import async_session

    async with async_session() as db:
        return await resolve_target(db, model_id)

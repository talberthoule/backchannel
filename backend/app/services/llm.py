"""Provider-routed text generation.

Single entry point generate_text() picks the client by the model's provider
in MODEL_REGISTRY: Google via google-genai, OpenAI via the HTTP API.
Unknown model ids default to Google so legacy ids stored in the DB keep working.
"""

import logging

import httpx
from google import genai
from google.genai import types

from app.config import MODEL_REGISTRY
from app.services.privacy import LocalOnlyModeError, is_local_only
from app.services.secrets import resolve_provider_key
from app.services.token_usage import record_token_usage

logger = logging.getLogger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"


class LLMKeyMissing(ValueError):
    def __init__(self, provider: str):
        super().__init__(f"No API key configured for {provider}; add one in Admin -> API Keys")
        self.provider = provider


def registry_entry(model_id: str) -> dict | None:
    return next((m for m in MODEL_REGISTRY if m["id"] == model_id), None)


def provider_for(model_id: str) -> str:
    entry = registry_entry(model_id)
    if entry:
        return entry["provider"].lower()
    # Ids no longer in the registry may persist in agent_configs rows; infer
    # the provider by prefix so stored OpenAI ids keep routing correctly.
    if model_id.startswith(("gpt-", "openai-", "o1", "o3", "o4")):
        return "openai"
    return "google"


async def _resolve_key(provider: str) -> str:
    return await resolve_provider_key(provider)


async def _call_google(model_id: str, prompt: str, system: str | None, temperature: float | None, key: str) -> tuple[str, object]:
    config_kwargs = {}
    if system is not None:
        config_kwargs["system_instruction"] = system
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    client = genai.Client(api_key=key)
    response = await client.aio.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
    )
    return response.text or "", getattr(response, "usage_metadata", None)


async def _call_openai(model_id: str, prompt: str, system: str | None, temperature: float | None, key: str) -> tuple[str, object]:
    messages = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict = {"model": model_id, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"] or "", data.get("usage")


async def generate_text(
    model_id: str,
    prompt: str,
    *,
    system: str | None = None,
    temperature: float | None = None,
    session_id: object | None = None,
    source: str = "",
) -> str:
    provider = provider_for(model_id)
    if provider != "local" and await is_local_only():
        raise LocalOnlyModeError(f"text generation with {model_id}")
    key = await _resolve_key(provider)
    if not key:
        raise LLMKeyMissing(provider)
    if provider == "openai":
        text, usage = await _call_openai(model_id, prompt, system, temperature, key)
    else:
        text, usage = await _call_google(model_id, prompt, system, temperature, key)
    await record_token_usage(session_id, source, model_id, usage)
    return text

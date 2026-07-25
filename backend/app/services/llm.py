"""Provider-routed text generation.

Entry points generate_text() and generate_json() pick the client by the
model's provider in MODEL_REGISTRY: Google via google-genai, OpenAI and any
OpenAI-compatible server via the HTTP API. Unknown model ids default to
Google so legacy ids stored in the DB keep working.

The OpenAI-shaped base URL and wire model name are resolved per call by
services/llm_endpoint.py rather than hardcoded, which is what lets an agent
target a local Ollama, LM Studio, vLLM, or LiteLLM server.
"""

import json
import logging

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import MODEL_REGISTRY
from app.services.llm_endpoint import (
    OpenAIEndpoint,
    auth_headers,
    is_openai_shaped,
    requires_api_key,
    resolve_endpoint,
)
from app.services.privacy import LocalOnlyModeError, is_local_only
from app.services.secrets import resolve_provider_key
from app.services.token_usage import record_token_usage

logger = logging.getLogger(__name__)


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


async def _call_openai(endpoint: OpenAIEndpoint, prompt: str, system: str | None, temperature: float | None, key: str) -> tuple[str, object]:
    messages = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict = {"model": endpoint.model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{endpoint.base_url}/chat/completions",
            headers=auth_headers(key),
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
    if not key and requires_api_key(provider):
        raise LLMKeyMissing(provider)
    if is_openai_shaped(provider):
        endpoint = await resolve_endpoint(provider, model_id)
        text, usage = await _call_openai(endpoint, prompt, system, temperature, key)
    else:
        text, usage = await _call_google(model_id, prompt, system, temperature, key)
    await record_token_usage(session_id, source, model_id, usage)
    return text


_JSON_CONTRACT_HEADER = "## Required JSON Contract"

_STRICT_JSON_REPROMPT = (
    "The previous reply was not valid JSON for the required contract. "
    "Return exactly one valid JSON object matching the contract, with no "
    "markdown or commentary."
)


def parse_json_response(raw: str, response_schema: type[BaseModel]):
    """Parse a model reply into response_schema, tolerating markdown fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    if not raw:
        return response_schema()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            raise
        data = json.loads(raw[start:end + 1])
    return response_schema.model_validate(data)


def _contract_prompt(prompt: str, schema_hint: str) -> str:
    return f"{prompt.rstrip()}\n\n{_JSON_CONTRACT_HEADER}\n{schema_hint}"


def _default_schema_hint(response_schema: type[BaseModel]) -> str:
    return (
        "Return exactly one valid JSON object matching this JSON Schema. "
        "Do not include markdown or commentary.\n"
        f"{json.dumps(response_schema.model_json_schema(), indent=2)}"
    )


def _parse_google_response(response, response_schema: type[BaseModel]):
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, response_schema):
            return parsed
        if isinstance(parsed, dict):
            return response_schema.model_validate(parsed)
        return parsed
    return parse_json_response(response.text or "", response_schema)


async def _google_json(
    model_id: str,
    prompt: str,
    response_schema: type[BaseModel],
    schema_hint: str,
    key: str,
    session_id,
    source: str,
):
    client = genai.Client(api_key=key)

    async def call(text_prompt: str, config):
        response = await client.aio.models.generate_content(
            model=model_id,
            contents=text_prompt,
            config=config,
        )
        await record_token_usage(
            session_id, source, model_id, getattr(response, "usage_metadata", None)
        )
        return response

    try:
        response = await call(
            prompt,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        return _parse_google_response(response, response_schema)
    except Exception as exc:
        logger.warning(
            "Structured schema call failed for %s/%s; retrying JSON contract prompt: %s",
            model_id,
            response_schema.__name__,
            exc,
        )
    contract = _contract_prompt(prompt, schema_hint)
    try:
        response = await call(
            contract,
            types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except TypeError:
        response = await call(contract, None)
    return _parse_google_response(response, response_schema)


async def _openai_json(
    model_id: str,
    endpoint: OpenAIEndpoint,
    prompt: str,
    response_schema: type[BaseModel],
    schema_hint: str,
    key: str,
    session_id,
    source: str,
):
    contract = _contract_prompt(prompt, schema_hint)

    async def call(messages: list[dict]) -> str:
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{endpoint.base_url}/chat/completions",
                headers=auth_headers(key),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        await record_token_usage(session_id, source, model_id, data.get("usage"))
        return data["choices"][0]["message"]["content"] or ""

    text = await call([{"role": "user", "content": contract}])
    try:
        return parse_json_response(text, response_schema)
    except ValueError as exc:
        # json.JSONDecodeError and pydantic.ValidationError are ValueErrors.
        logger.warning(
            "OpenAI JSON reply failed validation for %s/%s; re-prompting once: %s",
            model_id,
            response_schema.__name__,
            exc,
        )
    text = await call([
        {"role": "user", "content": contract},
        {"role": "assistant", "content": text},
        {"role": "user", "content": _STRICT_JSON_REPROMPT},
    ])
    return parse_json_response(text, response_schema)


async def generate_json(
    model_id: str,
    prompt: str,
    response_schema: type[BaseModel],
    *,
    schema_hint: str | None = None,
    session_id: object | None = None,
    source: str = "",
):
    """Provider-routed structured generation validated against a Pydantic schema.

    Routes by the model's registry provider exactly like generate_text().
    Google models use Gemini's native response_schema JSON mode, retrying once
    with a JSON-contract prompt if the schema call fails. OpenAI-shaped models
    use response_format json_object with the contract appended to the prompt,
    re-prompting strictly at most once when the reply fails parsing or schema
    validation. schema_hint overrides the auto-derived contract text. Token
    usage is recorded per provider call so the Tokens tab stays accurate.
    """
    provider = provider_for(model_id)
    if provider != "local" and await is_local_only():
        raise LocalOnlyModeError(f"structured generation with {model_id}")
    key = await _resolve_key(provider)
    if not key and requires_api_key(provider):
        raise LLMKeyMissing(provider)
    hint = schema_hint or _default_schema_hint(response_schema)
    if is_openai_shaped(provider):
        endpoint = await resolve_endpoint(provider, model_id)
        return await _openai_json(
            model_id, endpoint, prompt, response_schema, hint, key, session_id, source
        )
    return await _google_json(
        model_id, prompt, response_schema, hint, key, session_id, source
    )

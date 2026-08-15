"""Provider-routed text generation.

Entry points generate_text() and generate_json() pick the client by the
model's provider in MODEL_REGISTRY: Google via google-genai, OpenAI and any
OpenAI-compatible server via the HTTP API. Unknown model ids default to
Google so legacy ids stored in the DB keep working.

The OpenAI-shaped base URL, wire model name, and per-endpoint key are resolved
per call by services/llm_endpoint.py rather than hardcoded, which is what lets
an agent target a local Ollama, LM Studio, vLLM, or LiteLLM server.
"""

import json
import logging
from dataclasses import dataclass

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import MODEL_REGISTRY, settings
from app.services.custom_endpoints import is_endpoint_model
from app.services.llm_endpoint import (
    OPENAI_COMPATIBLE_PROVIDER,
    OpenAIEndpoint,
    auth_headers,
    is_openai_shaped,
    requires_api_key,
    resolve_endpoint,
)
from app.services.privacy import LocalOnlyModeError, allows_local_only, is_local_only
from app.services.secrets import resolve_provider_key
from app.services.token_usage import record_token_usage

logger = logging.getLogger(__name__)


class LLMReplyTruncated(ValueError):
    """The server stopped generating before the reply was complete.

    Its own class because the raw symptom is a json decode error partway
    through a well-formed document, which reads like a broken model rather
    than an output budget the user can raise.
    """

    def __init__(self, model_id: str, source: str = ""):
        subject = f"{source} ({model_id})" if source else model_id
        super().__init__(
            f"{subject} hit its output limit before finishing the reply. Raise the "
            "server's max tokens (or LLM_SELF_HOSTED_MAX_TOKENS), or use a model "
            "with more output headroom."
        )
        self.model_id = model_id
        self.source = source


def _is_self_hosted(model_id: str) -> bool:
    """Whether this model is served by one of the workspace's own endpoints.

    Self-hosted servers are the slow, small-budget case: they run on whatever
    hardware the user has rather than a provider's fleet.
    """
    return is_endpoint_model(model_id)


def _request_timeout(model_id: str) -> float:
    return (
        settings.LLM_SELF_HOSTED_TIMEOUT_SECONDS
        if _is_self_hosted(model_id)
        else settings.LLM_TIMEOUT_SECONDS
    )


def _apply_output_budget(payload: dict, model_id: str, budget: int | None = None) -> dict:
    """Give every provider an explicit completion budget.

    This used to exempt hosted providers, on the reasoning that their defaults
    are generous and a cap could only make things worse. The opposite turned
    out to be true. With no ceiling, a reply that degenerates runs until the
    provider stops it: on one measured session five synthesizer calls emitted
    47k-63k output tokens each - 95 percent of that agent's output and 22
    percent of the entire session bill - and every one of them was then
    DISCARDED as unparseable and retried. The generous default was not buying
    headroom, it was setting the price of failure.

    A cap does not rescue those calls; a reply truncated at 4k fails schema
    parsing exactly as one truncated at 63k does, and the existing retry still
    runs. It only stops the doomed attempt costing sixteen times what it needs
    to. Healthy calls are nowhere near the ceiling - the observed median output
    for that same agent is 300 tokens (ALP-295).

    budget overrides the default with whatever this particular server has been
    observed to accept.
    """
    self_hosted = _is_self_hosted(model_id)
    effective = budget
    if effective is None:
        effective = (
            settings.LLM_SELF_HOSTED_MAX_TOKENS
            if self_hosted
            else settings.LLM_HOSTED_MAX_TOKENS
        )
    if effective > 0:
        # The two shapes disagree on the field name. OpenAI renamed it for
        # newer models and rejects the old one outright - "Unsupported
        # parameter: 'max_tokens' is not supported with this model. Use
        # 'max_completion_tokens' instead." Self-hosted OpenAI-compatible
        # servers (LM Studio, Ollama, vLLM) only know max_tokens, and that
        # path has been shipping against them for a while, so it keeps it.
        #
        # This only became reachable when hosted providers started getting a
        # budget at all; before that the hosted branch returned early and the
        # disagreement was invisible.
        key = "max_tokens" if self_hosted else "max_completion_tokens"
        payload[key] = effective
    return payload


def _truncated(data: dict) -> bool:
    choices = data.get("choices") or [{}]
    return (choices[0] or {}).get("finish_reason") == "length"


class LLMKeyMissing(ValueError):
    def __init__(self, provider: str):
        super().__init__(f"No API key configured for {provider}; add one in Admin -> Connections")
        self.provider = provider


class LLMModelNotSelected(ValueError):
    def __init__(self, source: str = ""):
        subject = source or "This feature"
        super().__init__(
            f"{subject} has no model selected; choose one in Admin -> Agents."
        )
        self.source = source


def registry_entry(model_id: str) -> dict | None:
    return next((m for m in MODEL_REGISTRY if m["id"] == model_id), None)


def provider_for(model_id: str) -> str:
    # Custom endpoint models are not in the static registry: their ids encode
    # which saved endpoint serves them, and they all speak the OpenAI dialect.
    if is_endpoint_model(model_id):
        return OPENAI_COMPATIBLE_PROVIDER
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


@dataclass(frozen=True)
class _CallTarget:
    provider: str
    key: str
    endpoint: OpenAIEndpoint | None  # None for Google


async def _prepare_call(model_id: str, feature: str, source: str = "") -> _CallTarget:
    """Privacy gate, endpoint resolution, and key selection for one call.

    An endpoint model carries its own key (often empty, because local servers
    are unauthenticated), so it never consults the provider-wide credential.

    source is the caller's own label (the same one token usage is recorded
    under). Passing it through means a refusal names which feature and which
    model were involved, so the user is told what to change instead of only
    that something is off. Every caller of this module gets that for free,
    which is why the naming lives here rather than at each call site.
    """
    if not model_id.strip():
        raise LLMModelNotSelected(source)
    provider = provider_for(model_id)
    if provider != "local" and await is_local_only() and not await allows_local_only(model_id):
        raise LocalOnlyModeError(feature, model_id, source)
    endpoint = await resolve_endpoint(provider, model_id) if is_openai_shaped(provider) else None
    key = endpoint.api_key if endpoint and endpoint.api_key is not None else await _resolve_key(provider)
    if not key and requires_api_key(provider):
        raise LLMKeyMissing(provider)
    return _CallTarget(provider=provider, key=key, endpoint=endpoint)


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


async def _call_openai(model_id: str, endpoint: OpenAIEndpoint, prompt: str, system: str | None, temperature: float | None, key: str) -> tuple[str, object]:
    messages = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict = {"model": endpoint.model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    _apply_output_budget(payload, model_id)
    async with httpx.AsyncClient(timeout=_request_timeout(model_id)) as client:
        resp = await client.post(
            f"{endpoint.base_url}/chat/completions",
            headers=auth_headers(key),
            json=payload,
        )
        _raise_for_status(resp)
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
    target = await _prepare_call(model_id, "text generation", source)
    if target.endpoint is not None:
        text, usage = await _call_openai(
            model_id, target.endpoint, prompt, system, temperature, target.key
        )
    else:
        text, usage = await _call_google(model_id, prompt, system, temperature, target.key)
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


def _google_generation_limits() -> dict:
    """Output ceiling, thinking budget and temperature for a structured call.

    None of these were ever set, so every structured agent ran at the provider
    defaults: no output cap (see _apply_output_budget for what that cost),
    dynamic thinking, and temperature 1.0. Thinking bills at output rates and
    on one measured session the synthesizer spent 83,471 thinking tokens at a
    median of 2,913 per call against a median visible output of 293 - roughly
    ten tokens of reasoning per token of answer, to pick operations from a
    fixed six-item vocabulary against a list it was handed.

    The budget is deliberately not zero. Answer detection - deciding whether a
    question was answered implicitly by something nobody said directly - is
    genuinely inferential and is this agent's highest-value output, so the
    default leaves room for it rather than optimizing it away unmeasured
    (ALP-296).

    Built per call rather than as a module constant so an operator override in
    settings takes effect without a restart, and returned as kwargs so a
    google-genai build that lacks one of these fails loudly at construction
    rather than silently ignoring it.
    """
    limits: dict = {}
    if settings.LLM_HOSTED_MAX_TOKENS > 0:
        limits["max_output_tokens"] = settings.LLM_HOSTED_MAX_TOKENS
    if settings.LLM_JSON_TEMPERATURE >= 0:
        limits["temperature"] = settings.LLM_JSON_TEMPERATURE
    if settings.LLM_JSON_THINKING_BUDGET >= 0:
        limits["thinking_config"] = types.ThinkingConfig(
            thinking_budget=settings.LLM_JSON_THINKING_BUDGET
        )
    return limits


def _google_retry_generation_limits() -> dict:
    """Limits for the retry after a structured call came back unparseable.

    The retry used to reuse the first attempt's ceiling verbatim, which is the
    one thing guaranteed not to help when the reason for the retry was that the
    ceiling truncated the JSON mid-string. A measured 35-minute Gemini call hit
    the 8192 ceiling twice, both times the synthesizer, both times producing
    "Unterminated string"; those retries happened to fit on the second pass but
    nothing made that likely, and a response that genuinely needed the room
    would have truncated twice and lost the cycle outright.

    Widening only on the retry keeps the cap doing its job on the common path -
    the runaway this bounds reached 63,192 tokens uncapped - while giving the
    uncommon legitimately-long answer somewhere to land.
    """
    limits = _google_generation_limits()
    ceiling = limits.get("max_output_tokens")
    if ceiling:
        limits["max_output_tokens"] = int(ceiling * settings.LLM_JSON_RETRY_HEADROOM)
    return limits


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
                **_google_generation_limits(),
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
            types.GenerateContentConfig(
                response_mime_type="application/json",
                **_google_retry_generation_limits(),
            ),
        )
    except TypeError:
        response = await call(contract, None)
    return _parse_google_response(response, response_schema)


# OpenAI-shaped servers disagree on which response_format shapes they accept:
# LM Studio requires json_schema or text and rejects json_object outright, while
# other builds only know json_object. Negotiate by walking these in order and
# remember the winner per base URL, so the cost is one rejected call per server
# rather than one per request. The JSON contract is in the prompt either way, so
# the "text" fallback still returns parseable output.
_JSON_MODES = ("json_schema", "json_object", "text")
_json_mode_by_base_url: dict[str, str] = {}


def _response_format(mode: str, response_schema: type[BaseModel]) -> dict | None:
    if mode == "json_object":
        return {"type": "json_object"}
    if mode == "json_schema":
        # "strict" is deliberately omitted: it demands every property be
        # required with additionalProperties false, which these schemas (all
        # optional fields with defaults) do not satisfy.
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema.__name__,
                "schema": response_schema.model_json_schema(),
            },
        }
    return None


def _rejects_response_format(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code not in (400, 404, 422):
        return False
    return "response_format" in (exc.response.text or "").lower()


# A completion budget is only safe relative to a context window we cannot see:
# prompt plus max_tokens must fit, and the briefing arbiter's prompt carries
# both lens documents. Asking for too much is refused outright, so start at the
# configured budget and halve on refusal, remembering what fit per base URL.
_MIN_OUTPUT_BUDGET = 1024
_json_budget_by_base_url: dict[str, int] = {}


# Whether this server accepted the optional generation limits below. Assumed
# yes until one is rejected, then remembered, so the cost of a server that does
# not take them is one refused call rather than one per request - the same
# shape as _json_mode_by_base_url and _json_budget_by_base_url above.
_json_generation_limits_by_base_url: dict[str, bool] = {}


def _openai_generation_limits(model_id: str, reasoning_effort: str | None) -> dict:
    """Temperature and reasoning budget for an OpenAI-shaped structured call.

    The Google path gets these from _google_generation_limits. Without the same
    treatment here, moving the analysis agents from Gemini to OpenAI would
    silently revert ALP-296: the reasoning budget would go back to the
    provider default and no temperature would be sent at all, so the change
    would look like a provider difference rather than a lost setting.

    Self-hosted servers are left alone. They are the ones most likely to reject
    an unknown field outright, they are already negotiated hard by the mode and
    budget loops, and their operators set their own sampling.

    An explicit reasoning_effort from the caller always wins - briefing_synthesis
    raises the arbiter deliberately, and a global default must not quietly
    lower it (ALP-296).
    """
    if _is_self_hosted(model_id):
        return {}
    limits: dict = {}
    effort = reasoning_effort or settings.LLM_JSON_REASONING_EFFORT
    if effort:
        limits["reasoning_effort"] = effort
    if settings.LLM_JSON_TEMPERATURE >= 0:
        limits["temperature"] = settings.LLM_JSON_TEMPERATURE
    return limits


def _rejects_generation_limits(exc: httpx.HTTPStatusError) -> bool:
    """Whether a failure is the server refusing temperature or reasoning_effort.

    Reasoning models commonly reject a non-default temperature, and models
    without a reasoning mode reject reasoning_effort. Either way the request is
    recoverable by dropping the optional fields, unlike a context overflow.
    """
    if exc.response.status_code not in (400, 404, 422):
        return False
    text = (exc.response.text or "").lower()
    if "unsupported parameter" in text or "unrecognized" in text:
        # Covers the completion-budget field name as well. Providers rename
        # these (max_tokens became max_completion_tokens on newer OpenAI
        # models), and a request refused purely over a field name should
        # degrade to one without the optional fields rather than fail a cycle.
        return True
    return any(term in text for term in ("temperature", "reasoning_effort", "reasoning"))


def _rejects_output_budget(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code not in (400, 413, 422):
        return False
    text = (exc.response.text or "").lower()
    return any(
        term in text
        for term in ("context", "max_tokens", "too long", "too large", "exceed")
    )


def _raise_for_status(resp: httpx.Response) -> None:
    """raise_for_status, but keep the server's explanation.

    httpx's own message names only the status and the URL, so the reason the
    call failed is thrown away exactly when it is most needed. That is what
    reduced a context-window refusal to a bare "HTTP 400" in the briefing.
    """
    if resp.is_success:
        return
    detail = (resp.text or "").strip()
    raise httpx.HTTPStatusError(
        f"HTTP {resp.status_code} from {resp.request.url}"
        + (f": {detail[:400]}" if detail else ""),
        request=resp.request,
        response=resp,
    )


async def _openai_json(
    model_id: str,
    endpoint: OpenAIEndpoint,
    prompt: str,
    response_schema: type[BaseModel],
    schema_hint: str,
    key: str,
    session_id,
    source: str,
    reasoning_effort: str | None,
):
    contract = _contract_prompt(prompt, schema_hint)

    async def post(messages: list[dict], mode: str) -> str:
        payload: dict = {"model": endpoint.model, "messages": messages}
        if _json_generation_limits_by_base_url.get(endpoint.base_url, True):
            payload.update(_openai_generation_limits(model_id, reasoning_effort))
        elif reasoning_effort is not None:
            # This server refused the optional limits, but an explicit caller
            # value is a deliberate choice rather than a default, so it still
            # goes out and fails loudly if it is genuinely unsupported.
            payload["reasoning_effort"] = reasoning_effort
        response_format = _response_format(mode, response_schema)
        if response_format is not None:
            payload["response_format"] = response_format
        _apply_output_budget(payload, model_id, _json_budget_by_base_url.get(endpoint.base_url))
        async with httpx.AsyncClient(timeout=_request_timeout(model_id)) as client:
            resp = await client.post(
                f"{endpoint.base_url}/chat/completions",
                headers=auth_headers(key),
                json=payload,
            )
            _raise_for_status(resp)
            data = resp.json()
        await record_token_usage(session_id, source, model_id, data.get("usage"))
        if _truncated(data):
            # Say why the JSON will not parse. Retrying cannot help: the model
            # will hit the same ceiling again.
            raise LLMReplyTruncated(model_id, source)
        return data["choices"][0]["message"]["content"] or ""

    async def _post_within_budget(messages: list[dict], mode: str) -> str:
        """post(), shrinking the completion budget until the server accepts it."""
        while True:
            try:
                return await post(messages, mode)
            except httpx.HTTPStatusError as exc:
                if _json_generation_limits_by_base_url.get(
                    endpoint.base_url, True
                ) and _rejects_generation_limits(exc):
                    _json_generation_limits_by_base_url[endpoint.base_url] = False
                    logger.info(
                        "%s refused the optional generation limits; retrying without them",
                        endpoint.base_url,
                    )
                    continue
                current = _json_budget_by_base_url.get(
                    endpoint.base_url, settings.LLM_SELF_HOSTED_MAX_TOKENS
                )
                if (
                    not _is_self_hosted(model_id)
                    or not _rejects_output_budget(exc)
                    or current <= _MIN_OUTPUT_BUDGET
                ):
                    raise
                reduced = max(_MIN_OUTPUT_BUDGET, current // 2)
                _json_budget_by_base_url[endpoint.base_url] = reduced
                logger.info(
                    "%s refused a %s-token completion budget; retrying at %s",
                    endpoint.base_url,
                    current,
                    reduced,
                )

    async def call(messages: list[dict]) -> str:
        start = _json_mode_by_base_url.get(endpoint.base_url, _JSON_MODES[0])
        candidates = _JSON_MODES[_JSON_MODES.index(start):]
        for mode in candidates:
            try:
                text = await _post_within_budget(messages, mode)
            except httpx.HTTPStatusError as exc:
                if not _rejects_response_format(exc) or mode == candidates[-1]:
                    raise
                logger.info(
                    "%s rejected response_format '%s'; falling back", endpoint.base_url, mode
                )
                continue
            if _json_mode_by_base_url.get(endpoint.base_url) != mode:
                _json_mode_by_base_url[endpoint.base_url] = mode
                logger.info("Using response_format '%s' for %s", mode, endpoint.base_url)
            return text
        raise RuntimeError("unreachable: response_format negotiation exhausted")

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
    reasoning_effort: str | None = None,
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
    target = await _prepare_call(model_id, "structured generation", source)
    hint = schema_hint or _default_schema_hint(response_schema)
    if target.endpoint is not None:
        return await _openai_json(
            model_id,
            target.endpoint,
            prompt,
            response_schema,
            hint,
            target.key,
            session_id,
            source,
            reasoning_effort,
        )
    return await _google_json(
        model_id, prompt, response_schema, hint, target.key, session_id, source
    )

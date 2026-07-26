"""Map LLM provider client errors to actionable messages.

Routers that call the provider-routed LLM helpers should catch
PROVIDER_ERROR_TYPES and re-raise via provider_error_to_http() so quota,
auth, and transport failures surface as clean 429/502 responses with a
user-readable remedy instead of unhandled 500s. Background paths (agent
loops, briefing synthesis) that persist status strings or write log lines
instead of raising should use provider_error_message() for the same
actionable text without the HTTP wrapper. The tuple is deliberately
narrow: programming errors (TypeError, KeyError, ...) must keep surfacing
as 500s.
"""

import logging

import httpx
from fastapi import HTTPException
from google.genai import errors as genai_errors

logger = logging.getLogger(__name__)

# google-genai wraps API failures in APIError (ClientError/ServerError);
# the OpenAI text path calls the HTTP API with httpx directly, so its
# rate-limit/auth failures arrive as httpx.HTTPStatusError and transport
# failures as other httpx.HTTPError subclasses.
PROVIDER_ERROR_TYPES = (genai_errors.APIError, httpx.HTTPError)

_LABELS = {
    "google": "Gemini",
    "openai": "OpenAI",
    "openai-compatible": "OpenAI-compatible endpoint",
}
_KEY_NAMES = {
    "google": "Google",
    "openai": "OpenAI",
    "openai-compatible": "OpenAI-compatible endpoint",
}

_QUOTA_REMEDIES = {
    "google": (
        "Gemini quota exhausted: the Google project hit its rate limit or "
        "monthly spending cap. Raise the cap in Google AI Studio "
        "(https://ai.studio/spend) or switch the model or provider in Admin."
    ),
    "openai": (
        "OpenAI quota exhausted: the account hit its rate limit or spending "
        "cap. Check usage and billing at https://platform.openai.com/usage "
        "or switch the model or provider in Admin."
    ),
}


def _short_message(exc: Exception) -> str:
    if isinstance(exc, genai_errors.APIError):
        text = exc.message or str(exc)
    elif isinstance(exc, httpx.HTTPStatusError):
        try:
            text = exc.response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            text = f"HTTP {exc.response.status_code}"
    else:
        text = str(exc) or type(exc).__name__
    text = " ".join(str(text).split())
    return text if len(text) <= 300 else text[:297] + "..."


def _status_of(exc: Exception) -> int | None:
    if isinstance(exc, genai_errors.APIError):
        return exc.code
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _is_auth_error(exc: Exception, status: int | None) -> bool:
    if status in (401, 403):
        return True
    if isinstance(exc, genai_errors.APIError):
        # Google reports a bad key as 400 INVALID_ARGUMENT "API key not
        # valid", not as a 401.
        if (exc.status or "") in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            return True
        return "api key" in (exc.message or "").lower()
    return False


def _is_quota_error(exc: Exception, status: int | None) -> bool:
    resource_exhausted = (
        isinstance(exc, genai_errors.APIError)
        and (exc.status or "") == "RESOURCE_EXHAUSTED"
    )
    return status == 429 or resource_exhausted


def provider_error_message(provider: str, exc: Exception) -> str:
    """Short actionable description of a provider failure.

    For background paths that surface failures as persisted status strings
    or log lines (briefing synthesis, strategic signals, agent loops)
    rather than HTTP responses.
    """
    label = _LABELS.get(provider, provider or "provider")
    status = _status_of(exc)

    if _is_quota_error(exc, status):
        return _QUOTA_REMEDIES.get(provider) or (
            f"{label} quota exhausted: {_short_message(exc)} "
            "Switch the model or provider in Admin."
        )

    if _is_auth_error(exc, status):
        key_name = _KEY_NAMES.get(provider, provider)
        return (
            f"{label} rejected the API key ({_short_message(exc)}). "
            f"Update the {key_name} key in Admin -> Connections."
        )

    return f"{label} error: {_short_message(exc)}"


def provider_error_to_http(
    provider: str,
    exc: Exception,
    context: str = "LLM call failed",
) -> HTTPException:
    """Translate a provider/client exception into an actionable HTTPException.

    Callers catch PROVIDER_ERROR_TYPES and raise the returned exception;
    exceptions outside that tuple should stay unhandled so genuine bugs
    still produce 500s.
    """
    label = _LABELS.get(provider, provider or "provider")
    status = _status_of(exc)
    logger.warning("%s: %s provider error (HTTP %s): %s", context, label, status, exc)

    detail = provider_error_message(provider, exc)
    if _is_quota_error(exc, status):
        return HTTPException(429, detail)
    if _is_auth_error(exc, status):
        return HTTPException(502, detail)
    return HTTPException(502, f"{context}: {detail}")

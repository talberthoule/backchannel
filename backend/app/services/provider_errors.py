"""Map LLM provider client errors to actionable HTTPExceptions.

Routers that call the provider-routed LLM helpers should catch
PROVIDER_ERROR_TYPES and re-raise via provider_error_to_http() so quota,
auth, and transport failures surface as clean 429/502 responses with a
user-readable remedy instead of unhandled 500s. The tuple is deliberately
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

_LABELS = {"google": "Gemini", "openai": "OpenAI"}
_KEY_NAMES = {"google": "Google", "openai": "OpenAI"}

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

    resource_exhausted = (
        isinstance(exc, genai_errors.APIError)
        and (exc.status or "") == "RESOURCE_EXHAUSTED"
    )
    if status == 429 or resource_exhausted:
        detail = _QUOTA_REMEDIES.get(provider) or (
            f"{label} quota exhausted: {_short_message(exc)} "
            "Switch the model or provider in Admin."
        )
        return HTTPException(429, detail)

    if _is_auth_error(exc, status):
        key_name = _KEY_NAMES.get(provider, provider)
        return HTTPException(
            502,
            f"{label} rejected the API key ({_short_message(exc)}). "
            f"Update the {key_name} key in Admin -> API Keys.",
        )

    return HTTPException(502, f"{context}: {label} error: {_short_message(exc)}")

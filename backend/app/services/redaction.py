"""Keep provider secrets out of log lines and user-facing messages.

Two layers, applied together by ``redact_text``:

- Known values. Every plaintext key that passes through ``services.secrets``
  (a decrypted credential row, an environment fallback, a custom endpoint key,
  the master key itself) is registered here, and any text carrying one of them
  verbatim is scrubbed. This is what catches a key that a provider SDK or a
  future code path embeds in an exception message or a request URL.
- Shapes. Bearer tokens, ``x-goog-api-key`` headers, key-shaped query
  parameters, URL userinfo, and the published key prefixes (``AIza...``,
  ``sk-...``) are masked even when the value was never registered - a key typed
  into a probe form, or one arriving from another process.

Registration is deliberately conservative: a value shorter than 16 characters
or equal to a known endpoint slug is left to the shape patterns, because
scrubbing a short everyday word verbatim (a self-hosted server whose "key" is
``lm-studio``) would eat every ``endpoint:lm-studio:model`` log line.

``install_log_redaction`` swaps the process-wide LogRecord factory so every
handler - the root stream, the desktop file log, uvicorn's own error logger -
formats through the scrubber. Attaching a Filter to the root handlers would
miss records that uvicorn's non-propagating loggers write with their own
handlers, and a record factory has no such gap.
"""

from __future__ import annotations

import logging
import re
import threading

REDACTED = "[redacted]"

# Shorter values are too likely to be ordinary words to scrub blindly; they
# stay covered by the header and bearer shapes below.
MIN_REGISTERED_LENGTH = 16

_known: set[str] = set()
_exempt: set[str] = set()
_lock = threading.Lock()

_VALUE_CHARS = r"[^\s'\",;&]+"
_TOKEN_CHARS = r"[A-Za-z0-9._~+/=-]"
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "Bearer <token>", whatever its length: the word itself marks a credential.
    (re.compile(rf"(?i)\bbearer\s+{_VALUE_CHARS}"), f"Bearer {REDACTED}"),
    # The genai ephemeral form "Token auth_tokens/...". Plain prose uses the
    # word "token" constantly, so this one keeps a length floor.
    (re.compile(rf"(?i)\b(token)\s+({_TOKEN_CHARS}{{16,}})"), rf"\1 {REDACTED}"),
    # Header or key/value spellings: x-goog-api-key: v, api_key=v,
    # "api-key": "v", Authorization: Bearer v.
    (
        re.compile(
            rf"(?i)\b(x-goog-api-key|api[-_]?key|authorization)"
            rf"(['\"]?\s*[:=]\s*['\"]?)((?:bearer\s+)?{_VALUE_CHARS})"
        ),
        rf"\1\2{REDACTED}",
    ),
    # Query parameters that carry credentials.
    (
        re.compile(r"(?i)([?&](?:key|api[-_]?key|apikey|token|access_token|secret)=)([^&\s'\"]+)"),
        rf"\1{REDACTED}",
    ),
    # URL userinfo: https://user:password@host
    (re.compile(r"(?i)(https?://)([^/\s@:]+):([^/\s@]+)@"), rf"\1{REDACTED}@"),
    # Published key prefixes.
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), REDACTED),
)


def register_secret(value: str | bytes | None, *, min_length: int = MIN_REGISTERED_LENGTH) -> None:
    """Remember a plaintext secret so any later text carrying it is scrubbed.

    ``min_length`` exists for the PII vault, whose values (a name, a phone
    number) are shorter than any credential yet must never reach a log.
    """
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    if not value:
        return
    value = value.strip()
    if len(value) < min_length:
        return
    with _lock:
        if value in _exempt:
            return
        _known.add(value)


def exempt_from_redaction(value: str | None) -> None:
    """Mark an identifier (an endpoint slug) that must never be scrubbed.

    A user may reuse the same word as an endpoint's name and its key; the name
    appears in every model id and log line, so it wins.
    """
    if not value:
        return
    value = value.strip()
    if not value:
        return
    with _lock:
        _exempt.add(value)
        _known.discard(value)


def clear_registered_secrets() -> None:
    """Forget every registered and exempted value (tests)."""
    with _lock:
        _known.clear()
        _exempt.clear()


def registered_secret_count() -> int:
    with _lock:
        return len(_known)


def redact_text(text: str | None) -> str:
    """Return ``text`` with every known or key-shaped secret masked."""
    if not text:
        return "" if text is None else text
    result = str(text)
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for value in known:
        if value in result:
            result = result.replace(value, REDACTED)
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _safe_redact(text: str) -> str:
    try:
        return redact_text(text)
    except Exception:  # noqa: BLE001 - a scrubber must never take the log line down with it
        return REDACTED


class RedactingLogRecord(logging.LogRecord):
    """LogRecord whose formatted message, exception text, and stack info are scrubbed.

    ``Formatter.format`` reads the message through ``getMessage()`` and caches
    exception text on ``exc_text``; routing both through the scrubber means
    every handler in the process sees clean text without being configured.
    """

    def getMessage(self) -> str:  # noqa: N802 - logging API
        return _safe_redact(super().getMessage())

    @property
    def exc_text(self) -> str | None:
        return self.__dict__.get("_exc_text")

    @exc_text.setter
    def exc_text(self, value: str | None) -> None:
        self.__dict__["_exc_text"] = _safe_redact(value) if value else value

    @property
    def stack_info(self) -> str | None:
        return self.__dict__.get("_stack_info")

    @stack_info.setter
    def stack_info(self, value: str | None) -> None:
        self.__dict__["_stack_info"] = _safe_redact(value) if value else value


class SecretRedactionFilter(logging.Filter):
    """Handler-level scrubber for loggers configured outside this process's factory.

    The record factory covers everything created after installation; this
    filter exists for tests and for any handler that wants belt-and-braces
    coverage of records built before ``install_log_redaction`` ran.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            message = str(record.msg)
        record.msg = _safe_redact(message)
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _safe_redact(record.exc_text)
        if record.stack_info:
            record.stack_info = _safe_redact(record.stack_info)
        return True


_installed = False


def install_log_redaction() -> None:
    """Make every LogRecord in the process scrub itself. Idempotent."""
    global _installed
    if _installed:
        return
    current = logging.getLogRecordFactory()
    if current is logging.LogRecord:
        logging.setLogRecordFactory(RedactingLogRecord)
    else:
        # Someone else installed a factory first; wrap rather than replace it.
        def factory(*args, **kwargs):
            record = current(*args, **kwargs)
            record.__class__ = type(
                "RedactingLogRecord", (RedactingLogRecord, record.__class__), {}
            )
            for attr in ("exc_text", "stack_info"):
                value = record.__dict__.pop(attr, None)
                setattr(record, attr, value)
            return record

        logging.setLogRecordFactory(factory)
    _installed = True

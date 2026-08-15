"""Best-effort persistence and aggregation for provider usage counts.

Named for tokens because that is what almost every provider reports, but the
unit is whatever the provider bills in. OpenAI Realtime transcription bills by
audio duration and reports ``{"type": "duration", "seconds": N}``; before
ALP-300 that shape matched no known field and was discarded, so an agent that
cost real money showed nothing at all on the cost page.
"""

import logging
import uuid
from typing import Any, Iterable

from app.database import async_session
from app.models import TokenUsage

logger = logging.getLogger(__name__)

_INPUT_FIELDS = ("prompt_token_count", "prompt_tokens", "input_tokens")
_OUTPUT_FIELDS = (
    "candidates_token_count",
    "response_token_count",
    "completion_tokens",
    "output_tokens",
)
_TOTAL_FIELDS = ("total_token_count", "total_tokens")
# Reasoning tokens are reported apart from the visible completion but bill at
# output rates, so they have to be counted separately or the cost estimate is
# wrong. Gemini reports thoughts_token_count at the top level; OpenAI-shaped
# servers nest reasoning_tokens under completion_tokens_details.
_THINKING_FIELDS = ("thoughts_token_count", "reasoning_tokens")
_THINKING_DETAIL_FIELDS = ("completion_tokens_details", "output_tokens_details")
# Audio duration, for models billed per minute instead of per token. OpenAI
# Realtime reports "seconds" on the transcription-completed event; the other
# spellings are defensive against sibling shapes.
_DURATION_FIELDS = ("seconds", "audio_duration_seconds", "duration_seconds")
_warned_usage_sources: set[str] = set()


def _value(usage: Any, *names: str) -> int | None:
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if value is not None:
            return max(0, int(value))
    return None


def _attr(usage: Any, name: str) -> Any:
    return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)


def _thinking_value(usage: Any) -> int | None:
    """Reasoning tokens, whether reported flat (Gemini) or nested (OpenAI)."""
    direct = _value(usage, *_THINKING_FIELDS)
    if direct is not None:
        return direct
    for name in _THINKING_DETAIL_FIELDS:
        details = _attr(usage, name)
        if details is not None:
            nested = _value(details, *_THINKING_FIELDS)
            if nested is not None:
                return nested
    return None


def _seconds_value(usage: Any) -> float | None:
    """Audio duration, kept as a float: segments are seldom whole seconds and
    truncating each one would lose minutes across a long call."""
    for name in _DURATION_FIELDS:
        value = _attr(usage, name)
        if value is None:
            continue
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return None


def _has_known_field(usage: Any) -> bool:
    fields = _INPUT_FIELDS + _OUTPUT_FIELDS + _TOTAL_FIELDS + _THINKING_FIELDS + _DURATION_FIELDS
    if isinstance(usage, dict):
        if any(field in usage for field in fields):
            return True
    elif any(getattr(usage, field, None) is not None for field in fields):
        return True
    return any(_attr(usage, name) is not None for name in _THINKING_DETAIL_FIELDS)


def normalize_usage(usage: Any, source: str = "") -> tuple[int, int, int, int, float] | None:
    """Return (input, output, thinking, total, audio_seconds), or None when
    nothing is usable.

    The tuple grew a fifth field for duration-billed models; callers that only
    read the token counts can keep indexing 0..3 unchanged.
    """
    if usage is None:
        return None
    input_tokens = _value(usage, *_INPUT_FIELDS) or 0
    output_tokens = _value(usage, *_OUTPUT_FIELDS) or 0
    thinking_tokens = _thinking_value(usage) or 0
    total_tokens = _value(usage, *_TOTAL_FIELDS)
    audio_seconds = _seconds_value(usage) or 0.0
    # A reported total already counts thinking; only a synthesized one has to add it.
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens + thinking_tokens
    if input_tokens == output_tokens == thinking_tokens == total_tokens == 0 and audio_seconds == 0.0:
        if source and not _has_known_field(usage) and source not in _warned_usage_sources:
            _warned_usage_sources.add(source)
            logger.warning(
                "Dropped unrecognized token usage for source %s (%s)",
                source,
                type(usage).__name__,
            )
        return None
    return input_tokens, output_tokens, thinking_tokens, total_tokens, audio_seconds


async def record_token_usage(
    session_id: uuid.UUID | str | None,
    source: str,
    model_id: str,
    usage: Any,
) -> None:
    try:
        normalized = normalize_usage(usage, source)
        if session_id is None or normalized is None:
            return
        async with async_session() as db:
            db.add(TokenUsage(
                session_id=uuid.UUID(str(session_id)),
                source=source,
                model_id=model_id,
                input_tokens=normalized[0],
                output_tokens=normalized[1],
                thinking_tokens=normalized[2],
                total_tokens=normalized[3],
                audio_seconds=normalized[4],
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record token usage for %s", source)


_ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "total_tokens": 0, "audio_seconds": 0.0}


def summarize_usage(rows: Iterable[TokenUsage]) -> dict:
    total = dict(_ZERO_USAGE)
    sources: dict[tuple[str, str], dict] = {}
    models: dict[str, dict] = {}
    for row in rows:
        values = {
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            # Rows written before the column existed read as NULL, not 0.
            "thinking_tokens": getattr(row, "thinking_tokens", 0) or 0,
            "total_tokens": row.total_tokens,
            "audio_seconds": getattr(row, "audio_seconds", 0.0) or 0.0,
        }
        for key, value in values.items():
            total[key] += value
        source = sources.setdefault(
            (row.source, row.model_id),
            {"source": row.source, "model_id": row.model_id, **_ZERO_USAGE},
        )
        model = models.setdefault(row.model_id, {"model_id": row.model_id, **_ZERO_USAGE})
        for key, value in values.items():
            source[key] += value
            model[key] += value
    # Ordered by tokens, which says nothing about a duration-billed row's
    # cost. Deliberately left that way: seconds and tokens cannot be ranked
    # against each other, and the only meaningful common axis is money, which
    # is applied at display time. The UI re-sorts by estimated cost.
    return {
        **total,
        "by_source": sorted(sources.values(), key=lambda item: (-item["total_tokens"], item["source"])),
        "by_model": sorted(models.values(), key=lambda item: (-item["total_tokens"], item["model_id"])),
    }

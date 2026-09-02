"""Best-effort persistence and aggregation for provider usage counts.

Named for tokens because that is what almost every provider reports, but the
unit is whatever the provider bills in. OpenAI Realtime transcription bills by
audio duration and reports ``{"type": "duration", "seconds": N}``; before
ALP-300 that shape matched no known field and was discarded, so an agent that
cost real money showed nothing at all on the cost page.

Not every input token costs the same either. Providers bill cached prompt
tokens at a fraction of the text rate (Gemini implicit caching reports them in
``cached_content_token_count``, OpenAI under ``prompt_tokens_details``), and
audio tokens at a multiple of it (Gemini breaks the prompt down per modality in
``prompt_tokens_details``, OpenAI reports ``audio_tokens``). Both counts are
subsets of the input total. They are recorded alongside it so the cost estimate
can price each slice at its own published rate instead of pricing a live
audio gateway, whose input is almost entirely audio, at the text rate.
"""

import logging
import uuid
from typing import Any, Iterable, NamedTuple

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
# Cached prompt tokens. Gemini reports them flat; OpenAI nests cached_tokens
# under the input details object (prompt_tokens_details on chat completions,
# input_tokens_details on the Responses API).
_CACHED_FIELDS = ("cached_content_token_count",)
_CACHED_DETAIL_FIELDS = ("cached_tokens",)
# OpenAI-shaped per-slice detail containers. Gemini reuses the name
# prompt_tokens_details for something else: a LIST of per-modality counts, so
# the readers below check the shape rather than trusting the name.
_INPUT_DETAIL_FIELDS = ("prompt_tokens_details", "input_tokens_details", "input_token_details")
_OUTPUT_DETAIL_FIELDS = ("completion_tokens_details", "output_tokens_details", "output_token_details")
_AUDIO_DETAIL_FIELDS = ("audio_tokens",)
# Gemini per-modality breakdowns: generate_content reports
# candidates_tokens_details, the Live API response_tokens_details.
_GEMINI_INPUT_MODALITY_FIELDS = ("prompt_tokens_details",)
_GEMINI_OUTPUT_MODALITY_FIELDS = ("candidates_tokens_details", "response_tokens_details")
_AUDIO_MODALITY = "AUDIO"
_warned_usage_sources: set[str] = set()


class UsageCounts(NamedTuple):
    """One provider response, normalized.

    A tuple so the original positional readers keep working; the trailing
    fields are subsets of the ones before them, never additions: cached and
    audio input tokens are part of input_tokens, audio output tokens part of
    output_tokens. Summing them into a total double-counts.
    """

    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int
    audio_seconds: float
    cached_input_tokens: int = 0
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0


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


def _detail_value(usage: Any, containers: tuple[str, ...], *names: str) -> int | None:
    """A count nested in an OpenAI-shaped details object (dict or attributes).

    A list under the same name is a Gemini modality breakdown, which
    _modality_tokens reads instead; it is skipped here rather than mistaken
    for a details object.
    """
    for container in containers:
        details = _attr(usage, container)
        if details is None or isinstance(details, (list, tuple)):
            continue
        value = _value(details, *names)
        if value is not None:
            return value
    return None


def _modality_name(entry: Any) -> str:
    """AUDIO from MediaModality.AUDIO, "AUDIO", or "MediaModality.AUDIO"."""
    modality = _attr(entry, "modality")
    if modality is None:
        return ""
    label = getattr(modality, "value", modality)
    return str(label).upper().rsplit(".", 1)[-1]


def _modality_tokens(usage: Any, containers: tuple[str, ...], modality: str) -> int | None:
    """Tokens of one modality from a Gemini per-modality breakdown list."""
    total: int | None = None
    for container in containers:
        details = _attr(usage, container)
        if not isinstance(details, (list, tuple)):
            continue
        for entry in details:
            if _modality_name(entry) != modality:
                continue
            count = _value(entry, "token_count")
            if count is None:
                continue
            total = (total or 0) + count
    return total


def _cached_input_value(usage: Any) -> int | None:
    direct = _value(usage, *_CACHED_FIELDS)
    if direct is not None:
        return direct
    return _detail_value(usage, _INPUT_DETAIL_FIELDS, *_CACHED_DETAIL_FIELDS)


def _audio_input_value(usage: Any) -> int | None:
    by_modality = _modality_tokens(usage, _GEMINI_INPUT_MODALITY_FIELDS, _AUDIO_MODALITY)
    if by_modality is not None:
        return by_modality
    return _detail_value(usage, _INPUT_DETAIL_FIELDS, *_AUDIO_DETAIL_FIELDS)


def _audio_output_value(usage: Any) -> int | None:
    by_modality = _modality_tokens(usage, _GEMINI_OUTPUT_MODALITY_FIELDS, _AUDIO_MODALITY)
    if by_modality is not None:
        return by_modality
    return _detail_value(usage, _OUTPUT_DETAIL_FIELDS, *_AUDIO_DETAIL_FIELDS)


def _has_known_field(usage: Any) -> bool:
    fields = _INPUT_FIELDS + _OUTPUT_FIELDS + _TOTAL_FIELDS + _THINKING_FIELDS + _DURATION_FIELDS
    if isinstance(usage, dict):
        if any(field in usage for field in fields):
            return True
    elif any(getattr(usage, field, None) is not None for field in fields):
        return True
    return any(_attr(usage, name) is not None for name in _THINKING_DETAIL_FIELDS)


def normalize_usage(usage: Any, source: str = "") -> UsageCounts | None:
    """Return UsageCounts, or None when nothing is usable.

    The result is a tuple whose first five fields are (input, output,
    thinking, total, audio_seconds); callers that only read the token counts
    can keep indexing 0..3 unchanged. The cached and audio slices that follow
    are clamped to the totals they are part of - and cached plus audio input
    to the input count together - so a provider quirk can never report or
    price more cached or audio tokens than there were input tokens.
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
    cached_input = min(input_tokens, _cached_input_value(usage) or 0)
    # Jointly, not just per side: cached and audio are both slices of the same
    # input count, so together they can never exceed it. Cached wins the
    # tokens, mirroring the cost formula in frontend/src/lib/modelPricing.ts,
    # so the stored row and the priced row agree.
    audio_input = min(input_tokens - cached_input, _audio_input_value(usage) or 0)
    audio_output = min(output_tokens, _audio_output_value(usage) or 0)
    return UsageCounts(
        input_tokens,
        output_tokens,
        thinking_tokens,
        total_tokens,
        audio_seconds,
        cached_input,
        audio_input,
        audio_output,
    )


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
                input_tokens=normalized.input_tokens,
                output_tokens=normalized.output_tokens,
                thinking_tokens=normalized.thinking_tokens,
                total_tokens=normalized.total_tokens,
                audio_seconds=normalized.audio_seconds,
                cached_input_tokens=normalized.cached_input_tokens,
                audio_input_tokens=normalized.audio_input_tokens,
                audio_output_tokens=normalized.audio_output_tokens,
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record token usage for %s", source)


_ZERO_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "thinking_tokens": 0,
    "total_tokens": 0,
    "audio_seconds": 0.0,
    "cached_input_tokens": 0,
    "audio_input_tokens": 0,
    "audio_output_tokens": 0,
}


def summarize_usage(rows: Iterable[TokenUsage]) -> dict:
    total = dict(_ZERO_USAGE)
    sources: dict[tuple[str, str], dict] = {}
    models: dict[str, dict] = {}
    for row in rows:
        values = {
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            # Rows written before a column existed read as NULL, not 0.
            "thinking_tokens": getattr(row, "thinking_tokens", 0) or 0,
            "total_tokens": row.total_tokens,
            "audio_seconds": getattr(row, "audio_seconds", 0.0) or 0.0,
            "cached_input_tokens": getattr(row, "cached_input_tokens", 0) or 0,
            "audio_input_tokens": getattr(row, "audio_input_tokens", 0) or 0,
            "audio_output_tokens": getattr(row, "audio_output_tokens", 0) or 0,
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

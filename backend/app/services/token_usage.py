"""Best-effort persistence and aggregation for provider token counts."""

import logging
import uuid
from typing import Any, Iterable

from app.database import async_session
from app.models import TokenUsage

logger = logging.getLogger(__name__)


def _value(usage: Any, *names: str) -> int | None:
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if value is not None:
            return max(0, int(value))
    return None


def normalize_usage(usage: Any) -> tuple[int, int, int] | None:
    if usage is None:
        return None
    input_tokens = _value(usage, "prompt_token_count", "prompt_tokens", "input_tokens") or 0
    output_tokens = _value(usage, "candidates_token_count", "completion_tokens", "output_tokens") or 0
    total_tokens = _value(usage, "total_token_count", "total_tokens")
    total_tokens = input_tokens + output_tokens if total_tokens is None else total_tokens
    if input_tokens == output_tokens == total_tokens == 0:
        return None
    return input_tokens, output_tokens, total_tokens


async def record_token_usage(
    session_id: uuid.UUID | str | None,
    source: str,
    model_id: str,
    usage: Any,
) -> None:
    try:
        normalized = normalize_usage(usage)
        if session_id is None or normalized is None:
            return
        async with async_session() as db:
            db.add(TokenUsage(
                session_id=uuid.UUID(str(session_id)),
                source=source,
                model_id=model_id,
                input_tokens=normalized[0],
                output_tokens=normalized[1],
                total_tokens=normalized[2],
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record token usage for %s", source)


def summarize_usage(rows: Iterable[TokenUsage]) -> dict:
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    sources: dict[tuple[str, str], dict] = {}
    models: dict[str, dict] = {}
    for row in rows:
        values = {
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "total_tokens": row.total_tokens,
        }
        for key, value in values.items():
            total[key] += value
        source = sources.setdefault(
            (row.source, row.model_id),
            {"source": row.source, "model_id": row.model_id, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        model = models.setdefault(
            row.model_id,
            {"model_id": row.model_id, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        for key, value in values.items():
            source[key] += value
            model[key] += value
    return {
        **total,
        "by_source": sorted(sources.values(), key=lambda item: (-item["total_tokens"], item["source"])),
        "by_model": sorted(models.values(), key=lambda item: (-item["total_tokens"], item["model_id"])),
    }

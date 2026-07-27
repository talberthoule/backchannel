"""Runtime selection helpers for speaker diarization backends."""

import math
from typing import Final

from app.services.diarization_diagnostics import SORTFORMER_RTF_THRESHOLD

DIARIZER_LIGHTWEIGHT: Final = "lightweight"
DIARIZER_SORTFORMER: Final = "sortformer"
SUPPORTED_DIARIZER_MODES: Final = {DIARIZER_LIGHTWEIGHT, DIARIZER_SORTFORMER}


def normalize_diarizer_mode(value: str | None) -> str:
    if value in SUPPORTED_DIARIZER_MODES:
        return value
    return DIARIZER_LIGHTWEIGHT


def sortformer_is_selectable(
    benchmark_status: str | None,
    sortformer_available: bool,
    benchmark_real_time_factor: float | None,
) -> bool:
    return (
        sortformer_available
        and benchmark_status == "passed"
        and benchmark_real_time_factor is not None
        and math.isfinite(benchmark_real_time_factor)
        and 0 < benchmark_real_time_factor <= SORTFORMER_RTF_THRESHOLD
    )


def resolve_effective_diarizer_mode(
    selected_mode: str | None,
    benchmark_status: str | None,
    sortformer_available: bool,
    benchmark_real_time_factor: float | None,
) -> str:
    normalized = normalize_diarizer_mode(selected_mode)
    if normalized != DIARIZER_SORTFORMER:
        return DIARIZER_LIGHTWEIGHT
    if sortformer_is_selectable(
        benchmark_status,
        sortformer_available,
        benchmark_real_time_factor,
    ):
        return DIARIZER_SORTFORMER
    return DIARIZER_LIGHTWEIGHT


def flush_diarizer_segments(diarizer) -> list:
    batch_flush = getattr(diarizer, "flush_segments", None)
    if callable(batch_flush):
        return list(batch_flush())

    single = diarizer.flush()
    return [single] if single else []

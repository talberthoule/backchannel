import math
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.diarization_diagnostics import (
    BenchmarkResult,
    SortformerEnvironment,
    describe_benchmark_headroom,
    probe_sortformer_environment,
)
from app.services.diarizer_selection import (
    DIARIZER_LIGHTWEIGHT,
    DIARIZER_SORTFORMER,
    normalize_diarizer_mode,
    resolve_effective_diarizer_mode,
    sortformer_is_selectable,
)

SETTING_SELECTED_DIARIZER = "diarization.selected_live_diarizer"
SETTING_SORTFORMER_BENCHMARK_STATUS = "diarization.sortformer.benchmark_status"
SETTING_SORTFORMER_BENCHMARK_RTF = "diarization.sortformer.real_time_factor"
SETTING_SORTFORMER_BENCHMARK_CONTENTION_RTF = (
    "diarization.sortformer.contention_adjusted_real_time_factor"
)
SETTING_SORTFORMER_BENCHMARK_PEAK_MEMORY_MB = (
    "diarization.sortformer.peak_memory_mb"
)
SETTING_SPEAKER_SIMILARITY_THRESHOLD = "diarization.speaker_similarity_threshold"
MIN_SPEAKER_SIMILARITY_THRESHOLD = 0.5
MAX_SPEAKER_SIMILARITY_THRESHOLD = 0.95


@dataclass(frozen=True)
class DiarizerRuntimeConfig:
    selected_live_diarizer: str
    effective_live_diarizer: str
    sortformer_selectable: bool
    benchmark_status: str
    benchmark_real_time_factor: float | None
    benchmark_contention_adjusted_real_time_factor: float | None
    benchmark_peak_memory_mb: float | None
    speaker_similarity_threshold: float
    selection_reason: str

    def to_dict(self) -> dict:
        return {
            "selected_live_diarizer": self.selected_live_diarizer,
            "effective_live_diarizer": self.effective_live_diarizer,
            "sortformer_selectable": self.sortformer_selectable,
            "benchmark_status": self.benchmark_status,
            "benchmark_real_time_factor": self.benchmark_real_time_factor,
            "benchmark_contention_adjusted_real_time_factor": (
                self.benchmark_contention_adjusted_real_time_factor
            ),
            "benchmark_peak_memory_mb": self.benchmark_peak_memory_mb,
            "speaker_similarity_threshold": self.speaker_similarity_threshold,
            "selection_reason": self.selection_reason,
        }


async def get_diarizer_runtime_config(
    db: AsyncSession,
    environment: SortformerEnvironment | None = None,
    probe_sortformer: bool = True,
) -> DiarizerRuntimeConfig:
    selected = normalize_diarizer_mode(
        await get_app_setting(db, SETTING_SELECTED_DIARIZER, settings.LIVE_DIARIZER)
    )
    if environment is None:
        if probe_sortformer or selected != DIARIZER_LIGHTWEIGHT:
            environment = probe_sortformer_environment()
        else:
            environment = SortformerEnvironment(
                torch_available=False,
                sortformer_available=False,
                cuda_available=False,
                device="cpu",
                gpu_name=None,
                gpu_memory_gb=None,
                model_id="",
                status="not_probed",
                recommended_live_diarizer=DIARIZER_LIGHTWEIGHT,
                reason=(
                    "Lightweight diarization is active; Enhanced availability was not probed "
                    "for this request."
                ),
            )
    benchmark_status = await get_app_setting(db, SETTING_SORTFORMER_BENCHMARK_STATUS, "")
    rtf = _parse_float(await get_app_setting(db, SETTING_SORTFORMER_BENCHMARK_RTF, ""))
    contention_rtf = _parse_float(
        await get_app_setting(db, SETTING_SORTFORMER_BENCHMARK_CONTENTION_RTF, "")
    )
    peak_memory_mb = _parse_float(
        await get_app_setting(db, SETTING_SORTFORMER_BENCHMARK_PEAK_MEMORY_MB, "")
    )
    threshold = _parse_threshold(
        await get_app_setting(db, SETTING_SPEAKER_SIMILARITY_THRESHOLD, str(settings.SPEAKER_SIMILARITY_THRESHOLD))
    )
    selectable = sortformer_is_selectable(
        benchmark_status,
        environment.sortformer_available,
        rtf,
    )
    effective = resolve_effective_diarizer_mode(
        selected,
        benchmark_status,
        environment.sortformer_available,
        rtf,
    )

    return DiarizerRuntimeConfig(
        selected_live_diarizer=selected,
        effective_live_diarizer=effective,
        sortformer_selectable=selectable,
        benchmark_status=benchmark_status,
        benchmark_real_time_factor=rtf,
        benchmark_contention_adjusted_real_time_factor=contention_rtf,
        benchmark_peak_memory_mb=peak_memory_mb,
        speaker_similarity_threshold=threshold,
        selection_reason=_selection_reason(
            selected,
            effective,
            selectable,
            environment.reason,
            rtf,
        ),
    )


async def set_selected_diarizer(db: AsyncSession, selected_mode: str) -> DiarizerRuntimeConfig:
    selected = normalize_diarizer_mode(selected_mode)
    environment = probe_sortformer_environment()
    benchmark_status = await get_app_setting(db, SETTING_SORTFORMER_BENCHMARK_STATUS, "")
    rtf = _parse_float(
        await get_app_setting(db, SETTING_SORTFORMER_BENCHMARK_RTF, "")
    )

    if selected == DIARIZER_SORTFORMER and not sortformer_is_selectable(
        benchmark_status,
        environment.sortformer_available,
        rtf,
    ):
        raise ValueError("Sortformer can be selected after a passing benchmark on this machine.")

    await set_app_setting(db, SETTING_SELECTED_DIARIZER, selected)
    await db.commit()
    return await get_diarizer_runtime_config(db, environment=environment)


async def record_sortformer_benchmark(db: AsyncSession, result: BenchmarkResult) -> None:
    await set_app_setting(db, SETTING_SORTFORMER_BENCHMARK_STATUS, result.status)
    # A non-finite RTF (inf marks an unmeasurable benchmark) must never be
    # persisted: it is not JSON-serializable in diagnostics responses. Clear
    # any stale value instead so the stored RTF matches the stored status.
    rtf = result.real_time_factor
    await set_app_setting(
        db,
        SETTING_SORTFORMER_BENCHMARK_RTF,
        str(rtf) if math.isfinite(rtf) else "",
    )
    contention_rtf = result.contention_adjusted_real_time_factor
    await set_app_setting(
        db,
        SETTING_SORTFORMER_BENCHMARK_CONTENTION_RTF,
        str(contention_rtf) if math.isfinite(contention_rtf) else "",
    )
    previous_peak_memory_mb = _parse_float(
        await get_app_setting(db, SETTING_SORTFORMER_BENCHMARK_PEAK_MEMORY_MB, "")
    )
    peak_candidates = [
        value
        for value in (previous_peak_memory_mb, result.peak_memory_mb)
        if value is not None and math.isfinite(value)
    ]
    peak_memory_mb = max(peak_candidates) if peak_candidates else None
    await set_app_setting(
        db,
        SETTING_SORTFORMER_BENCHMARK_PEAK_MEMORY_MB,
        str(peak_memory_mb)
        if peak_memory_mb is not None and math.isfinite(peak_memory_mb)
        else "",
    )
    await db.commit()


async def set_speaker_similarity_threshold(
    db: AsyncSession,
    threshold: float,
    environment: SortformerEnvironment | None = None,
) -> DiarizerRuntimeConfig:
    if threshold < MIN_SPEAKER_SIMILARITY_THRESHOLD or threshold > MAX_SPEAKER_SIMILARITY_THRESHOLD:
        raise ValueError(
            "Speaker similarity threshold must be between "
            f"{MIN_SPEAKER_SIMILARITY_THRESHOLD:.2f} and {MAX_SPEAKER_SIMILARITY_THRESHOLD:.2f}."
        )

    normalized = round(threshold, 2)
    await set_app_setting(db, SETTING_SPEAKER_SIMILARITY_THRESHOLD, f"{normalized:.2f}")
    await db.commit()
    return await get_diarizer_runtime_config(db, environment=environment)


def _selection_reason(
    selected: str,
    effective: str,
    selectable: bool,
    environment_reason: str,
    benchmark_real_time_factor: float | None,
) -> str:
    benchmark_reason = (
        describe_benchmark_headroom(
            benchmark_real_time_factor,
            passed=True,
        )
        if selectable and benchmark_real_time_factor is not None
        else ""
    )
    if effective == DIARIZER_SORTFORMER:
        return (
            "Enhanced Sortformer diarization is active for new live calls and audio imports. "
            f"{benchmark_reason}"
        )
    if selectable:
        return (
            "Enhanced Sortformer diarization is unlocked. "
            f"{benchmark_reason}"
        )
    if selected == DIARIZER_SORTFORMER and not selectable:
        if benchmark_real_time_factor is not None:
            return (
                "Enhanced Sortformer is selected, but the saved benchmark no longer "
                "meets the dual-track requirement. Lightweight diarization is active. "
                f"{describe_benchmark_headroom(benchmark_real_time_factor, passed=False)}"
            )
        return "Sortformer is selected, but the runtime is using the lightweight fallback until a benchmark passes."
    return environment_reason or "Lightweight diarization is active."


def _parse_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    # Databases written before non-finite RTFs were rejected may hold "inf";
    # treat those like an absent value so diagnostics stay serializable.
    return parsed if math.isfinite(parsed) else None


def _parse_threshold(value: str) -> float:
    parsed = _parse_float(value)
    if parsed is None:
        return settings.SPEAKER_SIMILARITY_THRESHOLD
    if parsed < MIN_SPEAKER_SIMILARITY_THRESHOLD or parsed > MAX_SPEAKER_SIMILARITY_THRESHOLD:
        return settings.SPEAKER_SIMILARITY_THRESHOLD
    return parsed

"""Call-start capacity admission (ALP-156, first wiring increment).

This assembles the measured demands that are actually available at call start,
runs the pure planner (`capacity_planner.plan_capacity`), and returns a verdict
with measured headroom - the "measured, not boolean" surface the design calls
for.

Scope of this increment, stated honestly because the whole point of ALP-156 is
not to present partial coverage as a complete answer:

* Diarization is modelled from the ALP-155 benchmark's persisted per-track
  contention-adjusted RTF and per-instance peak memory, but only when the
  effective live diarizer is Sortformer (the case that OOM-killed the call on
  2026-07-27). The lightweight diarizer is not separately benchmarked, so it is
  reported as unmodelled rather than guessed at.
* The machine budget (usable cores, container memory limit) is detected here.
* Batch ASR, the live captioner, and the text agents are NOT yet modelled,
  because their measurements are not persisted (the local fit test recomputes
  and stores nothing) and no served-model context length is captured anywhere.
  They are listed in `not_modelled` so a consumer never reads this as a complete
  clean pass. Wiring them in is the next increment, once those measurements are
  made available.

Because coverage is partial, an `over_budget` verdict here is definitive (even
the modelled subset exceeds the machine), but an `ok`/`thin` verdict must be read
together with `not_modelled`: unmeasured components can only push demand up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.capacity_planner import (
    CapacityVerdict,
    DiarizationDemand,
    MachineBudget,
    plan_capacity,
)
from app.services.diarizer_runtime import get_diarizer_runtime_config
from app.services.diarizer_selection import DIARIZER_SORTFORMER


# Leave at least this many cores for the event loop, WebSocket I/O, the database
# driver, and the OS; the audio and model stack gets the rest.
CPU_RESERVE_CORES = 1.0
# Fallback container memory limit when no cgroup limit is readable (e.g. a
# native dev backend on Windows/macOS). Deliberately modest so the fallback
# errs toward caution rather than promising memory that may not exist.
DEFAULT_MEMORY_LIMIT_MB = 4096.0
# A cgroup limit at or above this is the kernel's "unlimited" sentinel, not a
# real cap.
_UNLIMITED_MEMORY_BYTES = 1 << 50


def _container_memory_limit_mb() -> float | None:
    """The container/cgroup memory limit in MB, or None when unlimited/unknown.

    Reads cgroup v2 (`memory.max`) then v1 (`memory.limit_in_bytes`). A value of
    "max" or a kernel unlimited sentinel reads as no limit.
    """

    candidates = (
        ("/sys/fs/cgroup/memory.max", True),
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes", False),
    )
    for path, allow_max_keyword in candidates:
        try:
            raw = Path(path).read_text().strip()
        except OSError:
            continue
        if allow_max_keyword and raw == "max":
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        if value <= 0 or value >= _UNLIMITED_MEMORY_BYTES:
            return None
        return value / (1024 ** 2)
    return None


def detect_machine_budget(memory_limit_mb: float | None = None) -> MachineBudget:
    """Detect the machine's usable budget for the audio and model stack.

    Cores come from `os.cpu_count()` minus CPU_RESERVE_CORES; the memory limit
    comes from the cgroup limit, falling back to a modest default when none is
    readable.
    """

    total_cores = os.cpu_count() or 1
    usable_cores = max(1.0, float(total_cores) - CPU_RESERVE_CORES)
    if memory_limit_mb is None:
        memory_limit_mb = _container_memory_limit_mb()
    if memory_limit_mb is None or memory_limit_mb <= 0:
        memory_limit_mb = DEFAULT_MEMORY_LIMIT_MB
    return MachineBudget(usable_cores=usable_cores, memory_limit_mb=memory_limit_mb)


@dataclass(frozen=True)
class CapacityAssessment:
    """A call-start verdict plus an explicit statement of what it covers."""

    verdict: CapacityVerdict
    track_count: int
    modelled: tuple[str, ...]
    not_modelled: tuple[str, ...]

    @property
    def partial(self) -> bool:
        return bool(self.not_modelled)

    def to_dict(self) -> dict:
        verdict = self.verdict
        return {
            "status": verdict.status,
            "admits": verdict.admits(),
            "partial": self.partial,
            "track_count": self.track_count,
            "cpu_budget_cores": round(verdict.cpu_budget_cores, 3),
            "cpu_demand_cores": round(verdict.cpu_demand_cores, 3),
            "cpu_headroom_cores": round(verdict.cpu_headroom_cores, 3),
            "cpu_load_multiple": (
                None if verdict.cpu_load_multiple == float("inf") else round(verdict.cpu_load_multiple, 3)
            ),
            "memory_limit_mb": round(verdict.memory_limit_mb, 1),
            "memory_demand_mb": round(verdict.memory_demand_mb, 1),
            "memory_headroom_mb": round(verdict.memory_headroom_mb, 1),
            "reasons": list(verdict.reasons),
            "degradation_plan": list(verdict.degradation_plan),
            "role_fits": [
                {
                    "role": fit.role,
                    "context_fits": fit.context_fits,
                    "latency_fits": fit.latency_fits,
                    "needed_context_tokens": fit.needed_context_tokens,
                    "context_window": fit.context_window,
                }
                for fit in verdict.role_fits
            ],
            "modelled": list(self.modelled),
            "not_modelled": list(self.not_modelled),
        }


# Components not yet fed into the numeric verdict in this first increment. Named
# explicitly so a consumer cannot mistake a partial pass for a complete one.
_NOT_MODELLED_BASE = (
    "batch_asr: real-time factor not persisted; run the local fit test",
    "live_captioner: real-time factor not persisted; run the local fit test",
    "text_agents: served-model tokens/sec and context window are not captured",
)


async def assess_call_capacity(
    db: AsyncSession,
    track_count: int = 2,
    budget: MachineBudget | None = None,
) -> CapacityAssessment:
    """Assess whether the configured live call fits this machine's budget.

    track_count defaults to 2 (mic plus system audio) because dual-track is the
    load-multiplying default and the conservative case; a mic-only caller passes
    track_count=1.
    """

    if budget is None:
        budget = detect_machine_budget()

    diarizer = await get_diarizer_runtime_config(db)

    diarization: DiarizationDemand | None = None
    modelled: list[str] = ["machine_budget"]
    not_modelled = list(_NOT_MODELLED_BASE)

    if diarizer.effective_live_diarizer == DIARIZER_SORTFORMER:
        if (
            diarizer.benchmark_contention_adjusted_real_time_factor is not None
            and diarizer.benchmark_peak_memory_mb is not None
        ):
            diarization = DiarizationDemand(
                track_count=track_count,
                per_track_rtf=diarizer.benchmark_contention_adjusted_real_time_factor,
                per_instance_memory_mb=diarizer.benchmark_peak_memory_mb,
            )
            modelled.append("diarization_sortformer")
        else:
            not_modelled.append(
                "diarization: the Sortformer benchmark is stale; re-run it to "
                "capture contention and memory"
            )
    else:
        not_modelled.append(
            "diarization: the lightweight diarizer is not separately benchmarked"
        )

    verdict = plan_capacity(budget, diarization=diarization)
    return CapacityAssessment(
        verdict=verdict,
        track_count=track_count,
        modelled=tuple(modelled),
        not_modelled=tuple(not_modelled),
    )

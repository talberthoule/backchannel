"""Call-start capacity admission (ALP-156).

Assembles every demand backed by a persisted measurement, then names any
configured local component that remains unmeasured. Partial coverage can never
read as a complete clean pass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AgentConfig
from app.services import local_fit, transcription_runtime
from app.services.capacity_planner import (
    BatchAsrDemand,
    CapacityVerdict,
    CaptionerDemand,
    DiarizationDemand,
    MachineBudget,
    TextAgentDemand,
    plan_capacity,
)
from app.services.diarizer_runtime import get_diarizer_runtime_config
from app.services.diarizer_selection import DIARIZER_SORTFORMER
from app.services.local_live_captioner import LOCAL_LIVE_MODEL_MAP
from app.services.local_transcriber import LOCAL_MODEL_MAP


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


def detect_machine_budget(
    memory_limit_mb: float | None = None,
    cpu_reserve_cores: float = CPU_RESERVE_CORES,
) -> MachineBudget:
    """Detect the machine's usable budget for the audio and model stack.

    Cores come from `os.cpu_count()` minus a reserve; the memory limit comes from
    the cgroup limit, falling back to a modest default when none is readable.
    """

    total_cores = os.cpu_count() or 1
    usable_cores = max(1.0, float(total_cores) - max(0.0, cpu_reserve_cores))
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


_ROLES_BY_SLUG = {role.slug: role for role in local_fit.AGENT_ROLES}


def _positive_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _measured_asr_rtf(
    fit_result: dict,
    model_id: str,
    field: str,
) -> float | None:
    contention = _positive_number(fit_result.get("contention"))
    report = fit_result.get("asr")
    if contention is None or not isinstance(report, dict):
        return None
    models = report.get("asr_models")
    if not isinstance(models, list):
        return None
    measured = next(
        (
            model
            for model in models
            if isinstance(model, dict)
            and model.get("model_id") == model_id
            and model.get("status") == "ok"
        ),
        None,
    )
    value = _positive_number(measured.get(field)) if measured else None
    return (
        local_fit.effective_latency(value, contention)
        if value is not None
        else None
    )


def _measured_text_latency(
    fit_result: dict,
    model_id: str,
    slug: str,
) -> float | None:
    contention = _positive_number(fit_result.get("contention"))
    if contention is None:
        return None
    models = fit_result.get("text_models")
    if not isinstance(models, list):
        return None
    measured = next(
        (
            model
            for model in models
            if isinstance(model, dict)
            and model.get("model_id") == model_id
            and model.get("status") == "ok"
        ),
        None,
    )
    roles = measured.get("roles") if measured else None
    if not isinstance(roles, list):
        return None
    role = next(
        (
            item
            for item in roles
            if isinstance(item, dict) and item.get("slug") == slug
        ),
        None,
    )
    latency = _positive_number(role.get("latency_seconds")) if role else None
    return (
        local_fit.effective_latency(latency, contention)
        if latency is not None
        else None
    )


def _effective_interval(row: AgentConfig, default: int) -> int | None:
    return (
        local_fit.parse_model_intervals(row.model_intervals).get(row.model_id)
        or row.interval_seconds
        or default
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
    runtime = await transcription_runtime.get_transcription_runtime_config(db)
    fit_result = await local_fit.load_local_fit_result(db) or {}
    agent_rows = list(
        (
            await db.execute(select(AgentConfig).order_by(AgentConfig.display_order))
        ).scalars().all()
    )
    agents = {row.slug: row for row in agent_rows}
    local_text_model_ids = {
        model["id"]
        for model in await local_fit.local_text_models(db)
        if model.get("id")
    }

    diarization: DiarizationDemand | None = None
    batch_asr: BatchAsrDemand | None = None
    captioner: CaptionerDemand | None = None
    text_agents: list[TextAgentDemand] = []
    modelled: list[str] = ["machine_budget"]
    not_modelled: list[str] = []

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

    batch_model_id = runtime.batch_model_id
    if batch_model_id in LOCAL_MODEL_MAP:
        measured_rtf = _measured_asr_rtf(
            fit_result,
            batch_model_id,
            "real_time_factor",
        )
        if measured_rtf is None:
            not_modelled.append(
                f"batch_asr:{batch_model_id}: run the local fit test for this model"
            )
        else:
            batch_asr = BatchAsrDemand(real_time_factor=measured_rtf)
            modelled.append(f"batch_asr:{batch_model_id}")

    gateway = agents.get(transcription_runtime.AUDIO_GATEWAY_SLUG)
    live_model_id = runtime.live_preview_model_id
    if (
        gateway is not None
        and gateway.enabled
        and live_model_id in LOCAL_LIVE_MODEL_MAP
    ):
        live_asr_model_id = LOCAL_LIVE_MODEL_MAP[live_model_id]
        measured_rtf = _measured_asr_rtf(
            fit_result,
            live_asr_model_id,
            "short_real_time_factor",
        )
        if measured_rtf is None:
            not_modelled.append(
                f"live_captioner:{live_model_id}: run the local fit test "
                "for live-caption feasibility"
            )
        else:
            captioner = CaptionerDemand(real_time_factor=measured_rtf)
            modelled.append(f"live_captioner:{live_model_id}")

    output_budget = settings.LLM_SELF_HOSTED_MAX_TOKENS
    for row in agent_rows:
        role = _ROLES_BY_SLUG.get(row.slug)
        if (
            not row.enabled
            or role is None
            or row.model_id not in local_text_model_ids
        ):
            continue
        latency = _measured_text_latency(fit_result, row.model_id, row.slug)
        if latency is None or output_budget <= 0:
            not_modelled.append(
                f"text_agent:{row.slug}: run the local fit test for "
                f"{row.model_id}"
            )
            continue
        interval = 0 if role.post_call else _effective_interval(
            row,
            role.default_interval,
        )
        if not role.post_call and not interval:
            not_modelled.append(
                f"text_agent:{row.slug}: no effective cycle interval is configured"
            )
            continue

        # TextAgentDemand expresses latency through a token rate. Deriving that
        # rate from the ALP-154 output bound makes projected_call_seconds equal
        # the measured end-to-end latency without inventing a prompt size.
        text_agents.append(
            TextAgentDemand(
                role=row.slug,
                prompt_tokens=0,
                reserved_output_tokens=output_budget,
                tokens_per_second=output_budget / latency,
                context_window=None,
                interval_seconds=float(interval or 0),
                timeout_seconds=settings.LLM_SELF_HOSTED_TIMEOUT_SECONDS,
                one_shot=role.post_call,
            )
        )
        modelled.append(f"text_agent:{row.slug}")
        not_modelled.append(
            f"text_agent:{row.slug}: served-model context window is not captured"
        )

    verdict = plan_capacity(
        budget,
        diarization=diarization,
        batch_asr=batch_asr,
        captioner=captioner,
        text_agents=text_agents,
    )
    return CapacityAssessment(
        verdict=verdict,
        track_count=track_count,
        modelled=tuple(modelled),
        not_modelled=tuple(not_modelled),
    )

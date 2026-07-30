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
from app.services import fit_staleness, local_fit, transcription_runtime
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
    # Inputs that were modelled but carry a caveat. Aged measurements land here
    # rather than in not_modelled: they are still this machine's numbers, so
    # they annotate the verdict instead of degrading it (ALP-160 5.2).
    annotations: tuple[str, ...] = ()

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
            "annotations": list(self.annotations),
        }


_ROLES_BY_SLUG = {role.slug: role for role in local_fit.AGENT_ROLES}


def _positive_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


@dataclass(frozen=True)
class _Measured:
    """A measurement read, plus what the verdict must say about its validity.

    value is None whenever the number may not be modelled, so a caller that
    ignores the rest still fails closed. unusable carries the reason a stamped
    row was refused; aged carries the reason a row was accepted with a caveat.
    """

    value: float | None = None
    unusable: str = ""
    aged: str = ""


def _validity_of(measured: dict) -> _Measured:
    """Read one measurement's ALP-160 validity stamp.

    An invalid input is missing, not passing: Incompatible and Superseded
    describe a machine or a served model that is no longer the one in front of
    us, so modelling from those numbers would invent demand and round a gap up
    into a favorable verdict. Aged rows are still this machine's numbers, only
    old, so they stay admissible and annotate the verdict instead of degrading
    it. A row with no stamp predates ALP-160 and is left alone.
    """
    validity = measured.get("validity")
    if not isinstance(validity, dict):
        return _Measured()
    status = validity.get("status")
    reason = validity.get("reason") or ""
    if status in (fit_staleness.INCOMPATIBLE, fit_staleness.SUPERSEDED):
        return _Measured(unusable=reason or status)
    if status == fit_staleness.AGED:
        return _Measured(aged=reason or "measured a while ago")
    return _Measured()


def _measured_asr_rtf(
    fit_result: dict,
    model_id: str,
    field: str,
) -> _Measured:
    contention = _positive_number(fit_result.get("contention"))
    report = fit_result.get("asr")
    if contention is None or not isinstance(report, dict):
        return _Measured()
    models = report.get("asr_models")
    if not isinstance(models, list):
        return _Measured()
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
    if measured is None:
        return _Measured()
    validity = _validity_of(measured)
    if validity.unusable:
        return validity
    value = _positive_number(measured.get(field))
    if value is None:
        return _Measured()
    return _Measured(
        value=local_fit.effective_latency(value, contention),
        aged=validity.aged,
    )


def _measured_text_latency(
    fit_result: dict,
    model_id: str,
    slug: str,
) -> _Measured:
    contention = _positive_number(fit_result.get("contention"))
    if contention is None:
        return _Measured()
    models = fit_result.get("text_models")
    if not isinstance(models, list):
        return _Measured()
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
    if measured is None:
        return _Measured()
    validity = _validity_of(measured)
    if validity.unusable:
        return validity
    roles = measured.get("roles")
    if not isinstance(roles, list):
        return _Measured()
    role = next(
        (
            item
            for item in roles
            if isinstance(item, dict) and item.get("slug") == slug
        ),
        None,
    )
    latency = _positive_number(role.get("latency_seconds")) if role else None
    if latency is None:
        return _Measured()
    return _Measured(
        value=local_fit.effective_latency(latency, contention),
        aged=validity.aged,
    )


def _effective_interval(row: AgentConfig, default: int) -> int | None:
    return (
        local_fit.parse_model_intervals(row.model_intervals).get(row.model_id)
        or row.interval_seconds
        or default
    )


def _diarization_demand(
    diarizer,
    track_count: int,
) -> tuple[DiarizationDemand | None, list[str], list[str]]:
    modelled: list[str] = []
    not_modelled: list[str] = []

    # The diarizer in effect decides which message is honest. A machine on the
    # lightweight diarizer needs no Sortformer benchmark at all, so reporting
    # that its Sortformer record is incompatible would answer a question nobody
    # asked and bury the real one; the lightweight message wins there. Only when
    # Sortformer is actually in effect does the record's validity matter, and
    # then an invalid record is missing rather than passing (ALP-160 5.2).
    if diarizer.effective_live_diarizer != DIARIZER_SORTFORMER:
        not_modelled.append(
            "diarization: the lightweight diarizer is not separately benchmarked"
        )
        return None, modelled, not_modelled
    if diarizer.benchmark_validity in ("incompatible", "superseded"):
        not_modelled.append(
            f"diarization: {diarizer.benchmark_validity_reason}"
        )
        return None, modelled, not_modelled

    # A record that survived the validity gate carries all three numbers:
    # ALP-160 classifies an incomplete one as incompatible, which the branch
    # above already caught. No completeness re-check is reachable here.
    demand = DiarizationDemand(
        track_count=track_count,
        per_track_rtf=diarizer.benchmark_contention_adjusted_real_time_factor,
        per_instance_memory_mb=diarizer.benchmark_peak_memory_mb,
    )
    modelled.append("diarization_sortformer")
    return demand, modelled, not_modelled


def _transcription_demands(
    fit_result: dict,
    runtime,
    agents: dict[str, AgentConfig],
) -> tuple[
    BatchAsrDemand | None,
    CaptionerDemand | None,
    list[str],
    list[str],
    list[str],
]:
    batch_asr: BatchAsrDemand | None = None
    captioner: CaptionerDemand | None = None
    modelled: list[str] = []
    not_modelled: list[str] = []
    annotations: list[str] = []

    batch_model_id = runtime.batch_model_id
    if batch_model_id in LOCAL_MODEL_MAP:
        measured_rtf = _measured_asr_rtf(
            fit_result,
            batch_model_id,
            "real_time_factor",
        )
        if measured_rtf.unusable:
            not_modelled.append(
                f"batch_asr:{batch_model_id}: {measured_rtf.unusable}"
            )
        elif measured_rtf.value is None:
            not_modelled.append(
                f"batch_asr:{batch_model_id}: run the local fit test for this model"
            )
        else:
            if measured_rtf.aged:
                annotations.append(
                    f"batch_asr:{batch_model_id}: {measured_rtf.aged}"
                )
            batch_asr = BatchAsrDemand(real_time_factor=measured_rtf.value)
            modelled.append(f"batch_asr:{batch_model_id}")
            not_modelled.append(
                f"batch_asr:{batch_model_id}: memory demand is not measured"
            )

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
        if measured_rtf.unusable:
            not_modelled.append(
                f"live_captioner:{live_model_id}: {measured_rtf.unusable}"
            )
        elif measured_rtf.value is None:
            not_modelled.append(
                f"live_captioner:{live_model_id}: run the local fit test "
                "for live-caption feasibility"
            )
        else:
            if measured_rtf.aged:
                annotations.append(
                    f"live_captioner:{live_model_id}: {measured_rtf.aged}"
                )
            captioner = CaptionerDemand(real_time_factor=measured_rtf.value)
            modelled.append(f"live_captioner:{live_model_id}")
            not_modelled.append(
                f"live_captioner:{live_model_id}: memory demand is not measured"
            )

    return batch_asr, captioner, modelled, not_modelled, annotations


def _text_agent_demands(
    fit_result: dict,
    agent_rows: list[AgentConfig],
    local_text_model_ids: set[str],
) -> tuple[list[TextAgentDemand], list[str], list[str], list[str]]:
    text_agents: list[TextAgentDemand] = []
    modelled: list[str] = []
    not_modelled: list[str] = []
    annotations: list[str] = []
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
        if latency.unusable:
            not_modelled.append(f"text_agent:{row.slug}: {latency.unusable}")
            continue
        if latency.value is None or output_budget <= 0:
            not_modelled.append(
                f"text_agent:{row.slug}: run the local fit test for "
                f"{row.model_id}"
            )
            continue
        if latency.aged:
            annotations.append(f"text_agent:{row.slug}: {latency.aged}")
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
                tokens_per_second=output_budget / latency.value,
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

    return text_agents, modelled, not_modelled, annotations


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

    diarization, diarization_modelled, diarization_not_modelled = (
        _diarization_demand(diarizer, track_count)
    )
    (
        batch_asr,
        captioner,
        transcription_modelled,
        transcription_not_modelled,
        transcription_annotations,
    ) = _transcription_demands(fit_result, runtime, agents)
    (
        text_agents,
        text_modelled,
        text_not_modelled,
        text_annotations,
    ) = _text_agent_demands(fit_result, agent_rows, local_text_model_ids)

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
        modelled=(
            "machine_budget",
            *diarization_modelled,
            *transcription_modelled,
            *text_modelled,
        ),
        not_modelled=(
            *diarization_not_modelled,
            *transcription_not_modelled,
            *text_not_modelled,
        ),
        annotations=(
            *transcription_annotations,
            *text_annotations,
        ),
    )

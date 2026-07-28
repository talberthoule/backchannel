"""Aggregate local resource budget: the pure planning core (ALP-156).

Nothing else in the app owns the machine's compute budget for a live call, so a
user can pass four independent gates on an idle machine and assemble a
configuration that cannot run (the 2026-07-27 OOM and briefing-timeout
incidents). This module is the call-start admission planner from the ALP-156
design: it reasons over the *whole* selected configuration and reports measured
headroom rather than a boolean.

It is deliberately pure. It imports nothing from the live audio path and touches
no I/O; it takes measured demands as inputs and returns a verdict. The wiring
that gathers those measurements (the ALP-155 diarization benchmark fields, the
local-fit ASR/caption/text numbers, the machine budget, and the per-role text
prompt sizes) and the runtime controller that acts on the degradation plan are
separate, deferred pieces. Keeping this core free of the bind-mounted runtime
lets it be unit-tested in isolation and reviewed on its own.

Design: docs/superpowers/specs/2026-07-27-aggregate-local-resource-budget-design.md

Two budget dimensions, because the two incidents were two different failures:

* Sustained CPU throughput, in a single currency of CPU-cores kept busy
  (CPU-seconds consumed per wall-clock second). Diarization is multiplied by
  track count; every active consumer sums against one budget.
* Peak resident memory of the in-process model stack against the container
  limit. Memory is modelled separately because a configuration can be fast
  enough and still exhaust memory, which is what actually OOM-killed the call;
  a latency-only model would miss it.

A third, per-role text-agent constraint is the served model's context window: if
a role's prompt plus its reserved output exceeds the context the model is served
with, the request is refused outright and the role cannot run at all. This is a
hard fit check, not a degradation, reported per agent role because the briefing
arbiter's prompt dwarfs a single lens (ALP-154, commit df9fc5c).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# How a consumer draws on the machine.
CONSUMER_IN_PROCESS = "in_process"        # backend thread pool + container memory (the OOM axis)
CONSUMER_LOCAL_OFF_PROCESS = "local_off_process"  # same machine, separate process (loopback endpoint)
CONSUMER_REMOTE = "remote"                # off-box (LAN or cloud): no local CPU or memory

# Verdict statuses.
STATUS_OK = "ok"
STATUS_THIN = "thin"
STATUS_OVER_BUDGET = "over_budget"


@dataclass(frozen=True)
class DegradationLever:
    """One step in the ratified degradation order (first sacrificed to last).

    The order is a product decision ratified 2026-07-27 (thoule and w2:pJ). Each
    lever names which budget it relieves so the runtime controller can apply the
    highest-in-order lever that relieves the *breached* budget, rather than
    whichever queue overflows first.
    """

    key: str
    label: str
    relieves_cpu: bool
    relieves_memory: bool
    protected: bool = False  # never shed to relieve budget


# Ratified order: live captions -> text-agent cadence -> diarization detail ->
# (protected) batch transcript -> (never) call liveness. Captions shed first
# because their content is reconstructed by batch ASR and dropping them relieves
# the exact in-process axis that OOM'd; call liveness is never sacrificed
# (ALP-153's floor).
DEGRADATION_ORDER: tuple[DegradationLever, ...] = (
    DegradationLever("live_captions", "Drop live interim captions", True, True),
    DegradationLever("text_agent_cadence", "Widen text-agent intervals", True, False),
    DegradationLever("diarization_detail", "Shed oldest diarization audio", True, True),
    DegradationLever("batch_transcript", "Protect the batch transcript", False, False, protected=True),
    DegradationLever("call_liveness", "Never sacrifice call liveness", False, False, protected=True),
)


@dataclass(frozen=True)
class MachineBudget:
    """The machine's usable budget for the audio and model stack.

    usable_cores is what is left for this stack after a reserve for the event
    loop, WebSocket I/O, database, and OS - not the full core count.
    memory_limit_mb is the container memory limit (Docker) or a machine-memory
    reserve (desktop). cpu_safety_factor keeps the plan below 100% of usable
    cores; thin_margin is the fraction of budget below which headroom is "thin".
    """

    usable_cores: float
    memory_limit_mb: float
    cpu_safety_factor: float = 0.85
    thin_margin: float = 0.15
    overhead_mb: float = 0.0


@dataclass(frozen=True)
class DiarizationDemand:
    """One diarizer per track. In-process (shares the backend thread pool).

    per_track_rtf is the contention-adjusted per-track real-time factor from the
    ALP-155 benchmark (raw * 1.5), i.e. CPU-seconds to diarize one second of one
    track's audio under a load reserve. per_instance_memory_mb is that
    benchmark's baseline-subtracted peak RSS delta. The planner multiplies both
    by track_count here; ALP-155 does no aggregate arithmetic itself.
    """

    track_count: int
    per_track_rtf: float
    per_instance_memory_mb: float | None = None

    def cpu_cores(self) -> float:
        return max(0, self.track_count) * max(0.0, self.per_track_rtf)

    def memory_mb(self) -> float:
        if self.per_instance_memory_mb is None:
            return 0.0
        return max(0, self.track_count) * max(0.0, self.per_instance_memory_mb)


@dataclass(frozen=True)
class BatchAsrDemand:
    """Batch ASR over diarized speech. In-process, bounded at max_concurrency.

    Load is the ASR real-time factor scaled by the fraction of wall-clock that is
    actually speech (VAD-derived). Bursty; the sustained average is what the
    budget reasons about and the controller absorbs the bursts.
    """

    real_time_factor: float
    speech_fraction: float = 0.6
    memory_mb: float | None = None
    max_concurrency: int = 3

    def cpu_cores(self) -> float:
        fraction = min(1.0, max(0.0, self.speech_fraction))
        return fraction * max(0.0, self.real_time_factor)

    def memory_mb_value(self) -> float:
        return 0.0 if self.memory_mb is None else max(0.0, self.memory_mb)


@dataclass(frozen=True)
class CaptionerDemand:
    """The local-parakeet-live on-device captioner. In-process, continuous.

    Set memory_mb to 0 when it shares cached weights with a Parakeet batch model
    that is already counted, so the footprint is not double-counted.
    """

    real_time_factor: float
    memory_mb: float | None = None
    enabled: bool = True

    def cpu_cores(self) -> float:
        return max(0.0, self.real_time_factor) if self.enabled else 0.0

    def memory_mb_value(self) -> float:
        if not self.enabled or self.memory_mb is None:
            return 0.0
        return max(0.0, self.memory_mb)


@dataclass(frozen=True)
class TextAgentDemand:
    """One text-agent role against a served model.

    Text inference is out-of-process for endpoint models: a loopback endpoint
    burns the same physical cores as the audio pipeline but not the backend
    thread pool, and a LAN/cloud endpoint is off-box entirely. So only
    location == CONSUMER_LOCAL_OFF_PROCESS contributes local CPU here.

    Three things are checked per role: sustained CPU (interval roles only),
    latency against the per-endpoint timeout (ALP-154), and the hard
    context-window fit. one_shot marks briefing roles that run once at call end
    rather than on an interval, so they add no sustained CPU but are still
    checked for latency and context fit.
    """

    role: str
    prompt_tokens: int
    reserved_output_tokens: int
    tokens_per_second: float
    context_window: int | None
    interval_seconds: float = 0.0
    location: str = CONSUMER_LOCAL_OFF_PROCESS
    timeout_seconds: float = 900.0
    one_shot: bool = False

    def projected_call_seconds(self) -> float:
        if self.tokens_per_second <= 0:
            return math.inf
        total_tokens = max(0, self.prompt_tokens) + max(0, self.reserved_output_tokens)
        return total_tokens / self.tokens_per_second

    def cpu_cores(self) -> float:
        if self.location != CONSUMER_LOCAL_OFF_PROCESS or self.one_shot:
            return 0.0
        if self.interval_seconds <= 0:
            return 0.0
        call_seconds = self.projected_call_seconds()
        if not math.isfinite(call_seconds):
            return 0.0
        return call_seconds / self.interval_seconds

    def needed_context_tokens(self) -> int:
        return max(0, self.prompt_tokens) + max(0, self.reserved_output_tokens)

    def context_fits(self) -> bool | None:
        if self.context_window is None:
            return None
        if self.context_window <= 0:
            return False
        return self.needed_context_tokens() <= self.context_window

    def latency_fits(self) -> bool:
        call_seconds = self.projected_call_seconds()
        if not math.isfinite(call_seconds):
            return False
        return call_seconds <= self.timeout_seconds


@dataclass(frozen=True)
class RoleFit:
    """The per-role text fit result surfaced to the user."""

    role: str
    needed_context_tokens: int
    context_window: int | None
    context_fits: bool | None
    projected_call_seconds: float
    timeout_seconds: float
    latency_fits: bool

    def shortfall(self) -> str | None:
        if self.context_fits is False:
            return (
                f"{self.role}: needs about {self.needed_context_tokens} tokens "
                f"against a {self.context_window}-token context - it will not fit "
                "and the request is refused outright"
            )
        if not self.latency_fits:
            return (
                f"{self.role}: a single call is projected at "
                f"{self.projected_call_seconds:.0f}s against a "
                f"{self.timeout_seconds:.0f}s timeout"
            )
        return None


@dataclass(frozen=True)
class CapacityVerdict:
    """The admission verdict: measured headroom, not a boolean.

    admits() is True unless the status is over_budget. An over_budget verdict is
    refuse-with-override (ratified 2026-07-27): the caller may start anyway, but
    the override must state the measured shortfall in reasons, per role where the
    failure is a role's context or latency.
    """

    status: str
    cpu_budget_cores: float
    cpu_demand_cores: float
    cpu_headroom_cores: float
    memory_limit_mb: float
    memory_demand_mb: float
    memory_headroom_mb: float
    role_fits: tuple[RoleFit, ...]
    reasons: tuple[str, ...]
    degradation_plan: tuple[str, ...]

    def admits(self) -> bool:
        return self.status != STATUS_OVER_BUDGET

    @property
    def cpu_load_multiple(self) -> float:
        if self.cpu_budget_cores <= 0:
            return math.inf
        return self.cpu_demand_cores / self.cpu_budget_cores


def plan_capacity(
    budget: MachineBudget,
    diarization: DiarizationDemand | None = None,
    batch_asr: BatchAsrDemand | None = None,
    captioner: CaptionerDemand | None = None,
    text_agents: Sequence[TextAgentDemand] = (),
) -> CapacityVerdict:
    """Reason over the whole selected configuration and report measured headroom.

    Sums in-process CPU and memory plus any local off-process text CPU against
    one budget, evaluates each text role's context and latency fit, and returns a
    verdict with the measured shortfall and the applicable degradation plan.
    """

    cpu_demand = 0.0
    memory_demand = max(0.0, budget.overhead_mb)

    if diarization is not None:
        cpu_demand += diarization.cpu_cores()
        memory_demand += diarization.memory_mb()
    if batch_asr is not None:
        cpu_demand += batch_asr.cpu_cores()
        memory_demand += batch_asr.memory_mb_value()
    if captioner is not None:
        cpu_demand += captioner.cpu_cores()
        memory_demand += captioner.memory_mb_value()
    for agent in text_agents:
        cpu_demand += agent.cpu_cores()

    cpu_budget = max(0.0, budget.usable_cores) * max(0.0, budget.cpu_safety_factor)
    cpu_headroom = cpu_budget - cpu_demand
    memory_headroom = budget.memory_limit_mb - memory_demand

    role_fits = tuple(
        RoleFit(
            role=agent.role,
            needed_context_tokens=agent.needed_context_tokens(),
            context_window=agent.context_window,
            context_fits=agent.context_fits(),
            projected_call_seconds=agent.projected_call_seconds(),
            timeout_seconds=agent.timeout_seconds,
            latency_fits=agent.latency_fits(),
        )
        for agent in text_agents
    )

    reasons: list[str] = []
    over_budget = False
    thin = False

    if cpu_headroom < 0:
        over_budget = True
        reasons.append(
            f"Projected sustained load is about {_safe_multiple(cpu_demand, cpu_budget):.1f}x "
            f"this machine's budget ({cpu_demand:.2f} of {cpu_budget:.2f} usable cores)."
        )
    elif cpu_headroom < budget.thin_margin * cpu_budget:
        thin = True
        reasons.append(
            f"CPU headroom is thin: {cpu_demand:.2f} of {cpu_budget:.2f} usable cores in use."
        )

    if memory_headroom < 0:
        over_budget = True
        reasons.append(
            f"Projected peak memory is about {memory_demand:.0f} MB against a "
            f"{budget.memory_limit_mb:.0f} MB limit."
        )
    elif memory_headroom < budget.thin_margin * budget.memory_limit_mb:
        thin = True
        reasons.append(
            f"Memory headroom is thin: about {memory_demand:.0f} MB of "
            f"{budget.memory_limit_mb:.0f} MB."
        )

    for fit in role_fits:
        shortfall = fit.shortfall()
        if shortfall is None:
            continue
        reasons.append(shortfall)
        if not fit.context_fits:
            over_budget = True  # a role that cannot fit is a hard admission failure
        else:
            thin = True  # a latency overrun is a warning, not a hard block

    if over_budget:
        status = STATUS_OVER_BUDGET
    elif thin:
        status = STATUS_THIN
    else:
        status = STATUS_OK

    plan = _degradation_plan(
        cpu_breached=cpu_headroom < budget.thin_margin * cpu_budget,
        memory_breached=memory_headroom < budget.thin_margin * budget.memory_limit_mb,
        captioner_active=captioner is not None and captioner.enabled,
        has_interval_text_agents=any(
            not a.one_shot and a.interval_seconds > 0 for a in text_agents
        ),
    )

    return CapacityVerdict(
        status=status,
        cpu_budget_cores=cpu_budget,
        cpu_demand_cores=cpu_demand,
        cpu_headroom_cores=cpu_headroom,
        memory_limit_mb=budget.memory_limit_mb,
        memory_demand_mb=memory_demand,
        memory_headroom_mb=memory_headroom,
        role_fits=role_fits,
        reasons=tuple(reasons),
        degradation_plan=plan,
    )


def _degradation_plan(
    *,
    cpu_breached: bool,
    memory_breached: bool,
    captioner_active: bool,
    has_interval_text_agents: bool,
) -> tuple[str, ...]:
    """The ordered, applicable relief levers for a breached budget.

    Only levers that relieve a breached budget and are actually available (a
    captioner that is on, interval text agents that exist) appear, in the
    ratified order. Protected levers are never returned.
    """

    if not (cpu_breached or memory_breached):
        return ()

    plan: list[str] = []
    for lever in DEGRADATION_ORDER:
        if lever.protected:
            continue
        relieves = (lever.relieves_cpu and cpu_breached) or (
            lever.relieves_memory and memory_breached
        )
        if not relieves:
            continue
        if lever.key == "live_captions" and not captioner_active:
            continue
        if lever.key == "text_agent_cadence" and not has_interval_text_agents:
            continue
        plan.append(lever.label)
    return tuple(plan)


def _safe_multiple(demand: float, budget: float) -> float:
    if budget <= 0:
        return math.inf
    return demand / budget

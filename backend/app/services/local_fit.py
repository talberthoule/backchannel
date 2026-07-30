"""Local Model Fit Test: can this machine keep up running analysis locally?

The signal here is keep-up SPEED only, never answer quality. Each live text
agent runs one provider call per cycle and must finish inside its cycle budget
(AgentConfig.interval_seconds) or it falls behind the conversation. This module
times a role-representative generate_text() call on each on-prem (self-hosted,
OpenAI-compatible) text model, scores every interval-driven agent against its
budget, and recommends a cycle interval that restores comfortable headroom.

Transcription keep-up (local ONNX ASR real-time factor) is a separate concern
tracked by the Diarization Capability card and ALP-144; this module is text
analysis only.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConfig
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.batch_transcriber import _audio_has_speech_energy
from app.services.custom_endpoints import endpoint_models
from app.services.diarization_diagnostics import probe_sortformer_environment
from app.services.fit_staleness import (
    INCOMPATIBLE,
    assess_fit_record,
    host_fingerprint,
    stamp_fit_record,
)
from app.services.llm import generate_text
from app.services.local_transcriber import LOCAL_MODEL_MAP, LocalTranscriber

logger = logging.getLogger(__name__)

# Verdicts, worst-to-best kept explicit so the UI and tests share one vocabulary.
GREEN = "green"
YELLOW = "yellow"
RED = "red"

# We want a cycle's call to finish within HEADROOM of its interval so a slow
# call, a retry, or a long transcript window never starves the next cycle.
HEADROOM = 0.5
# A live cycle shorter than this is pointless (setup dominates); longer than
# MAX_INTERVAL stops being "live" and should push the user to a lighter model.
MIN_INTERVAL = 5
MAX_INTERVAL = 180
# Recommended intervals round up to this step so the picker shows tidy numbers.
ROUND_STEP = 5

# Rough chars-per-token for the informational tokens/sec readout only; it never
# feeds a verdict, so a coarse constant is fine across tokenizers.
_CHARS_PER_TOKEN = 4

GenerateText = Callable[..., Awaitable[str]]


# A real call is busier than this idle benchmark (recording, diarization, other
# apps competing for CPU/RAM), so the fit screen scales measured latency by a
# contention factor before judging. 1.5x is a conservative default; the slider
# lets the user reserve more or less headroom.
DEFAULT_CONTENTION = 1.5
MIN_CONTENTION = 1.0
MAX_CONTENTION = 3.0

# Post-call briefing agents run once at call end, not on a live loop, so they are
# judged against an acceptable end-of-call wait rather than a cycle interval.
POST_CALL_GREEN_SECONDS = 60
POST_CALL_YELLOW_SECONDS = 180


@dataclass(frozen=True)
class AgentRole:
    """A text agent scored by the fit test and the prompt size it works over."""

    slug: str
    name: str
    prompt_profile: str  # "short" or "long"
    default_interval: int
    # Post-call agents (the briefing lenses) run once at call end, so they have
    # no live cycle budget and are judged on end-of-call wait instead.
    post_call: bool = False


# Interval-driven agents whose loops are latency-critical during a live call,
# plus the three post-call briefing agents (no live loop). default_interval
# mirrors seed_agents.SEED_CONFIGS for interval agents; for post-call agents it
# is the acceptable end-of-call wait. The audio bridge is not a text model, so
# it is not scored here.
AGENT_ROLES: tuple[AgentRole, ...] = (
    AgentRole("objection_handler", "Objection Handler", "short", 10),
    AgentRole("opportunity_specialist", "Opportunity Specialist", "short", 55),
    AgentRole("consolidated_analyst", "Consolidated Analyst", "long", 40),
    AgentRole("strategic_signals", "Strategic Signals", "long", 45),
    AgentRole("synthesizer", "Principal Agent", "long", 75),
    AgentRole("brief_meeting_lens", "Briefing Meeting Lens", "long", POST_CALL_GREEN_SECONDS, post_call=True),
    AgentRole("brief_discovery_lens", "Briefing Discovery Lens", "long", POST_CALL_GREEN_SECONDS, post_call=True),
    AgentRole("brief_arbiter", "Briefing Arbiter", "long", POST_CALL_GREEN_SECONDS, post_call=True),
)

_ROLES_BY_SLUG = {role.slug: role for role in AGENT_ROLES}
# Only interval-driven agents have a tunable cycle budget.
_INTERVAL_ROLES = tuple(role for role in AGENT_ROLES if not role.post_call)


def parse_model_intervals(raw: str) -> dict[str, int]:
    """Parse AgentConfig.model_intervals JSON into {model_id: interval}, tolerant
    of empty/garbage."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): int(v)
        for k, v in data.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }

# ~90 seconds of dialogue: the objection/opportunity fast-cycle window.
_SHORT_TRANSCRIPT = (
    "Rep: Thanks for making time today. How is the current rollout going on your side?\n"
    "Customer: Honestly it is behind. The team likes the product but procurement is nervous "
    "about the per-seat pricing, and our security lead has questions about data residency.\n"
    "Rep: Understood. On residency, everything can stay in your region. On pricing, we have a "
    "volume tier that usually helps at your headcount.\n"
    "Customer: That would help. The bigger blocker is that IT wants a self-hosted option so no "
    "call audio leaves our network. Is that realistic this quarter?\n"
    "Rep: It is. Let me show you the on-prem path and what it needs from your side.\n"
)

# Several minutes of dialogue: the analyst/synthesizer wider-context window.
# Deliberately large so the long-window call carries a realistic prefill and the
# short/long measurements diverge on a model that is actually prefill-bound.
_LONG_TAIL = (
    "Customer: Good. While we are here, the executive sponsor also cares about time-to-value. "
    "The last tool we bought took six months to actually get used.\n"
    "Rep: That is fair. Most teams your size are live in two to three weeks because the import "
    "is self-serve and we seed the first workflows with you.\n"
    "Customer: Two of our regional leads pushed back last time because reporting did not match "
    "how they run their pipeline. They each want their own view.\n"
    "Rep: We can template per-region views and still roll them into one executive dashboard, so "
    "each lead keeps their workflow without fragmenting the numbers.\n"
    "Customer: The security review is the real gate. If audio and transcripts stay on our "
    "hardware, that shortens the review a lot. Who else has done that with you?\n"
    "Rep: Two regulated customers run the fully self-hosted deployment; I can share a redacted "
    "architecture and their review checklist so your team is not starting cold.\n"
    "Customer: Procurement will also ask about total cost. Between licensing, the hardware to "
    "self-host, and the internal time to run it, what does year one really look like?\n"
    "Rep: I can build a side-by-side: hosted versus self-hosted, including the GPU box you would "
    "need and the hours your team spends versus us managing it. Most land on hosted for year one "
    "and revisit self-hosting once volume grows.\n"
    "Customer: The compliance team flagged data retention too. We are required to purge call "
    "recordings after ninety days. Can the platform enforce that automatically?\n"
    "Rep: Yes, retention is a per-workspace policy; you set the window and it purges audio and "
    "derived transcripts on schedule, with an export hook if legal needs an archive first.\n"
    "Customer: One of the regional leads is worried the AI will surface the wrong talking points "
    "mid-call and distract reps instead of helping.\n"
    "Rep: That is why the live prompts are advisory and ranked; a rep can collapse them. We can "
    "also tune how aggressively each agent fires so it stays quiet unless something matters.\n"
    "Customer: If we pilot, who needs to be involved and how do we measure whether it worked?\n"
    "Rep: A pilot is two or three reps, your security reviewer, and one regional lead. Success "
    "is faster follow-ups, fewer missed action items, and the reps choosing to keep it on after "
    "four weeks. We agree the metrics up front so it is not subjective.\n"
    "Customer: Okay. Send the on-prem details, the cost comparison, the retention policy note, "
    "and a pilot plan. If security signs off we can start next month.\n"
    "Rep: Perfect. I will package all of that today and include references from the two regulated "
    "customers so your reviewer has something concrete to work from.\n"
)
_LONG_TRANSCRIPT = _SHORT_TRANSCRIPT + _LONG_TAIL

# The timed calls are user messages (transcript + a brief directive); the heavy
# lifting is the agent's real system prompt, passed separately, which is what
# makes the measurement resemble a production call rather than a toy prompt.
_SHORT_USER = (
    f"Transcript (most recent ~90 seconds of a live call):\n{_SHORT_TRANSCRIPT}\n\n"
    "Follow your instructions for this transcript and return your findings as JSON."
)
_LONG_USER = (
    f"Transcript (most recent several minutes of a live call):\n{_LONG_TRANSCRIPT}\n\n"
    "Follow your instructions for this transcript and return your findings as JSON."
)
_PROMPTS = {"short": _SHORT_USER, "long": _LONG_USER}

# Fallback system prompt if an agent row and its seed default are both missing,
# so the benchmark still runs (just less representative).
_FALLBACK_SYSTEM = (
    "You are assisting live on a sales call. Analyze the transcript and return up to six "
    "concise findings (questions, observations, opportunities, action items) as JSON objects."
)

# Which agent's real system prompt represents each window: a light fast-cycle
# role for short, the heavy multi-lens analyst for long.
_PROFILE_ROLE = {"short": "objection_handler", "long": "consolidated_analyst"}

# Representative filler for the analyst prompt's runtime placeholders so the
# benchmark prompt has a realistic size and shape without pulling in the
# orchestrator's live prompt-composition.
_REPRESENTATIVE_LENS_BLOCK = (
    "## Lens: Strategic Follow-Up Questions\n"
    "Surface the highest-leverage questions the seller should ask next, grounded in what the "
    "buyer just said. Prefer questions that advance the deal or de-risk the evaluation.\n\n"
    "## Lens: Observations\n"
    "Call out meaningful shifts in sentiment, authority, urgency, or buying criteria.\n\n"
    "## Lens: Product & Service Opportunities\n"
    "Identify where a specific offering maps to a stated need, with the need quoted from the "
    "transcript.\n\n"
    "## Lens: Action Items\n"
    "Extract concrete commitments and owners so nothing agreed on the call is dropped."
)
_REPRESENTATIVE_CONTEXT = (
    "Meeting context: a mid-market prospect is evaluating the platform, weighing hosted versus "
    "self-hosted deployment, pricing, a security review, and time-to-value before a pilot."
)
_PLACEHOLDER_FILLERS = {
    "lens_sections": _REPRESENTATIVE_LENS_BLOCK,
    "meeting_context_text": _REPRESENTATIVE_CONTEXT,
}
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")

# One tiny call before the timed ones so model load / JIT warmup is not charged
# to the measurement.
_WARMUP_PROMPT = "Reply with the single word: ready."


def _fill_placeholders(prompt: str) -> str:
    """Fill an agent prompt's runtime placeholders with representative text.

    Known placeholders get realistic filler; any unknown `{token}` is dropped so
    the benchmark never sends a stray literal brace to a picky server.
    """
    return _PLACEHOLDER_RE.sub(lambda m: _PLACEHOLDER_FILLERS.get(m.group(1), ""), prompt)


async def role_system_prompts(db: AsyncSession) -> dict[str, str]:
    """The real system prompt for each window's representative agent.

    Uses the live AgentConfig prompt (falling back to the seeded default, then a
    generic system prompt) with placeholders filled, so the timed call carries
    the same heavy prefill a production call would.
    """
    from app.services.seed_agents import DEFAULT_PROMPTS

    slugs = list(_PROFILE_ROLE.values())
    rows = (
        await db.execute(select(AgentConfig).where(AgentConfig.slug.in_(slugs)))
    ).scalars().all()
    by_slug = {row.slug: row.prompt for row in rows}
    prompts: dict[str, str] = {}
    for profile, slug in _PROFILE_ROLE.items():
        raw = by_slug.get(slug) or DEFAULT_PROMPTS.get(slug) or _FALLBACK_SYSTEM
        prompts[profile] = _fill_placeholders(raw)
    return prompts


@dataclass(frozen=True)
class ProfileLatency:
    latency_seconds: float
    output_chars: int
    tokens_per_second: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RoleFit:
    slug: str
    name: str
    prompt_profile: str
    latency_seconds: float  # raw measured latency; the UI applies contention live
    budget_seconds: int
    verdict: str
    recommended_interval_seconds: int
    changed: bool
    # Post-call briefing agents have no live cycle: not editable, no recommended
    # interval, judged on end-of-call wait instead.
    post_call: bool = False
    editable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TextModelFit:
    model_id: str
    model_name: str
    status: str  # "ok" or "failed"
    reason: str = ""
    short: ProfileLatency | None = None
    long: ProfileLatency | None = None
    roles: list[RoleFit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "status": self.status,
            "reason": self.reason,
            "short": self.short.to_dict() if self.short else None,
            "long": self.long.to_dict() if self.long else None,
            "roles": [role.to_dict() for role in self.roles],
        }


def classify_latency(latency_seconds: float, budget_seconds: int) -> str:
    """green: comfortable headroom; yellow: keeps up but tight; red: falls behind.

    latency_seconds is the *effective* latency (already scaled by contention).
    """
    if latency_seconds <= 0:
        return GREEN
    if budget_seconds <= 0:
        return RED
    ratio = latency_seconds / budget_seconds
    if ratio <= HEADROOM:
        return GREEN
    if ratio <= 1.0:
        return YELLOW
    return RED


def classify_post_call(effective_seconds: float) -> str:
    """Verdict for a post-call briefing: judged on acceptable end-of-call wait."""
    if effective_seconds <= POST_CALL_GREEN_SECONDS:
        return GREEN
    if effective_seconds <= POST_CALL_YELLOW_SECONDS:
        return YELLOW
    return RED


def effective_latency(latency_seconds: float, contention: float) -> float:
    """Measured latency scaled for the load a real call adds. Clamped to sane range."""
    factor = min(max(contention, MIN_CONTENTION), MAX_CONTENTION)
    return round(latency_seconds * factor, 3)


def _round_up(value: float, step: int = ROUND_STEP) -> int:
    if value <= 0:
        return step
    return int(math.ceil(value / step) * step)


def recommend_interval(latency_seconds: float, current_interval_seconds: int) -> int:
    """Smallest tidy interval that restores headroom, never faster than current.

    A fast (green) model needs no change, so the recommendation equals the
    current interval. A slow model is lengthened to about twice its call
    latency, clamped so an unusably slow model tops out at MAX_INTERVAL rather
    than recommending a non-live number.
    """
    needed = _round_up(latency_seconds / HEADROOM) if latency_seconds > 0 else MIN_INTERVAL
    recommended = max(current_interval_seconds, needed, MIN_INTERVAL)
    return min(recommended, MAX_INTERVAL)


def score_text_model(
    fit: TextModelFit,
    budgets: dict[str, int],
    contention: float = DEFAULT_CONTENTION,
) -> list[RoleFit]:
    """Score every agent against this model's measured latency for this model's
    per-model budgets, reserving headroom for contention.

    `budgets` is the per-model cycle budget map for the interval-driven agents.
    Post-call briefing agents are judged on end-of-call wait, not a budget.
    """
    if fit.status != "ok" or fit.short is None or fit.long is None:
        return []
    roles: list[RoleFit] = []
    for role in AGENT_ROLES:
        profile = fit.long if role.prompt_profile == "long" else fit.short
        latency = profile.latency_seconds
        effective = effective_latency(latency, contention)
        if role.post_call:
            roles.append(
                RoleFit(
                    slug=role.slug,
                    name=role.name,
                    prompt_profile=role.prompt_profile,
                    latency_seconds=latency,
                    budget_seconds=POST_CALL_GREEN_SECONDS,
                    verdict=classify_post_call(effective),
                    recommended_interval_seconds=0,
                    changed=False,
                    post_call=True,
                    editable=False,
                )
            )
            continue
        budget = budgets.get(role.slug) or role.default_interval
        recommended = recommend_interval(effective, budget)
        roles.append(
            RoleFit(
                slug=role.slug,
                name=role.name,
                prompt_profile=role.prompt_profile,
                latency_seconds=latency,
                budget_seconds=budget,
                verdict=classify_latency(effective, budget),
                recommended_interval_seconds=recommended,
                changed=recommended != budget,
                post_call=False,
                editable=True,
            )
        )
    return roles


def _estimate_tokens_per_second(output_chars: int, elapsed: float) -> float | None:
    if elapsed <= 0:
        return None
    return round((output_chars / _CHARS_PER_TOKEN) / elapsed, 1)


async def benchmark_text_model(
    model_id: str,
    model_name: str,
    *,
    system_prompts: dict[str, str] | None = None,
    generate: GenerateText = generate_text,
) -> TextModelFit:
    """Warm up, then time one short-window and one long-window call.

    Each timed call carries the representative agent's real system prompt (via
    system_prompts) so the measurement resembles a production call. A model that
    errors on any call (server down, unsupported request) returns a failed fit
    with the reason rather than raising, so one bad endpoint does not abort the
    whole run.
    """
    system_prompts = system_prompts or {}
    try:
        await generate(model_id, _WARMUP_PROMPT, source="local_fit")
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a reason
        return TextModelFit(model_id, model_name, status="failed", reason=f"Model call failed: {exc}")

    profiles: dict[str, ProfileLatency] = {}
    for name, prompt in _PROMPTS.items():
        try:
            started = time.perf_counter()
            text = await generate(
                model_id, prompt, system=system_prompts.get(name), source="local_fit"
            )
            elapsed = time.perf_counter() - started
        except Exception as exc:  # noqa: BLE001
            return TextModelFit(
                model_id, model_name, status="failed", reason=f"{name} benchmark failed: {exc}"
            )
        output_chars = len(text or "")
        profiles[name] = ProfileLatency(
            latency_seconds=round(elapsed, 3),
            output_chars=output_chars,
            tokens_per_second=_estimate_tokens_per_second(output_chars, elapsed),
        )
    return TextModelFit(
        model_id,
        model_name,
        status="ok",
        short=profiles["short"],
        long=profiles["long"],
    )


async def local_text_models(db: AsyncSession) -> list[dict]:
    """On-prem, text-capable endpoint models: the ones that can run agents offline."""
    return [
        m
        for m in await endpoint_models(db)
        if m.get("runs_locally") and m.get("supports_text")
    ]


async def _interval_agent_rows(db: AsyncSession) -> dict[str, AgentConfig]:
    rows = (
        await db.execute(
            select(AgentConfig).where(
                AgentConfig.slug.in_([role.slug for role in _INTERVAL_ROLES])
            )
        )
    ).scalars().all()
    return {row.slug: row for row in rows}


async def current_intervals(db: AsyncSession) -> dict[str, int]:
    """Each interval agent's global cycle budget (stored value or seeded default).

    A baseline for display before a model is chosen; the actual scoring uses the
    per-model budget from budgets_for_model().
    """
    by_slug = await _interval_agent_rows(db)
    return {
        role.slug: (getattr(by_slug.get(role.slug), "interval_seconds", None) or role.default_interval)
        for role in _INTERVAL_ROLES
    }


async def budgets_for_model(db: AsyncSession, model_id: str) -> dict[str, int]:
    """Per-model cycle budget for each interval agent: the model-specific value,
    else the agent's global interval, else the seeded default."""
    by_slug = await _interval_agent_rows(db)
    budgets: dict[str, int] = {}
    for role in _INTERVAL_ROLES:
        row = by_slug.get(role.slug)
        per_model = (
            parse_model_intervals(getattr(row, "model_intervals", "")).get(model_id)
            if row
            else None
        )
        budgets[role.slug] = (
            per_model
            or (row.interval_seconds if row and row.interval_seconds else None)
            or role.default_interval
        )
    return budgets


def role_catalog() -> list[dict]:
    return [
        {
            "slug": role.slug,
            "name": role.name,
            "prompt_profile": role.prompt_profile,
            "default_interval": role.default_interval,
            "post_call": role.post_call,
        }
        for role in AGENT_ROLES
    ]


# --- Local capability map (where each local model can be used) -------------
#
# Each user-facing AI service and the model capability flag it needs. Derived
# straight from the registry flags so this map never drifts from what actually
# routes. "Meeting chat" and the analysis agents both need text, so a chat
# endpoint shows up under both.

LOCAL_SERVICES: tuple[tuple[str, str, str], ...] = (
    ("batch_transcription", "Batch transcription", "supports_batch_audio"),
    ("live_captions", "Live interim captions", "supports_live_audio"),
    ("analysis_agents", "Analysis agents", "supports_text"),
    ("meeting_chat", "Meeting chat & summarization", "supports_text"),
)

# When nothing local can fill a service, name the cloud capability it needs so
# the gap is actionable rather than a blank.
_CLOUD_ONLY_NOTE = {
    "live_captions": "needs a cloud streaming model (Gemini Live or OpenAI Realtime)",
}


def _model_usable_for(model: dict) -> list[str]:
    return [label for _key, label, cap in LOCAL_SERVICES if model.get(cap)]


def build_local_capabilities(models: list[dict]) -> dict:
    """Map local models to the services they can fill, and each service back to
    its local options (or a cloud-only note when there are none).

    `models` are registry-shaped dicts (id, name, supports_*). Pure, so the
    service/capability mapping is unit-tested without a DB or live models.
    """
    services = []
    for key, label, cap in LOCAL_SERVICES:
        options = [{"id": m["id"], "name": m["name"]} for m in models if m.get(cap)]
        services.append(
            {
                "key": key,
                "label": label,
                "local_options": options,
                "cloud_only": not options,
                "note": "" if options else _CLOUD_ONLY_NOTE.get(key, ""),
            }
        )
    model_usage = [
        {"id": m["id"], "name": m["name"], "usable_for": _model_usable_for(m)}
        for m in models
    ]
    return {"services": services, "models": model_usage}


async def local_models_all(db: AsyncSession) -> list[dict]:
    """Every model that runs on this machine: bundled ONNX plus on-prem endpoints."""
    from app.config import MODEL_REGISTRY

    bundled = [m for m in MODEL_REGISTRY if str(m.get("provider", "")).lower() == "local"]
    served = [m for m in await endpoint_models(db) if m.get("runs_locally")]
    return bundled + served


async def summarize_local_fit(db: AsyncSession) -> dict:
    """Light payload the card renders before running: what is available to test."""
    models = await local_text_models(db)
    return {
        "has_local_text_models": bool(models),
        "models": [{"id": m["id"], "name": m["name"]} for m in models],
        "intervals": await current_intervals(db),
        "roles": role_catalog(),
        "capabilities": build_local_capabilities(await local_models_all(db)),
        # The last run, so returning to the tab shows what was measured rather
        # than an empty card (see store_local_fit_result).
        "last_result": await load_local_fit_result(db),
    }


async def run_local_fit(
    db: AsyncSession,
    *,
    generate: GenerateText = generate_text,
    contention: float = DEFAULT_CONTENTION,
    include_asr: bool = True,
) -> dict:
    """Benchmark every on-prem text model against its per-model budgets, and the
    bundled local ASR models on a synthetic clip, in one pass."""
    models = await local_text_models(db)
    host = host_fingerprint(probe_sortformer_environment())
    measured_at = datetime.now(timezone.utc)
    systems = await role_system_prompts(db)
    text_models: list[dict] = []
    for model in models:
        fit = await benchmark_text_model(
            model["id"], model["name"], system_prompts=systems, generate=generate
        )
        budgets = await budgets_for_model(db, model["id"])
        fit.roles = score_text_model(fit, budgets, contention)
        measurement = fit.to_dict()
        measurement.update(
            stamp_fit_record(
                {
                    "model_id": model["id"],
                    "endpoint_fingerprint": model.get("endpoint_fingerprint"),
                },
                host,
                measured_at=measured_at,
            )
        )
        text_models.append(measurement)
    asr = None
    if include_asr:
        asr = await run_asr_fit(
            synthetic_speech_clip(), contention=contention, estimated=True
        )
        for measurement in asr["asr_models"]:
            measurement.update(
                stamp_fit_record(
                    {
                        "model_id": measurement["model_id"],
                        "endpoint_fingerprint": None,
                    },
                    host,
                    measured_at=measured_at,
                )
            )
    result = {
        "has_local_text_models": bool(models),
        "intervals": await current_intervals(db),
        "roles": role_catalog(),
        "contention": contention,
        "text_models": text_models,
        "asr": asr,
        "capabilities": build_local_capabilities(await local_models_all(db)),
        **stamp_fit_record(
            {
                "model_id": "local-fit",
                "endpoint_fingerprint": None,
            },
            host,
            measured_at=measured_at,
        ),
    }
    await store_local_fit_result(db, result)
    return result


LOCAL_FIT_RESULT_KEY = "diagnostics.local_fit.last_result"


async def store_local_fit_result(db: AsyncSession, result: dict) -> None:
    """Persist the last run so a page reload does not discard it.

    The test costs real time on a local model, so losing it to a refresh means
    re-running it. Stored whole rather than summarized: the card renders the
    same payload it would have received live.
    """
    payload = json.loads(json.dumps(result))
    if "schema_version" not in payload:
        host = host_fingerprint(probe_sortformer_environment())
        payload.update(
            stamp_fit_record(
                {"model_id": "local-fit", "endpoint_fingerprint": None},
                host,
            )
        )
    _drop_stored_judgments(payload)
    try:
        await set_app_setting(db, LOCAL_FIT_RESULT_KEY, json.dumps(payload))
        await db.commit()
    except Exception:
        # A benchmark the user already waited for must not be lost to a
        # storage problem; they still get the live result.
        logger.warning("Could not persist the local fit result", exc_info=True)


async def load_local_fit_result(db: AsyncSession) -> dict | None:
    raw = await get_app_setting(db, LOCAL_FIT_RESULT_KEY, "")
    if not raw:
        return None
    try:
        stored = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Stored local fit result is not valid JSON; ignoring")
        return None
    if not isinstance(stored, dict):
        return None
    current_models = await local_text_models(db)
    current_by_id = {model["id"]: model for model in current_models}
    host = host_fingerprint(probe_sortformer_environment())
    stored["validity"] = assess_fit_record(
        stored,
        current_subject={
            "model_id": "local-fit",
            "endpoint_fingerprint": None,
        },
        current_host=host,
    )
    if stored["validity"]["status"] == INCOMPATIBLE:
        return {
            "validity": stored["validity"],
            "measured_at": stored.get("measured_at"),
            "has_local_text_models": False,
            "models": [],
            "intervals": {},
            "roles": [],
            "text_models": [],
            "contention": DEFAULT_CONTENTION,
            "asr": None,
        }
    for measurement in stored.get("text_models") or []:
        current = current_by_id.get(measurement.get("model_id"))
        measurement["validity"] = assess_fit_record(
            measurement,
            current_subject=(
                {
                    "model_id": current["id"],
                    "endpoint_fingerprint": current.get("endpoint_fingerprint"),
                }
                if current
                else None
            ),
            current_host=host,
        )
        budgets = await budgets_for_model(db, measurement.get("model_id", ""))
        for role in measurement.get("roles") or []:
            role["budget_seconds"] = budgets.get(
                role.get("slug"), role.get("budget_seconds", 0)
            )
    for measurement in (stored.get("asr") or {}).get("asr_models") or []:
        measurement["validity"] = assess_fit_record(
            measurement,
            current_subject=(
                {
                    "model_id": measurement.get("model_id"),
                    "endpoint_fingerprint": None,
                }
                if measurement.get("model_id") in LOCAL_MODEL_MAP
                else None
            ),
            current_host=host,
        )
    return stored


async def local_model_recommendations(db: AsyncSession) -> dict[str, list[dict]]:
    return local_recommendations_from_fit(await load_local_fit_result(db))


def local_recommendations_from_fit(result: dict | None) -> dict[str, list[dict]]:
    """Recommend only current green winners from the latest Local Fit run."""
    if not result or (result.get("validity") or {}).get("status") != "current":
        return {}

    try:
        contention = float(result.get("contention", DEFAULT_CONTENTION))
    except (TypeError, ValueError):
        contention = DEFAULT_CONTENTION
    candidates: dict[str, list[tuple[float, str, RoleFit]]] = {}
    for measurement in result.get("text_models") or []:
        if (
            measurement.get("status") != "ok"
            or (measurement.get("validity") or {}).get("status") != "current"
        ):
            continue
        try:
            fit = TextModelFit(
                model_id=measurement["model_id"],
                model_name=measurement.get("model_name") or measurement["model_id"],
                status="ok",
                short=ProfileLatency(float(measurement["short"]["latency_seconds"]), 0, None),
                long=ProfileLatency(float(measurement["long"]["latency_seconds"]), 0, None),
            )
        except (KeyError, TypeError, ValueError):
            continue
        budgets = {
            role["slug"]: int(role["budget_seconds"])
            for role in measurement.get("roles") or []
            if role.get("slug") and isinstance(role.get("budget_seconds"), (int, float))
        }
        for role in score_text_model(fit, budgets, contention):
            if role.verdict == GREEN:
                candidates.setdefault(role.slug, []).append(
                    (
                        effective_latency(role.latency_seconds, contention),
                        fit.model_id,
                        role,
                    )
                )

    recommendations: dict[str, list[dict]] = {}
    for slug, choices in candidates.items():
        _, model_id, role = min(choices, key=lambda choice: (choice[0], choice[1]))
        recommendation = {
            "role": slug,
            "provider": "local",
            "recommended": True,
            "source": "local_fit",
        }
        if not role.post_call:
            recommendation["interval_seconds"] = role.recommended_interval_seconds
        recommendations.setdefault(model_id, []).append(recommendation)

    asr_candidates: list[tuple[float, str, dict]] = []
    for measurement in (result.get("asr") or {}).get("asr_models") or []:
        if (
            measurement.get("status") != "ok"
            or (measurement.get("validity") or {}).get("status") != "current"
        ):
            continue
        try:
            effective_rtf = effective_latency(
                float(measurement["real_time_factor"]),
                contention,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if classify_rtf(effective_rtf) == GREEN:
            asr_candidates.append(
                (effective_rtf, measurement["model_id"], measurement)
            )

    if asr_candidates:
        _, model_id, _ = min(asr_candidates, key=lambda choice: (choice[0], choice[1]))
        recommendations.setdefault(model_id, []).append(
            {
                "role": "batch_transcription",
                "provider": "local",
                "recommended": True,
                "source": "local_fit",
            }
        )

    live_measurement = next(
        (
            measurement
            for _, model_id, measurement in asr_candidates
            if model_id == "local-parakeet-tdt-0.6b"
        ),
        None,
    )
    if live_measurement is not None:
        try:
            live_rtf = effective_latency(
                float(live_measurement["short_real_time_factor"]),
                contention,
            )
        except (KeyError, TypeError, ValueError):
            live_rtf = float("inf")
        if classify_live_feasibility(live_rtf) == FEASIBLE:
            recommendations["local-parakeet-live"] = [
                {
                    "role": "audio_gateway",
                    "provider": "local",
                    "recommended": True,
                    "source": "local_fit",
                }
            ]

    return recommendations


def _drop_stored_judgments(payload: dict) -> None:
    for model in payload.get("text_models") or []:
        for role in model.get("roles") or []:
            for key in ("verdict", "recommended_interval_seconds", "changed"):
                role.pop(key, None)
    for model in (payload.get("asr") or {}).get("asr_models") or []:
        model.pop("verdict", None)
        model.pop("live_feasibility", None)


def validate_interval_updates(updates: list[dict]) -> dict[str, int]:
    """Clean an apply payload into {slug: interval}, rejecting unknown/out-of-range.

    Only the interval-driven agents this test scores may be tuned here, and only
    within the live-interval range, so a stray payload cannot rewrite an
    unrelated agent or set a non-live cadence.
    """
    interval_slugs = {role.slug for role in _INTERVAL_ROLES}
    cleaned: dict[str, int] = {}
    for update in updates:
        slug = str(update.get("slug") or "").strip()
        if slug not in interval_slugs:
            raise ValueError(f"Unknown or non-tunable agent: {slug or '(empty)'}")
        raw = update.get("interval_seconds")
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise ValueError(f"interval_seconds for {slug} must be an integer")
        if raw < MIN_INTERVAL or raw > MAX_INTERVAL:
            raise ValueError(
                f"interval_seconds for {slug} must be between {MIN_INTERVAL} and {MAX_INTERVAL}"
            )
        cleaned[slug] = raw
    return cleaned


async def apply_recommended_intervals(
    db: AsyncSession, model_id: str, updates: list[dict]
) -> dict[str, int]:
    """Write validated per-model cycle budgets onto the matching AgentConfig rows.

    The budget is stored under model_id in each agent's model_intervals, so it
    only applies when that agent runs that model; other models are untouched.
    """
    from datetime import datetime, timezone

    if not model_id or not isinstance(model_id, str):
        raise ValueError("model_id is required")
    cleaned = validate_interval_updates(updates)
    if not cleaned:
        return {}
    rows = (
        await db.execute(
            select(AgentConfig).where(AgentConfig.slug.in_(list(cleaned)))
        )
    ).scalars().all()
    applied: dict[str, int] = {}
    now = datetime.now(timezone.utc)
    for row in rows:
        model_intervals = parse_model_intervals(getattr(row, "model_intervals", ""))
        model_intervals[model_id] = cleaned[row.slug]
        row.model_intervals = json.dumps(model_intervals)
        row.updated_at = now
        applied[row.slug] = cleaned[row.slug]
    await db.commit()
    return applied


# --- Transcription (local ASR) keep-up -------------------------------------
#
# The other half of running everything locally: each diarized segment must
# transcribe faster than real time (real-time factor < 1) or the transcript
# falls behind the call. Unlike the text test this needs a real speech clip,
# because LocalTranscriber gates on an energy floor and a speech check.

_PCM16_BYTES_PER_SECOND = 16000 * 2
# Enough audio for a stable factor; a diarized segment tops out around 15s, so
# a longer upload is trimmed to keep the measurement bounded.
MIN_ASR_SECONDS = 3
MAX_ASR_SECONDS = 30

# RTF = processing_seconds / audio_seconds. Under half real time leaves comfort;
# up to real time keeps up with no margin; over real time falls behind live.
ASR_GREEN_RTF = 0.5
ASR_YELLOW_RTF = 1.0

# Live-caption feasibility (experimental): a rolling-window local captioner (see
# ALP-147) would re-transcribe a ~3s window frequently, so the short-window RTF
# must sit well under real time with headroom. Deliberately very conservative.
LIVE_WINDOW_SECONDS = 3
ASR_LIVE_FEASIBLE_RTF = 0.33
ASR_LIVE_MARGINAL_RTF = 0.66
FEASIBLE = "feasible"
MARGINAL = "marginal"
NOT_FEASIBLE = "no"


@dataclass
class ASRModelFit:
    model_id: str
    model_name: str
    status: str  # "ok" or "failed"
    reason: str = ""
    audio_seconds: float = 0.0
    processing_seconds: float = 0.0
    real_time_factor: float | None = None
    verdict: str = ""
    short_real_time_factor: float | None = None
    live_feasibility: str = ""  # feasible / marginal / no (experimental)
    estimated: bool = False  # measured on a synthetic clip, not real speech

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_rtf(rtf: float) -> str:
    """green: comfortably faster than real time; yellow: keeps up; red: behind."""
    if rtf <= ASR_GREEN_RTF:
        return GREEN
    if rtf <= ASR_YELLOW_RTF:
        return YELLOW
    return RED


def classify_live_feasibility(short_rtf: float) -> str:
    """Whether a short rolling window could sustain local live captions (ALP-147)."""
    if short_rtf <= ASR_LIVE_FEASIBLE_RTF:
        return FEASIBLE
    if short_rtf <= ASR_LIVE_MARGINAL_RTF:
        return MARGINAL
    return NOT_FEASIBLE


def synthetic_speech_clip(seconds: int = 8) -> bytes:
    """A deterministic speech-band test tone with enough energy to pass the ASR
    speech gate. It only exercises the model for a SPEED measurement - the audio
    is not real speech, so its transcript is meaningless and unused."""
    import numpy as np

    sr = 16000
    t = np.arange(int(seconds * sr), dtype=np.float32) / sr
    tone = (
        0.6 * np.sin(2 * np.pi * 180 * t)
        + 0.4 * np.sin(2 * np.pi * 650 * t)
        + 0.3 * np.sin(2 * np.pi * 1400 * t)
    )
    envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 3.0 * t)  # syllable-rate modulation
    signal = np.clip(tone * envelope * 0.4, -1.0, 1.0)
    return (signal * 32767).astype("<i2").tobytes()


def asr_clip_seconds(pcm_bytes: bytes) -> float:
    return len(pcm_bytes) / _PCM16_BYTES_PER_SECOND


def is_asr_clip_too_short(pcm_bytes: bytes) -> bool:
    return len(pcm_bytes) < MIN_ASR_SECONDS * _PCM16_BYTES_PER_SECOND


def trim_asr_clip(pcm_bytes: bytes) -> bytes:
    return pcm_bytes[: MAX_ASR_SECONDS * _PCM16_BYTES_PER_SECOND]


def clip_has_speech(pcm_bytes: bytes) -> bool:
    return _audio_has_speech_energy(pcm_bytes)


def _asr_model_name(model_id: str) -> str:
    from app.config import MODEL_REGISTRY

    entry = next((m for m in MODEL_REGISTRY if m["id"] == model_id), None)
    return entry["name"] if entry else model_id


async def benchmark_asr_model(
    model_id: str,
    pcm_bytes: bytes,
    audio_seconds: float,
    *,
    short_pcm: bytes | None = None,
    short_seconds: float = 0.0,
    estimated: bool = False,
    make_transcriber: Callable[[str], Any] = LocalTranscriber,
) -> ASRModelFit:
    """Warm up (loads/downloads the model, untimed), then time the full clip and,
    for the live-caption feasibility check, a short rolling window."""
    name = _asr_model_name(model_id)
    try:
        transcriber = make_transcriber(model_id)
        await transcriber.transcribe_segment(pcm_bytes)  # warmup: model load is not charged
        started = time.perf_counter()
        await transcriber.transcribe_segment(pcm_bytes)
        elapsed = time.perf_counter() - started
        short_rtf = None
        if short_pcm is not None and short_seconds > 0:
            short_started = time.perf_counter()
            await transcriber.transcribe_segment(short_pcm)
            short_rtf = round((time.perf_counter() - short_started) / short_seconds, 3)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a reason
        return ASRModelFit(
            model_id,
            name,
            status="failed",
            reason=f"Transcription failed: {exc}",
            audio_seconds=round(audio_seconds, 2),
            estimated=estimated,
        )
    rtf = round(elapsed / audio_seconds, 3) if audio_seconds > 0 else None
    return ASRModelFit(
        model_id,
        name,
        status="ok",
        audio_seconds=round(audio_seconds, 2),
        processing_seconds=round(elapsed, 3),
        real_time_factor=rtf,
        verdict=classify_rtf(rtf) if rtf is not None else RED,
        short_real_time_factor=short_rtf,
        live_feasibility=classify_live_feasibility(short_rtf) if short_rtf is not None else "",
        estimated=estimated,
    )


def _apply_contention_to_asr(fit: ASRModelFit, contention: float) -> None:
    """Re-derive the verdict + feasibility with the contention cushion applied."""
    if fit.status != "ok" or fit.real_time_factor is None:
        return
    fit.verdict = classify_rtf(effective_latency(fit.real_time_factor, contention))
    if fit.short_real_time_factor is not None:
        fit.live_feasibility = classify_live_feasibility(
            effective_latency(fit.short_real_time_factor, contention)
        )


async def run_asr_fit(
    pcm_bytes: bytes,
    *,
    contention: float = DEFAULT_CONTENTION,
    estimated: bool = False,
    make_transcriber: Callable[[str], Any] = LocalTranscriber,
) -> dict:
    """Measure real-time factor (and short-window live-caption feasibility) for
    every bundled local ASR model on one clip, with the contention cushion."""
    clip = trim_asr_clip(pcm_bytes)
    audio_seconds = asr_clip_seconds(clip)
    short_pcm = clip[: LIVE_WINDOW_SECONDS * _PCM16_BYTES_PER_SECOND]
    short_seconds = asr_clip_seconds(short_pcm)
    models = []
    for model_id in LOCAL_MODEL_MAP:
        fit = await benchmark_asr_model(
            model_id,
            clip,
            audio_seconds,
            short_pcm=short_pcm,
            short_seconds=short_seconds,
            estimated=estimated,
            make_transcriber=make_transcriber,
        )
        _apply_contention_to_asr(fit, contention)
        models.append(fit.to_dict())
    return {
        "audio_seconds": round(audio_seconds, 2),
        "estimated": estimated,
        "asr_models": models,
    }

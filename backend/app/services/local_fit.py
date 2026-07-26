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

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConfig
from app.services.batch_transcriber import _audio_has_speech_energy
from app.services.custom_endpoints import endpoint_models
from app.services.llm import generate_text
from app.services.local_transcriber import LOCAL_MODEL_MAP, LocalTranscriber

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


@dataclass(frozen=True)
class AgentRole:
    """An interval-driven text agent and the prompt size it works over."""

    slug: str
    name: str
    prompt_profile: str  # "short" or "long"
    default_interval: int


# The five text agents whose loops are latency-critical during a live call.
# Briefing lenses run at call end (no live budget) and the audio bridge is not a
# text model, so neither is scored here. default_interval mirrors
# seed_agents.SEED_CONFIGS and is the fallback when a row has no interval set.
AGENT_ROLES: tuple[AgentRole, ...] = (
    AgentRole("objection_handler", "Objection Handler", "short", 10),
    AgentRole("opportunity_specialist", "Opportunity Specialist", "short", 55),
    AgentRole("consolidated_analyst", "Consolidated Analyst", "long", 40),
    AgentRole("strategic_signals", "Strategic Signals", "long", 45),
    AgentRole("synthesizer", "Principal Agent", "long", 75),
)

_ROLES_BY_SLUG = {role.slug: role for role in AGENT_ROLES}

# A bounded instruction so we measure prompt-processing plus a small, realistic
# generation, which is what the agents actually do (they emit compact JSON).
_INSTRUCTION = (
    "You are assisting live on a sales call. From the transcript below, list up "
    "to three concise bullet points a seller should notice. Keep it under 60 words."
)

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

# ~300 seconds of dialogue: the analyst/synthesizer wider-context window.
_LONG_TRANSCRIPT = _SHORT_TRANSCRIPT + (
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
    "Customer: That plus the volume pricing might get procurement over the line. Send the "
    "on-prem details and let us line up the security walkthrough for next week.\n"
    "Rep: Will do. I will also include the rollout plan so the sponsor sees the time-to-value "
    "path, not just the licensing.\n"
)

_PROMPTS = {
    "short": f"{_INSTRUCTION}\n\nTranscript:\n{_SHORT_TRANSCRIPT}",
    "long": f"{_INSTRUCTION}\n\nTranscript:\n{_LONG_TRANSCRIPT}",
}

# One tiny call before the timed ones so model load / JIT warmup is not charged
# to the measurement.
_WARMUP_PROMPT = "Reply with the single word: ready."


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
    latency_seconds: float
    budget_seconds: int
    verdict: str
    recommended_interval_seconds: int
    changed: bool

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
    """green: comfortable headroom; yellow: keeps up but tight; red: falls behind."""
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


def score_text_model(fit: TextModelFit, intervals: dict[str, int]) -> list[RoleFit]:
    """Score every interval-driven agent against this model's measured latency."""
    if fit.status != "ok" or fit.short is None or fit.long is None:
        return []
    roles: list[RoleFit] = []
    for role in AGENT_ROLES:
        profile = fit.long if role.prompt_profile == "long" else fit.short
        latency = profile.latency_seconds
        budget = intervals.get(role.slug) or role.default_interval
        recommended = recommend_interval(latency, budget)
        roles.append(
            RoleFit(
                slug=role.slug,
                name=role.name,
                prompt_profile=role.prompt_profile,
                latency_seconds=latency,
                budget_seconds=budget,
                verdict=classify_latency(latency, budget),
                recommended_interval_seconds=recommended,
                changed=recommended != budget,
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
    generate: GenerateText = generate_text,
) -> TextModelFit:
    """Warm up, then time one short-window and one long-window call.

    A model that errors on any call (server down, unsupported request) returns a
    failed fit with the reason rather than raising, so one bad endpoint does not
    abort the whole run.
    """
    try:
        await generate(model_id, _WARMUP_PROMPT, source="local_fit")
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a reason
        return TextModelFit(model_id, model_name, status="failed", reason=f"Model call failed: {exc}")

    profiles: dict[str, ProfileLatency] = {}
    for name, prompt in _PROMPTS.items():
        try:
            started = time.perf_counter()
            text = await generate(model_id, prompt, source="local_fit")
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


async def current_intervals(db: AsyncSession) -> dict[str, int]:
    """Each scored agent's effective cycle budget (stored value or seeded default)."""
    rows = (
        await db.execute(
            select(AgentConfig).where(AgentConfig.slug.in_(list(_ROLES_BY_SLUG)))
        )
    ).scalars().all()
    stored = {row.slug: row.interval_seconds for row in rows}
    return {
        role.slug: stored.get(role.slug) or role.default_interval
        for role in AGENT_ROLES
    }


def role_catalog() -> list[dict]:
    return [
        {
            "slug": role.slug,
            "name": role.name,
            "prompt_profile": role.prompt_profile,
            "default_interval": role.default_interval,
        }
        for role in AGENT_ROLES
    ]


async def summarize_local_fit(db: AsyncSession) -> dict:
    """Light payload the card renders before running: what is available to test."""
    models = await local_text_models(db)
    return {
        "has_local_text_models": bool(models),
        "models": [{"id": m["id"], "name": m["name"]} for m in models],
        "intervals": await current_intervals(db),
        "roles": role_catalog(),
    }


async def run_local_fit(
    db: AsyncSession,
    *,
    generate: GenerateText = generate_text,
) -> dict:
    """Benchmark every on-prem text model and score it against each agent role."""
    models = await local_text_models(db)
    intervals = await current_intervals(db)
    text_models: list[dict] = []
    for model in models:
        fit = await benchmark_text_model(model["id"], model["name"], generate=generate)
        fit.roles = score_text_model(fit, intervals)
        text_models.append(fit.to_dict())
    return {
        "has_local_text_models": bool(models),
        "intervals": intervals,
        "roles": role_catalog(),
        "text_models": text_models,
    }


def validate_interval_updates(updates: list[dict]) -> dict[str, int]:
    """Clean an apply payload into {slug: interval}, rejecting unknown/out-of-range.

    Only the interval-driven agents this test scores may be tuned here, and only
    within the live-interval range, so a stray payload cannot rewrite an
    unrelated agent or set a non-live cadence.
    """
    cleaned: dict[str, int] = {}
    for update in updates:
        slug = str(update.get("slug") or "").strip()
        if slug not in _ROLES_BY_SLUG:
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


async def apply_recommended_intervals(db: AsyncSession, updates: list[dict]) -> dict[str, int]:
    """Write validated cycle intervals onto the matching AgentConfig rows."""
    from datetime import datetime, timezone

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
        row.interval_seconds = cleaned[row.slug]
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_rtf(rtf: float) -> str:
    """green: comfortably faster than real time; yellow: keeps up; red: behind."""
    if rtf <= ASR_GREEN_RTF:
        return GREEN
    if rtf <= ASR_YELLOW_RTF:
        return YELLOW
    return RED


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
    make_transcriber: Callable[[str], Any] = LocalTranscriber,
) -> ASRModelFit:
    """Warm up (loads/downloads the model, untimed), then time one transcription."""
    name = _asr_model_name(model_id)
    try:
        transcriber = make_transcriber(model_id)
        await transcriber.transcribe_segment(pcm_bytes)  # warmup: model load is not charged
        started = time.perf_counter()
        await transcriber.transcribe_segment(pcm_bytes)
        elapsed = time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a reason
        return ASRModelFit(
            model_id,
            name,
            status="failed",
            reason=f"Transcription failed: {exc}",
            audio_seconds=round(audio_seconds, 2),
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
    )


async def run_asr_fit(
    pcm_bytes: bytes,
    *,
    make_transcriber: Callable[[str], Any] = LocalTranscriber,
) -> dict:
    """Measure real-time factor for every bundled local ASR model on one clip."""
    clip = trim_asr_clip(pcm_bytes)
    audio_seconds = asr_clip_seconds(clip)
    models = [
        (
            await benchmark_asr_model(
                model_id, clip, audio_seconds, make_transcriber=make_transcriber
            )
        ).to_dict()
        for model_id in LOCAL_MODEL_MAP
    ]
    return {"audio_seconds": round(audio_seconds, 2), "asr_models": models}

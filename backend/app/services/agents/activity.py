"""Per-call agent activity and call health snapshots."""

import asyncio
import copy
import logging
import uuid
from datetime import datetime, timedelta, timezone
from time import monotonic

import httpx

from app.services.llm import LLMReplyTruncated

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def saved_outcome(last_outcome: dict | None, *, produced: int, saved: int) -> dict:
    """Merge model output with the orchestrator's dedup/save result."""
    if saved:
        return {
            "kind": "insights",
            "detail": f"{saved} insight{'s' if saved != 1 else ''} saved",
            "items": saved,
            "deduped": max(0, produced - saved),
        }
    if produced:
        return {
            "kind": "all_deduped",
            "detail": (
                f"{produced} item{'s were' if produced != 1 else ' was'} "
                "near-duplicates of recent insights"
            ),
            "items": 0,
            "deduped": produced,
        }
    return last_outcome or {
        "kind": "no_findings",
        "detail": "The model found nothing to surface.",
        "items": 0,
    }


def classify_error(exc: Exception, model_id: str = "") -> dict:
    detail = str(exc) or type(exc).__name__
    if isinstance(exc, LLMReplyTruncated):
        return {
            "kind": "truncated",
            "detail": detail,
            "remedy": (
                "The model's reply hit its output limit; use a model with more "
                "output headroom or raise the self-hosted output budget."
            ),
        }
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        remedy = (
            "The self-hosted endpoint did not answer in time; check the server "
            "or raise this agent's cycle budget in the Admin fit test."
            if model_id.startswith("endpoint:")
            else "The model did not answer in time; check the provider and try again."
        )
        return {"kind": "timeout", "detail": detail, "remedy": remedy}
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {
        400,
        401,
        403,
        422,
    }:
        return {
            "kind": "refusal",
            "detail": detail,
            "remedy": "Check the model, credentials, and output budget in Admin.",
        }
    return {
        "kind": "api_error",
        "detail": detail,
        "remedy": "Check the model connection in Admin -> Connections.",
    }


class ActivityRegistry:
    """In-memory runtime state for one orchestrator."""

    def __init__(
        self,
        session_id: uuid.UUID,
        websocket,
        agents: list[dict],
        *,
        privacy_first: bool = False,
        coalesce_seconds: float = 2.0,
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.coalesce_seconds = coalesce_seconds
        self._agents = {}
        for agent in agents:
            record = {
                **agent,
                "blocked_reason": agent.get("blocked_reason", ""),
                "remedy": agent.get("remedy", ""),
                "last_run_started_at": None,
                "last_run_ms": None,
                "next_due_at": None,
                "last_outcome": None,
                "last_error": None,
                "counts": {
                    "runs": 0,
                    "insights": 0,
                    "productive": 0,
                    "deduped": 0,
                    "errors": 0,
                },
            }
            interval = record.get("interval_seconds")
            if record["state"] == "waiting" and interval:
                record["next_due_at"] = _iso(_now() + timedelta(seconds=interval))
            self._agents[record["slug"]] = record
        self._call = {
            "privacy_first": privacy_first,
            "degraded": False,
            "degraded_reasons": [],
            "gateway": {"state": "off", "detail": ""},
            "transcription": {
                "jobs": 0,
                "failed": 0,
                "last_error": "",
            },
            "diarization": {"queued": 0, "shed": 0},
        }
        self._cycle_started_at: dict[str, float] = {}
        self._last_emit_at = float("-inf")
        self._pending_emit: asyncio.Task | None = None

    def snapshot(self) -> dict:
        return {
            "session_id": str(self.session_id),
            "at": _iso(),
            "agents": copy.deepcopy(list(self._agents.values())),
            "call": copy.deepcopy(self._call),
        }

    async def emit(self, *, force: bool = False):
        if force:
            if self._pending_emit and not self._pending_emit.done():
                self._pending_emit.cancel()
            self._pending_emit = None
            await self._send()
            return

        delay = self.coalesce_seconds - (monotonic() - self._last_emit_at)
        if delay <= 0:
            await self._send()
        elif not self._pending_emit or self._pending_emit.done():
            self._pending_emit = asyncio.create_task(self._emit_after(delay))

    async def _emit_after(self, delay: float):
        try:
            await asyncio.sleep(delay)
            await self._send()
        except asyncio.CancelledError:
            pass
        finally:
            if self._pending_emit is asyncio.current_task():
                self._pending_emit = None

    async def _send(self):
        self._last_emit_at = monotonic()
        try:
            await self.websocket.send_json(
                {"type": "agent_activity", "data": self.snapshot()}
            )
        except Exception as exc:
            logger.debug("Agent activity snapshot send failed: %s", exc)

    async def cycle_started(self, slug: str):
        record = self._agents[slug]
        record["state"] = "running"
        record["last_run_started_at"] = _iso()
        record["next_due_at"] = None
        self._cycle_started_at[slug] = monotonic()
        await self.emit()

    async def cycle_finished(self, slug: str, outcome: dict):
        record = self._agents[slug]
        started = self._cycle_started_at.pop(slug, monotonic())
        record["state"] = "waiting"
        record["last_run_ms"] = max(0, round((monotonic() - started) * 1000))
        record["last_error"] = None
        record["last_outcome"] = {**outcome, "at": _iso()}
        interval = record.get("interval_seconds")
        record["next_due_at"] = (
            _iso(_now() + timedelta(seconds=interval)) if interval else None
        )
        record["counts"]["runs"] += 1
        if outcome.get("kind") == "insights":
            record["counts"]["productive"] += 1
        record["counts"]["insights"] += int(
            outcome.get("items", 0) if outcome.get("kind") == "insights" else 0
        )
        record["counts"]["deduped"] += int(outcome.get("deduped", 0))
        await self.emit()

    async def cycle_error(self, slug: str, error: dict):
        record = self._agents[slug]
        started = self._cycle_started_at.pop(slug, monotonic())
        record["state"] = "failing"
        record["last_run_ms"] = max(0, round((monotonic() - started) * 1000))
        record["next_due_at"] = None
        record["last_error"] = {**error, "at": _iso()}
        record["counts"]["runs"] += 1
        record["counts"]["errors"] += 1
        await self.emit(force=True)

    async def set_agent_state(
        self,
        slug: str,
        state: str,
        *,
        blocked_reason: str = "",
        remedy: str = "",
    ):
        record = self._agents[slug]
        changed = (
            record["state"] != state
            or record["blocked_reason"] != blocked_reason
            or record["remedy"] != remedy
        )
        record.update(
            state=state,
            blocked_reason=blocked_reason,
            remedy=remedy,
            next_due_at=None if state != "waiting" else record["next_due_at"],
        )
        if changed:
            await self.emit(force=state in {"blocked", "failing"})

    async def update_call(self, **sections: dict):
        was_degraded = self._call["degraded"]
        for name, values in sections.items():
            self._call[name].update(values)

        reasons = []
        failed = self._call["transcription"]["failed"]
        shed = self._call["diarization"]["shed"]
        if failed:
            part = "part" if failed == 1 else "parts"
            reasons.append(
                f"{failed} {part} of the conversation could not be transcribed. "
                "The transcript may be incomplete."
            )
        if shed:
            reasons.append(
                "Live processing is falling behind. Some transcript text or "
                "speaker labels may be missing."
            )
        if self._call["gateway"]["state"] == "reconnecting":
            reasons.append("Live captions are reconnecting and may be delayed.")
        self._call["degraded_reasons"] = reasons
        self._call["degraded"] = bool(reasons)
        await self.emit(force=was_degraded != self._call["degraded"])

    async def close(self):
        await self.emit(force=True)
        if self._pending_emit and not self._pending_emit.done():
            self._pending_emit.cancel()
        self._pending_emit = None

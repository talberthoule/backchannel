"""AgentOrchestrator — event-driven agent coordination.

Architecture:
- Audio Gateway (native-audio model, Gemini Live) — silent listener, relays input_transcription
- Consolidated Analyst (text model, batch interval) — questions, observations, opportunities, action items
- Objection Handler (fast text model, short interval) — flags objections with a ready response
- Synthesizer (meta-agent) — event-driven, runs on new_insight with cooldown
- Opportunity Specialist (DB-backed) — event-driven, runs on new_opportunity
- Internal EventBus for pub/sub coordination between agents
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import WebSocket
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Directive, Question
from app.services.transcript_refiner import (
    REFINER_LIVE_WINDOW,
    REFINER_SLUG as TRANSCRIPT_REFINER_SLUG,
    refine_session,
    update_payload as refiner_update_payload,
)
from app.services.agents.activity import (
    ActivityRegistry,
    classify_error,
    saved_outcome,
)
from app.services.agents.base import TranscriptBuffer
from app.services.agents.consolidated_analyst import ConsolidatedAnalystAgent
from app.services.agents.event_bus import CooldownSubscriber, EventBus
from app.services.agents.objection_handler import ObjectionHandlerAgent
from app.services.agents.opportunity_specialist import run_opportunity_specialist_cycle
from app.services.agents.strategic_signals import (
    STRATEGIC_SIGNALS_SLUG,
    run_strategic_signals_cycle,
)
from app.services.agents.synthesizer import clear_synthesizer_state, run_synthesizer_cycle
from app.services.briefing_synthesis import (
    BRIEF_ARBITER_SLUG,
    agent_config_enabled,
    run_session_synthesis,
)
from app.services.gemini_live import GeminiLiveSession
from app.services.llm import provider_for
from app.services.local_live_captioner import LocalLiveCaptioner, is_local_live_model
from app.services.openai_realtime import OpenAIRealtimeSession
from app.services.meeting_context import build_meeting_context_text, normalize_meeting_type, should_match_offerings

logger = logging.getLogger(__name__)


def _parse_model_intervals(raw: str) -> dict[str, int]:
    """Parse AgentConfig.model_intervals JSON into {model_id: interval}, tolerant
    of empty/garbage so a bad value never breaks scheduling."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


# Restatements cluster about a minute apart: on a measured 57-minute meeting the
# median gap between insights the synthesizer later merged was 1.0 minute, and 90
# percent were within 2.1 minutes. A 60s window structurally missed 13 of 21 of
# them and left the synthesizer to merge them afterwards at full corpus cost.
_DEDUP_WINDOW_SECONDS = 300

# Open questions carried into the analyst and strategic-signals prompts so they
# stop re-proposing what is already on the board. Only pruned when a question is
# answered, so on a measured meeting it grew to 45 entries and never shrank --
# unbounded in call length. Kept generous: the emission-time dedup cannot catch
# a re-proposal at minute 40 of something first raised at minute 12, so this
# list is the only thing standing between the user and that repeat (ALP-287).
_MAX_ACTIVE_QUESTIONS = 24

# Non-question insights already saved this call, stubbed for the analyst's
# "already on the board" context. The emission-time word-overlap dedup only
# reaches back _DEDUP_WINDOW_SECONDS and active_questions only carries
# item_type question, so nothing stopped the analyst from re-proposing a
# minute-12 observation at minute 40 in fresh words; the synthesizer then had
# to merge the copies after the user saw both. Stubs are head-truncated the
# way the synthesizer's settled records are (ALP-283) and the cap bounds the
# prompt cost on long calls: 48 stubs at 110 chars is roughly 1.5k tokens.
_MAX_BOARD_STUBS = 48
_BOARD_STUB_CHARS = 110
ProgressCallback = Callable[[dict[str, object]], Awaitable[None]]

# Drain modes for call finalization: "full" runs every post-call stage,
# "skip_analysis" stops after insight reconciliation, and "minimal"
# (disconnect/error path) runs no analysis stages at all.
DRAIN_MODE_FULL = "full"
DRAIN_MODE_SKIP_ANALYSIS = "skip_analysis"
DRAIN_MODE_MINIMAL = "minimal"

_SHIELD_GATEWAY_REMEDY = (
    "Cloud live captions would hear the names the shield withholds. "
    "Switch the Audio Bridge to the on-device captioner (Admin -> Agents) "
    "or turn off the PII Shield (Admin -> Privacy)."
)


def _shield_locks_gateway(slug: str, audio_local_only: bool, model_id: str) -> bool:
    """The PII Shield admits only an on-device model as the audio gateway."""
    return slug == "audio_gateway" and audio_local_only and not is_local_live_model(model_id)


_ACTIVITY_AGENTS = (
    ("audio_gateway", "Audio Bridge", "stream", None, True),
    (
        "consolidated_analyst",
        "Consolidated Analyst",
        "interval",
        settings.TEXT_AGENT_INTERVAL_SECONDS,
        True,
    ),
    (
        "objection_handler",
        "Objection Handler",
        "interval",
        settings.OBJECTION_HANDLER_INTERVAL_SECONDS,
        True,
    ),
    (
        "synthesizer",
        "Principal Agent",
        "event",
        settings.SYNTHESIZER_COOLDOWN_SECONDS,
        True,
    ),
    (
        "opportunity_specialist",
        "Opportunity Specialist",
        "event",
        settings.OPPORTUNITY_SPECIALIST_COOLDOWN_SECONDS,
        True,
    ),
    ("strategic_signals", "Strategic Signals", "interval", 45, False),
    (TRANSCRIPT_REFINER_SLUG, "Transcript Refiner", "interval", 45, False),
    ("brief_meeting_lens", "Briefing Meeting Lens", "post_call", None, True),
    ("brief_discovery_lens", "Briefing Discovery Lens", "post_call", None, True),
    ("brief_arbiter", "Briefing Arbiter", "post_call", None, True),
)


def drain_progress_percent(current_step: int, total_steps: int) -> int:
    """Map a finalization step onto the 15..95 band shown by the progress overlay."""
    if total_steps <= 1:
        return 95
    return 15 + round((current_step - 1) * 80 / (total_steps - 1))

# Live orchestrators by session id so REST routes can push mid-call updates.
# ponytail: in-process dict; needs a shared channel if the app ever runs multi-worker.
_live_orchestrators: dict[uuid.UUID, "AgentOrchestrator"] = {}


def get_live_orchestrator(session_id: uuid.UUID) -> "AgentOrchestrator | None":
    return _live_orchestrators.get(session_id)


# Matches the cadence the client already sees during transcription drain, so a
# quiet analysis stage is not mistaken for a stalled one.
DRAIN_HEARTBEAT_SECONDS = 5.0


async def _run_drain_heartbeat(
    progress_callback: ProgressCallback,
    latest: dict[str, dict],
    interval: float = DRAIN_HEARTBEAT_SECONDS,
) -> None:
    """Re-announce the running stage until the drain moves on.

    Repeats the last progress event rather than inventing one, so the client
    sees the same stage and step it already knows, marked as a heartbeat. A send
    failure ends the heartbeat quietly: the socket is gone, which the drain
    itself does not care about.
    """
    while True:
        await asyncio.sleep(interval)
        event = latest.get("event")
        if not event:
            continue
        try:
            await progress_callback({**event, "heartbeat": True})
        except Exception:
            return


async def _emit_progress(
    progress_callback: ProgressCallback | None,
    stage: str,
    message: str,
    current_step: int,
    total_steps: int,
    progress: int,
):
    if not progress_callback:
        return
    await progress_callback(
        {
            "stage": stage,
            "message": message,
            "current_step": current_step,
            "total_steps": total_steps,
            "progress": progress,
        }
    )


def _texts_similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """Simple word-overlap similarity check for near-duplicate detection."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    return overlap / min(len(words_a), len(words_b)) >= threshold


class AgentOrchestrator:
    """Central coordinator for all agents with event-driven coordination."""

    def __init__(
        self,
        session_id: uuid.UUID,
        websocket: WebSocket,
        directives: list[str],
        doc_summaries: str,
        active_questions: list[dict],
        speakers: list[dict],
        agent_configs: dict | None = None,
        meeting_type: str = "general",
        meeting_context: str = "",
        local_only: bool = False,
        admitted_models: set[str] | None = None,
        board_stubs: list[dict] | None = None,
        audio_local_only: bool = False,
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.directives = directives
        self.doc_summaries = doc_summaries
        self.active_questions = active_questions
        self.speakers = speakers
        self._agent_configs = agent_configs or {}
        self.local_only = local_only
        # The PII Shield locks audio alone: a cloud live gateway would hear
        # the names the shield exists to withhold, so it is skipped while
        # cloud text models (which receive tokens only) stay admitted.
        self.audio_local_only = audio_local_only or local_only
        # Model ids Privacy First admits, resolved by the caller because the
        # verdict needs a database read (see privacy.admitted_model_ids) and
        # this constructor is synchronous. None means "not resolved": fall back
        # to the bundled-local check so a caller that predates this stays safe.
        self.admitted_models = admitted_models
        self.privacy_blocked_agents: list[dict] = []
        self.meeting_type = normalize_meeting_type(meeting_type)
        self.meeting_context = meeting_context
        self._derive_meeting_context()

        def _get_model(slug: str) -> str:
            cfg = self._agent_configs.get(slug)
            return cfg.model_id if cfg else ""

        def _privacy_admits(model_id: str) -> bool:
            """Whether Privacy First lets this model run.

            Membership in the caller-resolved set, because admission is about
            where the model is served, not what its provider is called: a qwen
            on an endpoint at localhost qualifies while the same model behind a
            public URL does not. Only when the set was never resolved do we fall
            back to the bundled-ONNX check, which is conservative by design.
            """
            if self.admitted_models is not None:
                return model_id in self.admitted_models
            return provider_for(model_id) == "local"

        # Helper to check if an agent is enabled (DB config with fallback).
        # In Privacy First mode an enabled agent also needs a model that stays
        # on this machine or its network; one that does not is recorded so the
        # call can say so instead of the agent silently never running.
        def _is_enabled(slug: str, fallback: bool = True) -> bool:
            cfg = self._agent_configs.get(slug)
            enabled = cfg.enabled if cfg else fallback
            if not enabled:
                return False
            model_id = _get_model(slug)
            if not model_id:
                return False
            if _shield_locks_gateway(slug, self.audio_local_only, model_id):
                return False
            if not self.local_only:
                return enabled
            if _privacy_admits(model_id):
                return True
            if not any(b["agent"] == slug for b in self.privacy_blocked_agents):
                self.privacy_blocked_agents.append({"agent": slug, "model_id": model_id})
            return False

        def _get_prompt(slug: str) -> str:
            cfg = self._agent_configs.get(slug)
            return cfg.prompt if cfg else ""

        def _get_interval(slug: str, fallback: int) -> int:
            cfg = self._agent_configs.get(slug)
            if not cfg:
                return fallback
            # A per-model budget for the agent's assigned model wins, so the same
            # agent can run tighter on a fast model and looser on a slow one.
            per_model = _parse_model_intervals(getattr(cfg, "model_intervals", "")).get(cfg.model_id)
            if per_model:
                return per_model
            return cfg.interval_seconds if cfg.interval_seconds else fallback

        def _get_knowledge_source_ids(slug: str) -> list[uuid.UUID]:
            cfg = self._agent_configs.get(slug)
            raw = getattr(cfg, "knowledge_source_ids", "") if cfg else ""
            ids = []
            for part in (raw or "").split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    ids.append(uuid.UUID(part))
                except ValueError:
                    logger.warning(f"[orchestrator] invalid knowledge source id '{part}' on agent '{slug}'")
            return ids

        self._is_enabled = _is_enabled
        self._privacy_admits = _privacy_admits
        self._get_model = _get_model
        self._get_prompt = _get_prompt
        self._get_interval = _get_interval
        self._get_knowledge_source_ids = _get_knowledge_source_ids

        # Consolidated text analyst (includes question generation). Built before
        # the activity roster so its active lens count rides in the snapshot.
        enabled_types: set[str] = set()
        ca_cfg = self._agent_configs.get("consolidated_analyst")
        if ca_cfg and ca_cfg.sub_types:
            enabled_types = {t.strip() for t in ca_cfg.sub_types.split(",") if t.strip()}
        else:
            # Fallback to config.py settings
            enabled_types.add("question")
            if settings.AGENT_OBSERVER_ENABLED:
                enabled_types.add("observation")
            if settings.AGENT_OPPORTUNITY_SCOUT_ENABLED:
                enabled_types.add("opportunity")
            if settings.AGENT_ACTION_TRACKER_ENABLED:
                enabled_types.add("action_item")

        # Configurable lens definitions (JSON column); None falls back to the
        # defaults filtered by the legacy sub_types selection above.
        ca_lenses: list | None = None
        raw_lenses = (getattr(ca_cfg, "lenses", "") or "") if ca_cfg else ""
        if raw_lenses.strip():
            try:
                parsed = json.loads(raw_lenses)
                if isinstance(parsed, list):
                    ca_lenses = parsed
            except json.JSONDecodeError:
                logger.warning("[orchestrator] invalid lenses JSON on consolidated_analyst; using defaults")

        ca_model = _get_model("consolidated_analyst")
        self.consolidated_agent = ConsolidatedAnalystAgent(
            enabled_types=enabled_types or None,
            model_override=ca_model,
            prompt_override=_get_prompt("consolidated_analyst") or None,
            meeting_context_text=self.meeting_context_text,
            lenses=ca_lenses,
            session_id=session_id,
            suppressed_types=self._suppressed_analyst_types(),
        )

        activity_agents = []
        for slug, fallback_name, trigger, fallback_interval, fallback_enabled in _ACTIVITY_AGENTS:
            cfg = self._agent_configs.get(slug)
            configured_enabled = cfg.enabled if cfg else fallback_enabled
            admitted = _is_enabled(slug, fallback_enabled)
            session_override = getattr(cfg, "_session_override", None) if cfg else None
            interval = (
                _get_interval(slug, fallback_interval)
                if fallback_interval is not None
                else None
            )
            if interval is not None and (
                not isinstance(interval, (int, float))
                or isinstance(interval, bool)
            ):
                interval = fallback_interval
            if not configured_enabled:
                state = "off"
                blocked_reason = (
                    "session_override" if session_override is False else "disabled"
                )
                remedy = (
                    "Enabled globally but turned off for this session in pre-call agent selection."
                    if blocked_reason == "session_override"
                    else "Enable it in Admin -> Agents."
                )
            elif not _get_model(slug):
                state = "blocked"
                blocked_reason = "no_model"
                remedy = "Choose a model for this agent in Admin -> Agents."
            elif not admitted and not self.local_only and _shield_locks_gateway(slug, self.audio_local_only, _get_model(slug)):
                state = "blocked"
                blocked_reason = "pii_shield"
                remedy = _SHIELD_GATEWAY_REMEDY
            elif not admitted:
                state = "blocked"
                blocked_reason = "privacy_first"
                remedy = (
                    "Assign a local model to this agent (Admin -> Agents) or "
                    "turn off Privacy First (Admin -> Connections)."
                )
            elif slug == "opportunity_specialist" and not self._offering_matching_enabled:
                state = "blocked"
                blocked_reason = "meeting_type"
                remedy = (
                    "Runs for client/sales and customer delivery conversations; "
                    "change the conversation type to enable it."
                )
            else:
                state = "waiting"
                blocked_reason = ""
                remedy = ""
            record = {
                "slug": slug,
                "name": getattr(cfg, "name", "") or fallback_name,
                "trigger": trigger,
                "state": state,
                "enabled": configured_enabled,
                "blocked_reason": blocked_reason,
                "remedy": remedy,
                "interval_seconds": interval,
            }
            if slug == "consolidated_analyst":
                record["lens_count"] = self.consolidated_agent.lens_count
            activity_agents.append(record)
        self.activity = ActivityRegistry(
            session_id,
            websocket,
            activity_agents,
            privacy_first=local_only,
        )

        # Audio Gateway: a cloud streaming session (Gemini Live / OpenAI Realtime)
        # or the on-device local captioner, chosen by the gateway agent's model.
        gw_model = _get_model("audio_gateway")
        self.audio_gateway = None
        if is_local_live_model(gw_model):
            self.audio_gateway = LocalLiveCaptioner(model_override=gw_model, session_id=session_id)
        elif provider_for(gw_model) == "openai":
            self.audio_gateway = OpenAIRealtimeSession(model_override=gw_model, session_id=session_id)
        elif gw_model:
            self.audio_gateway = GeminiLiveSession(model_override=gw_model, session_id=session_id)

        # Objection handler (fast scan loop over the freshest transcript)
        self.objection_agent = ObjectionHandlerAgent(
            model_override=_get_model("objection_handler"),
            prompt_override=_get_prompt("objection_handler") or None,
            meeting_context_text=self.meeting_context_text,
            session_id=session_id,
        )

        # Shared transcript buffer
        self.transcript_buffer = TranscriptBuffer()

        # Event bus
        self._event_bus = EventBus()

        # Cooldown subscribers (created in start())
        self._synth_subscriber: CooldownSubscriber | None = None
        self._opp_specialist_subscriber: CooldownSubscriber | None = None

        # Coordination
        self._consolidated_task: asyncio.Task | None = None
        self._objection_task: asyncio.Task | None = None
        self._gateway_task: asyncio.Task | None = None
        self._strategic_signals_task: asyncio.Task | None = None
        self._refiner_task = None
        self._stopped = False

        # Recent insights for dedup (text -> timestamp)
        self._recent_insights: dict[str, float] = {}

        # Non-question insights on the board, stubbed for the analyst's
        # context (see _MAX_BOARD_STUBS). Seeded from the session's saved
        # insights so a resumed call remembers its own board.
        self._board_stubs: list[dict] = []
        for note in board_stubs or []:
            self._remember_board_stub(
                str(note.get("item_type") or "insight"),
                str(note.get("text") or ""),
            )

    def briefing_enabled(self) -> bool:
        # The arbiter settles the briefing, so its model decides whether the
        # stage can run at all; a lens on a refused model degrades to a partial
        # briefing rather than cancelling it (see briefing_synthesis).
        if not agent_config_enabled(self._agent_configs, BRIEF_ARBITER_SLUG):
            return False
        if not self._get_model(BRIEF_ARBITER_SLUG):
            return True
        if not self.local_only:
            return True
        return self._privacy_admits(self._get_model(BRIEF_ARBITER_SLUG))

    def drain_stages(self, mode: str = DRAIN_MODE_FULL) -> list[str]:
        """Ordered analysis stages graceful_drain runs for a drain mode.

        The websocket handler owns the surrounding steps: the transcript
        flush (speaker_assignment) before these and the session save after.
        """
        if mode == DRAIN_MODE_MINIMAL:
            return []
        stages = []
        # First, so the final insights and the briefing read the corrected
        # wording rather than the transcriber's.
        if self._is_enabled(TRANSCRIPT_REFINER_SLUG, False):
            stages.append("transcript_refinement")
        stages.extend(["final_insights", "insight_reconciliation"])
        if mode != DRAIN_MODE_SKIP_ANALYSIS:
            stages.append("opportunity_matching")
            if self.briefing_enabled():
                stages.append("call_briefing")
        return stages

    def drain_total_steps(self, mode: str = DRAIN_MODE_FULL) -> int:
        # Transcript flush (step 1) + drain stages + the final save step.
        return 2 + len(self.drain_stages(mode))

    async def start(self):
        """Connect all agents and wire event subscriptions."""
        # --- Audio Gateway (silent listener) ---
        if self._is_enabled("audio_gateway"):
            try:
                await self.audio_gateway.connect()
                self._gateway_task = asyncio.create_task(self._handle_gateway_responses())
                await self.activity.set_agent_state("audio_gateway", "running")
                await self.activity.update_call(
                    gateway={"state": "ok", "detail": ""}
                )
            except Exception as e:
                logger.error(f"Audio gateway unavailable, continuing without interim transcription: {e}")
                await self.activity.cycle_error(
                    "audio_gateway",
                    classify_error(e, self._get_model("audio_gateway")),
                )
                await self.activity.update_call(
                    gateway={"state": "reconnecting", "detail": str(e)}
                )
        else:
            await self.activity.update_call(
                gateway={"state": "off", "detail": ""}
            )

        # --- Consolidated Analyst ---
        if self._is_enabled("consolidated_analyst") and self.consolidated_agent.enabled_types:
            self._consolidated_task = asyncio.create_task(self._consolidated_agent_loop())

        # --- Objection Handler (fast scan) ---
        if self._is_enabled("objection_handler"):
            self._objection_task = asyncio.create_task(self._objection_agent_loop())

        # --- Event-driven: Synthesizer ---
        if self._is_enabled("synthesizer"):
            synth_cooldown = self._get_interval("synthesizer", settings.SYNTHESIZER_COOLDOWN_SECONDS)
            self._synth_subscriber = CooldownSubscriber(
                handler=self._run_synthesizer,
                cooldown_seconds=synth_cooldown,
                max_interval_seconds=max(settings.SYNTHESIZER_MAX_INTERVAL_SECONDS, synth_cooldown),
            )
            self._event_bus.subscribe("new_insight", self._synth_subscriber)
            self._event_bus.subscribe("insight_updated", self._synth_subscriber)
            await self._synth_subscriber.start_max_interval()

        # --- Event-driven: Opportunity Specialist ---
        self._wire_opportunity_specialist()

        if self._is_enabled(STRATEGIC_SIGNALS_SLUG, False):
            self._strategic_signals_task = asyncio.create_task(
                self._strategic_signals_loop()
            )

        if self._is_enabled(TRANSCRIPT_REFINER_SLUG, False):
            self._refiner_task = asyncio.create_task(self._transcript_refiner_loop())

        ca_interval = self._get_interval("consolidated_analyst", settings.TEXT_AGENT_INTERVAL_SECONDS)
        logger.info(
            f"Orchestrator started: gateway={self._is_enabled('audio_gateway')} "
            f"consolidated={self._is_enabled('consolidated_analyst')} "
            f"interval={ca_interval}s "
            f"types={self.consolidated_agent.enabled_types} "
            f"objection={self._is_enabled('objection_handler')} "
            f"synth={self._is_enabled('synthesizer')}(event-driven) "
            f"opp_specialist={self._is_enabled('opportunity_specialist')}(event-driven) "
            f"strategic_signals={self._is_enabled(STRATEGIC_SIGNALS_SLUG, False)}"
        )
        _live_orchestrators[self.session_id] = self

    def _wire_opportunity_specialist(self):
        """Subscribe the opportunity specialist if enabled and the meeting type warrants it."""
        if self._opp_specialist_subscriber is not None:
            return
        if not (self._is_enabled("opportunity_specialist") and self._offering_matching_enabled):
            return
        self._opp_specialist_subscriber = CooldownSubscriber(
            handler=self._run_opportunity_specialist,
            cooldown_seconds=self._get_interval(
                "opportunity_specialist", settings.OPPORTUNITY_SPECIALIST_COOLDOWN_SECONDS
            ),
        )
        self._event_bus.subscribe("new_opportunity", self._opp_specialist_subscriber)

    def _remember_active_question(self, item_id: str, text: str, item_type: str = "question"):
        """Track an open question, dropping the oldest past the cap."""
        self.active_questions.append({"id": item_id, "question": text, "item_type": item_type})
        overflow = len(self.active_questions) - _MAX_ACTIVE_QUESTIONS
        if overflow > 0:
            del self.active_questions[:overflow]

    def _forget_active_question(self, item_id: str | None):
        """Stop carrying a question once it is answered or dismissed."""
        if not item_id:
            return
        self.active_questions[:] = [aq for aq in self.active_questions if aq["id"] != item_id]

    def _remember_board_stub(self, item_type: str, text: str):
        """Track a non-question insight so the analyst stops restating it."""
        text = text.strip()
        if not text:
            return
        if len(text) > _BOARD_STUB_CHARS:
            text = text[:_BOARD_STUB_CHARS].rstrip() + "..."
        self._board_stubs.append({"item_type": item_type, "text": text})
        overflow = len(self._board_stubs) - _MAX_BOARD_STUBS
        if overflow > 0:
            del self._board_stubs[:overflow]

    def _derive_meeting_context(self):
        """Recompute the fields derived from meeting_type/meeting_context."""
        self.meeting_context_text = build_meeting_context_text(self.meeting_type, self.meeting_context)
        self._offering_matching_enabled = should_match_offerings(self.meeting_type)

    def _suppressed_analyst_types(self) -> set[str]:
        """Item types the analyst should not produce for this meeting type.

        Opportunity scouting only pays off when the offering specialist can
        enrich the result. On a meeting type where offering matching is off,
        the lens produced 57 of 199 insights on a measured call and every one
        carried an empty offering_match, so it is dropped from the prompt.
        """
        return set() if self._offering_matching_enabled else {"opportunity"}

    def update_meeting_context(self, meeting_type: str | None = None, meeting_context: str | None = None):
        """Apply a mid-call session context edit to the running text agents."""
        if meeting_type is not None:
            self.meeting_type = normalize_meeting_type(meeting_type)
        if meeting_context is not None:
            self.meeting_context = meeting_context
        self._derive_meeting_context()
        self.consolidated_agent.meeting_context_text = self.meeting_context_text
        self.consolidated_agent.set_suppressed_types(self._suppressed_analyst_types())
        self.objection_agent.update_meeting_context(self.meeting_context_text)
        # If the type change turned offering matching on, the specialist may not be wired yet.
        self._wire_opportunity_specialist()
        if self._is_enabled("opportunity_specialist"):
            if self._offering_matching_enabled:
                asyncio.create_task(
                    self.activity.set_agent_state(
                        "opportunity_specialist",
                        "waiting",
                    )
                )
            else:
                asyncio.create_task(
                    self.activity.set_agent_state(
                        "opportunity_specialist",
                        "blocked",
                        blocked_reason="meeting_type",
                        remedy=(
                            "Runs for client/sales and customer delivery conversations; "
                            "change the conversation type to enable it."
                        ),
                    )
                )
        logger.info(
            f"[orchestrator] meeting context updated mid-call: type={self.meeting_type} "
            f"offering_matching={self._offering_matching_enabled}"
        )

    async def send_audio(self, pcm_data: bytes):
        if self._is_enabled("audio_gateway"):
            await self.audio_gateway.send_audio(pcm_data)

    async def feed_transcript(
        self,
        text: str,
        speaker_name: str | None = None,
        speaker_id: str | None = None,
        speaker_type: str | None = None,
    ):
        await self.transcript_buffer.add(
            text,
            speaker_name,
            speaker_id=speaker_id,
            speaker_type=speaker_type,
        )

    async def send_directive(self, text: str):
        self.directives.append(text)

    async def check_health(self) -> bool:
        if not self._is_enabled("audio_gateway"):
            return True
        if self._gateway_task is None:
            return False
        if self._gateway_task.done():
            exc = (
                self._gateway_task.exception()
                if not self._gateway_task.cancelled()
                else None
            )
            if exc:
                logger.warning("Audio Gateway died: %s", exc)
            else:
                logger.warning("Audio Gateway ended")
            return False
        return True

    def _unregister_live(self):
        # Guarded so a newer orchestrator registered for the same session survives.
        if _live_orchestrators.get(self.session_id) is self:
            del _live_orchestrators[self.session_id]

    async def close_all(self):
        self._stopped = True
        self._unregister_live()
        clear_synthesizer_state(self.session_id)

        # Stop cooldown subscribers
        if self._synth_subscriber:
            self._synth_subscriber.stop()
        if self._opp_specialist_subscriber:
            self._opp_specialist_subscriber.stop()
        self._event_bus.clear()

        # Cancel tasks
        for task in [
            self._consolidated_task,
            self._objection_task,
            self._gateway_task,
            self._strategic_signals_task,
            self._refiner_task,
        ]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if self.audio_gateway:
            await self.audio_gateway.close()
        await self.activity.close()
        logger.info("Orchestrator shut down")

    async def graceful_drain(
        self,
        progress_callback: ProgressCallback | None = None,
        mode: str = DRAIN_MODE_FULL,
    ) -> dict[str, int | bool]:
        """Run the drain, keeping the client informed while a stage is slow.

        A single agent stage can run for minutes - one Gemini call hung nearly
        four on a malformed structured reply - and nothing crossed the socket
        while it did, so the client could not tell a working drain from a dead
        backend and gave up on it (ALP-171). Re-announcing the running stage on
        an interval gives the client something to wait on.
        """
        if progress_callback is None:
            return await self._run_drain_stages(None, mode)

        latest: dict[str, dict] = {}

        async def tracked(event: dict) -> None:
            latest["event"] = event
            await progress_callback(event)

        heartbeat = asyncio.create_task(_run_drain_heartbeat(progress_callback, latest))
        try:
            return await self._run_drain_stages(tracked, mode)
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):
                pass

    async def _run_drain_stages(
        self,
        progress_callback: ProgressCallback | None = None,
        mode: str = DRAIN_MODE_FULL,
    ) -> dict[str, int | bool]:
        """Run final text-agent passes before shutting down a live call.

        mode selects how much analysis runs (see drain_stages); per-agent
        enablement still applies within each mode.
        """
        self._stopped = True
        # Unregister up front: mid-drain context edits are pointless (loops are
        # stopping), and a drain error must not leave a dead entry in the registry.
        self._unregister_live()

        if self._synth_subscriber:
            self._synth_subscriber.stop()
        if self._opp_specialist_subscriber:
            self._opp_specialist_subscriber.stop()
        self._event_bus.clear()

        if self._consolidated_task and not self._consolidated_task.done():
            self._consolidated_task.cancel()
            try:
                await self._consolidated_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._objection_task and not self._objection_task.done():
            self._objection_task.cancel()
            try:
                await self._objection_task
            except (asyncio.CancelledError, Exception):
                pass
        if (
            self._strategic_signals_task
            and not self._strategic_signals_task.done()
        ):
            self._strategic_signals_task.cancel()
            try:
                await self._strategic_signals_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._refiner_task and not self._refiner_task.done():
            self._refiner_task.cancel()
            try:
                await self._refiner_task
            except (asyncio.CancelledError, Exception):
                pass

        result: dict = {
            "transcript_available": False,
            "insights_saved": 0,
            "synthesizer_ops": 0,
            "opportunity_ops": 0,
            # Stages that failed. The drain already degrades past a failure and
            # the call still finalizes, but until this was reported the client
            # saw only counts, so a failed briefing was indistinguishable from a
            # clean finish - and a slow one from a stranded call.
            "stage_errors": [],
        }

        stages = self.drain_stages(mode)
        drain_total_steps = 2 + len(stages)
        if "call_briefing" in stages:
            result["synthesis_generated"] = False

        transcript_window = await self.transcript_buffer.get_window()
        transcript_available = transcript_window != "(No recent transcript)"
        result["transcript_available"] = transcript_available

        await self._run_transcript_refinement_stage(
            stages,
            progress_callback,
            drain_total_steps,
            result,
        )
        await self._run_final_insights_stage(
            stages,
            progress_callback,
            drain_total_steps,
            transcript_window,
            transcript_available,
            result,
        )
        await self._run_insight_reconciliation_stage(
            stages,
            progress_callback,
            drain_total_steps,
            result,
        )
        await self._run_opportunity_matching_stage(
            stages,
            progress_callback,
            drain_total_steps,
            result,
        )
        await self._run_call_briefing_stage(
            stages,
            progress_callback,
            drain_total_steps,
            result,
        )

        logger.info(
            "Graceful drain complete: "
            f"transcript={result['transcript_available']} "
            f"insights={result['insights_saved']} "
            f"synth_ops={result['synthesizer_ops']} "
            f"opp_ops={result['opportunity_ops']}"
        )
        return result

    async def _run_final_insights_stage(
        self,
        stages: list[str],
        progress_callback: ProgressCallback | None,
        drain_total_steps: int,
        transcript_window: str,
        transcript_available: bool,
        result: dict,
    ) -> None:
        if not (
            "final_insights" in stages
            and transcript_available
            and self._is_enabled("consolidated_analyst")
            and self.consolidated_agent.enabled_types
        ):
            return
        stage_step = 2 + stages.index("final_insights")
        await _emit_progress(
            progress_callback,
            "final_insights",
            "Running final insight pass...",
            stage_step,
            drain_total_steps,
            drain_progress_percent(stage_step, drain_total_steps),
        )
        await self.activity.cycle_started("consolidated_analyst")
        try:
            insights = await self.consolidated_agent.run_cycle(
                transcript_window=transcript_window,
                directives=self.directives,
                doc_summaries=self.doc_summaries,
                speakers=self.speakers,
                active_questions=self.active_questions,
                board_notes=self._board_stubs,
            )

            for insight in insights:
                agent_source = insight.get("agent_source", "consolidated_analyst")
                saved = await self._save_and_send_insight(insight, agent_source=agent_source)
                if saved:
                    result["insights_saved"] = int(result["insights_saved"]) + 1

            if insights:
                logger.info(f"[consolidated_analyst] final drain produced {len(insights)} insights")
            last_outcome = self.consolidated_agent.last_outcome or {}
            if last_outcome.get("kind") == "error":
                await self.activity.cycle_error(
                    "consolidated_analyst",
                    last_outcome["error"],
                )
            else:
                await self.activity.cycle_finished(
                    "consolidated_analyst",
                    saved_outcome(
                        last_outcome,
                        produced=len(insights),
                        saved=int(result["insights_saved"]),
                    ),
                )
        except Exception as e:
            logger.error(f"Final consolidated analyst drain error: {e}")
            result["stage_errors"].append(
                {"stage": "final_insights", "detail": str(e)}
            )
            await self.activity.cycle_error(
                "consolidated_analyst",
                classify_error(e, self._get_model("consolidated_analyst")),
            )

    async def _run_insight_reconciliation_stage(
        self,
        stages: list[str],
        progress_callback: ProgressCallback | None,
        drain_total_steps: int,
        result: dict,
    ) -> None:
        if (
            "insight_reconciliation" not in stages
            or not self._is_enabled("synthesizer")
        ):
            return
        stage_step = 2 + stages.index("insight_reconciliation")
        await _emit_progress(
            progress_callback,
            "insight_reconciliation",
            "Reconciling and enriching saved insights...",
            stage_step,
            drain_total_steps,
            drain_progress_percent(stage_step, drain_total_steps),
        )
        await self.activity.cycle_started("synthesizer")
        try:
            applied_ops = await run_synthesizer_cycle(
                self.session_id,
                model_override=self._get_model("synthesizer"),
                prompt_override=self._get_prompt("synthesizer") or None,
            )
            result["synthesizer_ops"] = len(applied_ops)
            await self._broadcast_operation_results(applied_ops)
            await self.activity.cycle_finished(
                "synthesizer",
                {
                    "kind": "insights" if applied_ops else "no_findings",
                    "detail": (
                        f"{len(applied_ops)} insight operations applied"
                        if applied_ops
                        else "No saved insight needed reconciliation."
                    ),
                    "items": len(applied_ops),
                },
            )
        except Exception as e:
            logger.error(f"Final synthesizer drain error: {e}")
            result["stage_errors"].append(
                {"stage": "insight_reconciliation", "detail": str(e)}
            )
            await self.activity.cycle_error(
                "synthesizer",
                classify_error(e, self._get_model("synthesizer")),
            )

    async def _run_opportunity_matching_stage(
        self,
        stages: list[str],
        progress_callback: ProgressCallback | None,
        drain_total_steps: int,
        result: dict,
    ) -> None:
        if (
            "opportunity_matching" not in stages
            or not self._is_enabled("opportunity_specialist")
            or not self._offering_matching_enabled
        ):
            return
        stage_step = 2 + stages.index("opportunity_matching")
        await _emit_progress(
            progress_callback,
            "opportunity_matching",
            "Matching opportunities to the offerings catalog...",
            stage_step,
            drain_total_steps,
            drain_progress_percent(stage_step, drain_total_steps),
        )
        await self.activity.cycle_started("opportunity_specialist")
        try:
            applied_ops = await run_opportunity_specialist_cycle(
                self.session_id,
                model_override=self._get_model("opportunity_specialist"),
                knowledge_source_ids=self._get_knowledge_source_ids(
                    "opportunity_specialist"
                ),
            )
            result["opportunity_ops"] = len(applied_ops)
            await self._broadcast_operation_results(applied_ops)
            await self.activity.cycle_finished(
                "opportunity_specialist",
                {
                    "kind": "insights" if applied_ops else "no_findings",
                    "detail": (
                        f"{len(applied_ops)} opportunity matches applied"
                        if applied_ops
                        else "No offering match was found."
                    ),
                    "items": len(applied_ops),
                },
            )
        except Exception as e:
            logger.error(f"Final opportunity specialist drain error: {e}")
            result["stage_errors"].append(
                {"stage": "opportunity_matching", "detail": str(e)}
            )
            await self.activity.cycle_error(
                "opportunity_specialist",
                classify_error(e, self._get_model("opportunity_specialist")),
            )

    async def _run_call_briefing_stage(
        self,
        stages: list[str],
        progress_callback: ProgressCallback | None,
        drain_total_steps: int,
        result: dict,
    ) -> None:
        if "call_briefing" not in stages:
            return
        stage_step = 2 + stages.index("call_briefing")
        await _emit_progress(
            progress_callback,
            "call_briefing",
            "Settling the call briefing...",
            stage_step,
            drain_total_steps,
            drain_progress_percent(stage_step, drain_total_steps),
        )
        briefing_slugs = [
            record["slug"]
            for record in self.activity.snapshot()["agents"]
            if record["trigger"] == "post_call"
            and record["state"] not in {"off", "blocked"}
        ]
        for slug in briefing_slugs:
            await self.activity.cycle_started(slug)
        try:
            synthesis = await run_session_synthesis(
                self.session_id,
                mode="post_call",
                agent_configs=self._agent_configs,
            )
            result["synthesis_generated"] = synthesis is not None
            if synthesis:
                await self._send_synthesis_update(synthesis)
            for slug in briefing_slugs:
                await self.activity.cycle_finished(
                    slug,
                    {
                        "kind": "insights" if synthesis else "no_findings",
                        "detail": (
                            "Call briefing generated."
                            if synthesis
                            else "No call briefing was generated."
                        ),
                        "items": 1 if synthesis else 0,
                    },
                )
        except Exception as e:
            logger.error(f"Final briefing synthesis error: {e}")
            result["stage_errors"].append(
                {"stage": "call_briefing", "detail": str(e)}
            )
            for slug in briefing_slugs:
                await self.activity.cycle_error(
                    slug,
                    classify_error(e, self._get_model(slug)),
                )

    # ── Audio Gateway (silent listener) ──────────────────────────────────

    async def _handle_gateway_responses(self):
        """Relay input_transcription from the audio gateway to the frontend."""
        async for event in self.audio_gateway.receive_responses():
            if event["type"] == "transcript":
                try:
                    await self.websocket.send_json({
                        "type": "interim_transcript",
                        "data": {"text": event["data"]},
                    })
                except Exception:
                    pass

    # ── Save + broadcast (shared by all agents) ─────────────────────────

    async def _save_and_send_insight(self, q_json: dict, agent_source: str) -> bool:
        """Save a new insight. Returns True if saved (not deduped)."""
        if "question" not in q_json:
            return False

        text = q_json["question"]

        # Dedup check
        now = time.time()
        self._recent_insights = {
            k: v for k, v in self._recent_insights.items()
            if now - v < _DEDUP_WINDOW_SECONDS
        }
        for existing_text in self._recent_insights:
            if _texts_similar(text, existing_text):
                logger.info(f"[{agent_source}] Skipping near-duplicate: {text[:60]}")
                return False
        self._recent_insights[text] = now

        # Use agent_source from the insight dict if provided (consolidated analyst sets per-type)
        effective_source = q_json.get("agent_source", agent_source)
        speaker_id = self._validated_speaker_id(q_json.get("speaker_id"))

        async with async_session() as db:
            directive_id = None
            directive_source = q_json.get("directive_source")
            if directive_source:
                result = await db.execute(
                    select(Directive.id).where(
                        Directive.session_id == self.session_id,
                        Directive.text == directive_source,
                    )
                )
                directive_id = result.scalar_one_or_none()

            question = Question(
                session_id=self.session_id,
                item_type=q_json.get("item_type", "question"),
                lens_label=str(q_json.get("lens_label") or "")[:120],
                question=text,
                rationale=q_json.get("rationale", ""),
                source_context=q_json.get("source_context", ""),
                speaker_id=uuid.UUID(speaker_id) if speaker_id else None,
                directive_id=directive_id,
                agent_source=effective_source,
            )
            db.add(question)
            await db.commit()
            await db.refresh(question)

            if question.item_type == "question":
                self._remember_active_question(str(question.id), question.question, question.item_type)
            else:
                self._remember_board_stub(question.item_type, question.question)

            try:
                await self.websocket.send_json({
                    "type": "question",
                    "data": {
                        "id": str(question.id),
                        "item_type": question.item_type,
                        "lens_label": question.lens_label,
                        "question": question.question,
                        "rationale": question.rationale,
                        "source_context": question.source_context,
                        "speaker_id": speaker_id,
                        "directive_id": str(question.directive_id) if question.directive_id else None,
                        "is_followup": False,
                        "timestamp": question.created_at.isoformat(),
                        "agent_source": effective_source,
                        "offering_match": "",
                        "enhanced": False,
                    },
                })
            except Exception as e:
                logger.info(f"[{effective_source}] Insight saved but websocket broadcast failed: {e}")

            return True

    async def _send_signal_insights(self, signal_rows: dict | None) -> int:
        """Push this cycle's signal insight rows to the browser.

        New rows arrive as ordinary insights; a signal that aged into history,
        or came back, arrives as an update to the row already on screen.
        """
        if not signal_rows:
            return 0

        created = signal_rows.get("created") or []
        updated = signal_rows.get("updated") or []
        for message_type, rows in (("question", created), ("insight_updated", updated)):
            for row in rows:
                try:
                    await self.websocket.send_json({"type": message_type, "data": row})
                except Exception as e:
                    logger.info(f"[strategic_signals] signal insight broadcast failed: {e}")
                    return len(created)
        return len(created)

    def _validated_speaker_id(self, raw: object) -> str | None:
        """Keep insight attribution tied to the session speaker roster."""
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            speaker_id = str(uuid.UUID(raw.strip()))
        except ValueError:
            return None
        known_ids = {str(s.get("id")) for s in self.speakers if s.get("id")}
        return speaker_id if speaker_id in known_ids else None

    # ── Consolidated Analyst (single batch call) ─────────────────────────

    async def _consolidated_agent_loop(self):
        """Run consolidated analyst on interval."""
        interval = self._get_interval("consolidated_analyst", settings.TEXT_AGENT_INTERVAL_SECONDS)
        await asyncio.sleep(interval)

        last_window = ""
        while not self._stopped:
            await self.activity.cycle_started("consolidated_analyst")
            try:
                transcript_window = await self.transcript_buffer.get_window()
                if transcript_window == "(No recent transcript)":
                    logger.debug("[consolidated_analyst] No transcript yet, skipping cycle")
                    await self.activity.cycle_finished(
                        "consolidated_analyst",
                        {
                            "kind": "skipped_no_transcript",
                            "detail": "Nothing to analyze yet.",
                            "items": 0,
                        },
                    )
                    await asyncio.sleep(interval)
                    continue
                # Nobody spoke since the last cycle: the model has already read
                # exactly this window, so re-reading it buys nothing. Mirrors the
                # guard the objection handler has always had.
                if transcript_window == last_window:
                    logger.debug("[consolidated_analyst] Window unchanged, skipping cycle")
                    await asyncio.sleep(interval)
                    continue
                last_window = transcript_window

                logger.info(f"[consolidated_analyst] Running cycle with {len(transcript_window)} chars of transcript")
                insights = await self.consolidated_agent.run_cycle(
                    transcript_window=transcript_window,
                    directives=self.directives,
                    doc_summaries=self.doc_summaries,
                    speakers=self.speakers,
                    active_questions=self.active_questions,
                )

                saved_count = 0
                for insight in insights:
                    agent_source = insight.get("agent_source", "consolidated_analyst")
                    saved = await self._save_and_send_insight(insight, agent_source=agent_source)
                    if saved:
                        saved_count += 1
                        item_type = insight.get("item_type", "")
                        self._event_bus.publish("new_insight", {
                            "item_type": item_type,
                            "agent_source": agent_source,
                        })
                        if item_type == "opportunity" and self._offering_matching_enabled:
                            self._event_bus.publish("new_opportunity", {
                                "agent_source": agent_source,
                            })

                if insights:
                    logger.info(f"[consolidated_analyst] produced {len(insights)} insights")
                last_outcome = self.consolidated_agent.last_outcome or {}
                if last_outcome.get("kind") == "error":
                    await self.activity.cycle_error(
                        "consolidated_analyst",
                        last_outcome["error"],
                    )
                else:
                    await self.activity.cycle_finished(
                        "consolidated_analyst",
                        saved_outcome(
                            last_outcome,
                            produced=len(insights),
                            saved=saved_count,
                        ),
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Consolidated analyst loop error: {e}")
                await self.activity.cycle_error(
                    "consolidated_analyst",
                    classify_error(e, self._get_model("consolidated_analyst")),
                )

            await asyncio.sleep(interval)

    async def _objection_agent_loop(self):
        """Fast scan loop: short transcript window, low-latency model, immediate surfacing."""
        interval = self._get_interval("objection_handler", settings.OBJECTION_HANDLER_INTERVAL_SECONDS)
        await asyncio.sleep(interval)

        while not self._stopped:
            await self.activity.cycle_started("objection_handler")
            try:
                transcript_window = await self.transcript_buffer.get_window(
                    max_age_seconds=settings.OBJECTION_WINDOW_SECONDS
                )
                if transcript_window != "(No recent transcript)":
                    insights = await self.objection_agent.run_cycle(
                        transcript_window=transcript_window,
                        directives=self.directives,
                        speakers=self.speakers,
                    )

                    saved_count = 0
                    for insight in insights:
                        saved = await self._save_and_send_insight(insight, agent_source="objection_handler")
                        if saved:
                            saved_count += 1
                            self._event_bus.publish("new_insight", {
                                "item_type": "objection",
                                "agent_source": "objection_handler",
                            })
                    last_outcome = self.objection_agent.last_outcome or {}
                    if last_outcome.get("kind") == "error":
                        await self.activity.cycle_error(
                            "objection_handler",
                            last_outcome["error"],
                        )
                    else:
                        await self.activity.cycle_finished(
                            "objection_handler",
                            saved_outcome(
                                last_outcome,
                                produced=len(insights),
                                saved=saved_count,
                            ),
                        )
                else:
                    await self.activity.cycle_finished(
                        "objection_handler",
                        {
                            "kind": "skipped_no_transcript",
                            "detail": "Nothing to scan yet.",
                            "items": 0,
                        },
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Objection handler loop error: {e}")
                await self.activity.cycle_error(
                    "objection_handler",
                    classify_error(e, self._get_model("objection_handler")),
                )

            await asyncio.sleep(interval)

    async def _refine_recent_transcript(self, *, limit: int | None, source_label: str) -> int:
        """Refine pending entries and push each rewrite to the interface."""
        from app.database import async_session

        model_id = self._get_model(TRANSCRIPT_REFINER_SLUG)
        async with async_session() as db:
            changed = await refine_session(db, self.session_id, model_id, limit=limit)
            payloads = [refiner_update_payload(entry) for entry in changed]
            await db.commit()
        for payload in payloads:
            try:
                await self.websocket.send_json({"type": "transcript_updated", "data": payload})
            except Exception:  # noqa: BLE001 - a closed socket must not stop the pass
                break
        if payloads:
            logger.info("[%s] refined %d transcript entries", source_label, len(payloads))
        return len(payloads)

    async def _transcript_refiner_loop(self):
        interval = self._get_interval(TRANSCRIPT_REFINER_SLUG, 45)
        await asyncio.sleep(interval)
        while not self._stopped:
            await self.activity.cycle_started(TRANSCRIPT_REFINER_SLUG)
            try:
                count = await self._refine_recent_transcript(limit=REFINER_LIVE_WINDOW, source_label="transcript_refiner")
                await self.activity.cycle_finished(
                    TRANSCRIPT_REFINER_SLUG,
                    {
                        "kind": "insights" if count else "no_findings",
                        "detail": f"{count} transcript lines refined." if count else "Nothing new to refine.",
                        "items": count,
                    },
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Transcript refiner loop error: {e}")
                await self.activity.cycle_error(
                    TRANSCRIPT_REFINER_SLUG,
                    classify_error(e, self._get_model(TRANSCRIPT_REFINER_SLUG)),
                )
            await asyncio.sleep(interval)

    async def _run_transcript_refinement_stage(
        self,
        stages: list[str],
        progress_callback,
        drain_total_steps: int,
        result: dict,
    ) -> None:
        if "transcript_refinement" not in stages:
            return
        step = 1 + stages.index("transcript_refinement")
        await _emit_progress(
            progress_callback,
            "transcript_refinement",
            "Refining the transcript wording",
            drain_progress_percent(step, drain_total_steps),
        )
        await self.activity.cycle_started(TRANSCRIPT_REFINER_SLUG)
        try:
            count = await self._refine_recent_transcript(limit=None, source_label="transcript_refinement")
            result["transcript_refined"] = count
            await self.activity.cycle_finished(
                TRANSCRIPT_REFINER_SLUG,
                {"kind": "insights" if count else "no_findings", "detail": f"{count} lines refined at call end.", "items": count},
            )
        except Exception as e:  # noqa: BLE001 - the drain degrades past a failed stage
            logger.error(f"Transcript refinement stage failed: {e}")
            result["stage_errors"].append({"stage": "transcript_refinement", "error": str(e)})
            await self.activity.cycle_error(
                TRANSCRIPT_REFINER_SLUG,
                classify_error(e, self._get_model(TRANSCRIPT_REFINER_SLUG)),
            )

    async def _strategic_signals_loop(self):
        interval = self._get_interval(STRATEGIC_SIGNALS_SLUG, 45)
        await asyncio.sleep(interval)
        last_window = ""
        while not self._stopped:
            await self.activity.cycle_started(STRATEGIC_SIGNALS_SLUG)
            try:
                transcript_window = await self.transcript_buffer.get_window()
                if transcript_window == last_window:
                    logger.debug("[strategic_signals] Window unchanged, skipping cycle")
                elif transcript_window != "(No recent transcript)":
                    last_window = transcript_window
                    cycle = await run_strategic_signals_cycle(
                        self.session_id,
                        agent_configs=self._agent_configs,
                        transcript_window=transcript_window,
                        directives=self.directives,
                        doc_summaries=self.doc_summaries,
                        speakers=self.speakers,
                        active_questions=self.active_questions,
                    )
                    synthesis, signal_rows = cycle if cycle else (None, None)
                    if synthesis:
                        await self._send_synthesis_update(synthesis)
                    filed = await self._send_signal_insights(signal_rows)
                    await self.activity.cycle_finished(
                        STRATEGIC_SIGNALS_SLUG,
                        {
                            "kind": "insights" if synthesis else "no_findings",
                            "detail": (
                                f"Live strategic signals updated; {filed} filed as insights."
                                if synthesis and filed
                                else "Live strategic signals updated."
                                if synthesis
                                else "No strategic signal changed."
                            ),
                            "items": 1 if synthesis else 0,
                        },
                    )
                else:
                    await self.activity.cycle_finished(
                        STRATEGIC_SIGNALS_SLUG,
                        {
                            "kind": "skipped_no_transcript",
                            "detail": "Nothing to analyze yet.",
                            "items": 0,
                        },
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Strategic signals loop error: {e}")
                await self.activity.cycle_error(
                    STRATEGIC_SIGNALS_SLUG,
                    classify_error(e, self._get_model(STRATEGIC_SIGNALS_SLUG)),
                )
            await asyncio.sleep(interval)

    async def _send_synthesis_update(self, synthesis):
        try:
            await self.websocket.send_json({
                "type": "synthesis_updated",
                "data": _synthesis_payload(synthesis),
            })
        except Exception:
            pass

    # ── Event-driven: Synthesizer ────────────────────────────────────────

    async def _run_synthesizer(self, events: list[dict]):
        """Called by CooldownSubscriber when new_insight events arrive."""
        await self.activity.cycle_started("synthesizer")
        try:
            logger.info(f"Running synthesizer (triggered by {len(events)} events)")
            applied_ops = await run_synthesizer_cycle(
                self.session_id,
                model_override=self._get_model("synthesizer"),
                prompt_override=self._get_prompt("synthesizer") or None,
            )

            await self._broadcast_operation_results(applied_ops)

            if applied_ops:
                logger.info(f"Synthesizer applied {len(applied_ops)} operations")
            await self.activity.cycle_finished(
                "synthesizer",
                {
                    "kind": "insights" if applied_ops else "no_findings",
                    "detail": (
                        f"{len(applied_ops)} insight operation"
                        f"{'s' if len(applied_ops) != 1 else ''} applied"
                        if applied_ops
                        else "No saved insight needed reconciliation."
                    ),
                    "items": len(applied_ops),
                },
            )

        except Exception as e:
            logger.error(f"Synthesizer cycle error: {e}")
            await self.activity.cycle_error(
                "synthesizer",
                classify_error(e, self._get_model("synthesizer")),
            )

    # ── Event-driven: Opportunity Specialist ──────────────────────────────

    async def _run_opportunity_specialist(self, events: list[dict]):
        """Called by CooldownSubscriber when new_opportunity events arrive."""
        await self.activity.cycle_started("opportunity_specialist")
        try:
            logger.info(f"Running opportunity specialist (triggered by {len(events)} events)")
            applied_ops = await run_opportunity_specialist_cycle(
                self.session_id,
                model_override=self._get_model("opportunity_specialist"),
                knowledge_source_ids=self._get_knowledge_source_ids("opportunity_specialist"),
            )

            await self._broadcast_operation_results(applied_ops)
            await self.activity.cycle_finished(
                "opportunity_specialist",
                {
                    "kind": "insights" if applied_ops else "no_findings",
                    "detail": (
                        f"{len(applied_ops)} opportunity match"
                        f"{'es' if len(applied_ops) != 1 else ''} applied"
                        if applied_ops
                        else "No offering match was found."
                    ),
                    "items": len(applied_ops),
                },
            )

        except Exception as e:
            logger.error(f"Opportunity specialist cycle error: {e}")
            await self.activity.cycle_error(
                "opportunity_specialist",
                classify_error(e, self._get_model("opportunity_specialist")),
            )

    async def _broadcast_operation_results(self, applied_ops: list[dict]):
        for op_result in applied_ops:
            ws_type = op_result.get("ws_type")
            ws_data = op_result.get("ws_data")
            if ws_type and ws_data:
                try:
                    await self.websocket.send_json({
                        "type": ws_type,
                        "data": ws_data,
                    })
                except Exception:
                    pass

            op_name = op_result.get("op")
            if op_name in ("answer", "dismiss", "merge"):
                # A merged-away or dismissed question is as closed as an
                # answered one; only "answer" used to prune, so the rest
                # accumulated for the rest of the call.
                self._forget_active_question(op_result.get("id"))
                self._forget_active_question(op_result.get("remove_id"))
            elif op_name == "create" and ws_data:
                if (ws_data.get("item_type") or "question") == "question":
                    self._remember_active_question(
                        ws_data["id"], ws_data["question"], ws_data.get("item_type") or "question"
                    )

    # ── Reconnection ─────────────────────────────────────────────────────

    async def _reconnect_gateway(self) -> bool:
        if self.audio_gateway is None:
            return False
        try:
            if self._gateway_task and not self._gateway_task.done():
                self._gateway_task.cancel()
                try:
                    await self._gateway_task
                except (asyncio.CancelledError, Exception):
                    pass
            await self.audio_gateway.close()
        except Exception:
            pass

        try:
            await self.audio_gateway.connect()
            self._gateway_task = asyncio.create_task(self._handle_gateway_responses())
            return True
        except Exception as e:
            logger.error(f"Audio Gateway reconnect failed: {e}")
            return False


def _synthesis_payload(synthesis) -> dict:
    return {
        "id": str(synthesis.id),
        "session_id": str(synthesis.session_id),
        "mode": synthesis.mode,
        "status": synthesis.status,
        "top_outcomes": synthesis.top_outcomes or [],
        "client_objectives": synthesis.client_objectives or [],
        "top_opportunities": synthesis.top_opportunities or [],
        "risks_blockers": synthesis.risks_blockers or [],
        "action_plan": synthesis.action_plan or [],
        "unresolved_discovery_questions": synthesis.unresolved_discovery_questions or [],
        "strategic_signals": synthesis.strategic_signals or [],
        # Kept signals reach the live call view as insight rows now (ALP-308),
        # so only the count travels here; the rows themselves are fetched on
        # demand by the post-call history panel.
        "signal_history_count": len(synthesis.signal_history or []),
        "evidence_refs": synthesis.evidence_refs or [],
        "lens_meeting": synthesis.lens_meeting or {},
        "lens_discovery": synthesis.lens_discovery or {},
        "arbiter_notes": synthesis.arbiter_notes or "",
        "model_ids": synthesis.model_ids or {},
        "error_message": synthesis.error_message or "",
        "created_at": synthesis.created_at.isoformat(),
        "updated_at": synthesis.updated_at.isoformat() if synthesis.updated_at else None,
        "clusters": [
            {
                "id": str(cluster.id),
                "synthesis_id": str(cluster.synthesis_id),
                "session_id": str(cluster.session_id),
                "title": cluster.title,
                "summary": cluster.summary,
                "priority": cluster.priority,
                "confidence": cluster.confidence,
                "related_question_ids": cluster.related_question_ids or [],
                "evidence_refs": cluster.evidence_refs or [],
                "created_at": cluster.created_at.isoformat(),
            }
            for cluster in getattr(synthesis, "clusters", [])
        ],
    }

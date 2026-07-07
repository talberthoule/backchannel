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
from app.services.agents.base import TranscriptBuffer
from app.services.agents.consolidated_analyst import ConsolidatedAnalystAgent
from app.services.agents.event_bus import CooldownSubscriber, EventBus
from app.services.agents.objection_handler import ObjectionHandlerAgent
from app.services.agents.opportunity_specialist import run_opportunity_specialist_cycle
from app.services.agents.synthesizer import run_synthesizer_cycle
from app.services.briefing_synthesis import (
    BRIEF_ARBITER_SLUG,
    LIVE_SYNTHESIS_INTERVAL_SECONDS,
    agent_config_enabled,
    run_session_synthesis,
)
from app.services.gemini_live import GeminiLiveSession
from app.services.llm import provider_for
from app.services.openai_realtime import OpenAIRealtimeSession
from app.services.meeting_context import build_meeting_context_text, normalize_meeting_type, should_match_offerings

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_SECONDS = 60
ProgressCallback = Callable[[dict[str, object]], Awaitable[None]]


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
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.directives = directives
        self.doc_summaries = doc_summaries
        self.active_questions = active_questions
        self.speakers = speakers
        self._agent_configs = agent_configs or {}
        self.local_only = local_only
        self.meeting_type = normalize_meeting_type(meeting_type)
        self.meeting_context = meeting_context
        self.meeting_context_text = build_meeting_context_text(self.meeting_type, meeting_context)
        self._offering_matching_enabled = should_match_offerings(self.meeting_type)

        def _get_model(slug: str, fallback: str = "") -> str:
            cfg = self._agent_configs.get(slug)
            return cfg.model_id if cfg else fallback

        # Helper to check if an agent is enabled (DB config with fallback).
        # In Privacy First (local-only) mode an agent also needs a local model;
        # today none of the agents have one, so all of them sit out.
        def _is_enabled(slug: str, fallback: bool = True) -> bool:
            cfg = self._agent_configs.get(slug)
            enabled = cfg.enabled if cfg else fallback
            if enabled and self.local_only:
                return provider_for(_get_model(slug)) == "local"
            return enabled

        def _get_prompt(slug: str) -> str:
            cfg = self._agent_configs.get(slug)
            return cfg.prompt if cfg else ""

        def _get_interval(slug: str, fallback: int) -> int:
            cfg = self._agent_configs.get(slug)
            return cfg.interval_seconds if cfg and cfg.interval_seconds else fallback

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
        self._get_model = _get_model
        self._get_prompt = _get_prompt
        self._get_interval = _get_interval
        self._get_knowledge_source_ids = _get_knowledge_source_ids

        # Audio Gateway (native-audio model — silent listener only)
        gw_model = _get_model("audio_gateway", settings.GEMINI_MODEL)
        if provider_for(gw_model) == "openai":
            self.audio_gateway = OpenAIRealtimeSession(model_override=gw_model)
        else:
            self.audio_gateway = GeminiLiveSession(model_override=gw_model)

        # Consolidated text analyst (includes question generation)
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

        ca_model = _get_model("consolidated_analyst", settings.REFINEMENT_MODEL)
        self.consolidated_agent = ConsolidatedAnalystAgent(
            enabled_types=enabled_types or None,
            model_override=ca_model,
            prompt_override=_get_prompt("consolidated_analyst") or None,
            meeting_context_text=self.meeting_context_text,
            lenses=ca_lenses,
        )

        # Objection handler (fast scan loop over the freshest transcript)
        self.objection_agent = ObjectionHandlerAgent(
            model_override=_get_model("objection_handler", "") or None,
            prompt_override=_get_prompt("objection_handler") or None,
            meeting_context_text=self.meeting_context_text,
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
        self._briefing_task: asyncio.Task | None = None
        self._stopped = False

        # Recent insights for dedup (text -> timestamp)
        self._recent_insights: dict[str, float] = {}

    def briefing_enabled(self) -> bool:
        # Briefing lenses/arbiter call Gemini directly, so local-only mode skips them.
        return not self.local_only and agent_config_enabled(self._agent_configs, BRIEF_ARBITER_SLUG)

    async def start(self):
        """Connect all agents and wire event subscriptions."""
        # --- Audio Gateway (silent listener) ---
        if self._is_enabled("audio_gateway"):
            try:
                await self.audio_gateway.connect()
                self._gateway_task = asyncio.create_task(self._handle_gateway_responses())
            except Exception as e:
                logger.error(f"Audio gateway unavailable, continuing without interim transcription: {e}")

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
        if self._is_enabled("opportunity_specialist") and self._offering_matching_enabled:
            self._opp_specialist_subscriber = CooldownSubscriber(
                handler=self._run_opportunity_specialist,
                cooldown_seconds=self._get_interval(
                    "opportunity_specialist", settings.OPPORTUNITY_SPECIALIST_COOLDOWN_SECONDS
                ),
            )
            self._event_bus.subscribe("new_opportunity", self._opp_specialist_subscriber)

        if self.briefing_enabled():
            self._briefing_task = asyncio.create_task(self._live_briefing_loop())

        ca_interval = self._get_interval("consolidated_analyst", settings.TEXT_AGENT_INTERVAL_SECONDS)
        logger.info(
            f"Orchestrator started: gateway={self._is_enabled('audio_gateway')} "
            f"consolidated={self._is_enabled('consolidated_analyst')} "
            f"interval={ca_interval}s "
            f"types={self.consolidated_agent.enabled_types} "
            f"objection={self._is_enabled('objection_handler')} "
            f"synth={self._is_enabled('synthesizer')}(event-driven) "
            f"opp_specialist={self._is_enabled('opportunity_specialist')}(event-driven)"
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
        if self._gateway_task and self._gateway_task.done():
            exc = self._gateway_task.exception() if not self._gateway_task.cancelled() else None
            if exc:
                logger.warning(f"Audio Gateway died: {exc}, reconnecting...")
            else:
                logger.warning("Audio Gateway ended, reconnecting...")
            return await self._reconnect_gateway()
        return True

    async def close_all(self):
        self._stopped = True

        # Stop cooldown subscribers
        if self._synth_subscriber:
            self._synth_subscriber.stop()
        if self._opp_specialist_subscriber:
            self._opp_specialist_subscriber.stop()
        self._event_bus.clear()

        # Cancel tasks
        for task in [self._consolidated_task, self._objection_task, self._gateway_task, self._briefing_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        await self.audio_gateway.close()
        logger.info("Orchestrator shut down")

    async def graceful_drain(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, int | bool]:
        """Run final text-agent passes before shutting down a live call."""
        self._stopped = True

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
        if self._briefing_task and not self._briefing_task.done():
            self._briefing_task.cancel()
            try:
                await self._briefing_task
            except (asyncio.CancelledError, Exception):
                pass

        result: dict[str, int | bool] = {
            "transcript_available": False,
            "insights_saved": 0,
            "synthesizer_ops": 0,
            "opportunity_ops": 0,
        }
        briefing_enabled = self.briefing_enabled()
        drain_total_steps = 6 if briefing_enabled else 5
        if briefing_enabled:
            result["synthesis_generated"] = False

        transcript_window = await self.transcript_buffer.get_window()
        transcript_available = transcript_window != "(No recent transcript)"
        result["transcript_available"] = transcript_available

        if (
            transcript_available
            and self._is_enabled("consolidated_analyst")
            and self.consolidated_agent.enabled_types
        ):
            await _emit_progress(
                progress_callback,
                "final_insights",
                "Running final insight pass...",
                2,
                drain_total_steps,
                40,
            )
            try:
                insights = await self.consolidated_agent.run_cycle(
                    transcript_window=transcript_window,
                    directives=self.directives,
                    doc_summaries=self.doc_summaries,
                    speakers=self.speakers,
                    active_questions=self.active_questions,
                )

                for insight in insights:
                    agent_source = insight.get("agent_source", "consolidated_analyst")
                    saved = await self._save_and_send_insight(insight, agent_source=agent_source)
                    if saved:
                        result["insights_saved"] = int(result["insights_saved"]) + 1

                if insights:
                    logger.info(f"[consolidated_analyst] final drain produced {len(insights)} insights")
            except Exception as e:
                logger.error(f"Final consolidated analyst drain error: {e}")

        if self._is_enabled("synthesizer"):
            await _emit_progress(
                progress_callback,
                "insight_reconciliation",
                "Reconciling and enriching saved insights...",
                3,
                drain_total_steps,
                65,
            )
            try:
                applied_ops = await run_synthesizer_cycle(
                    self.session_id,
                    model_override=self._get_model("synthesizer", None),
                    prompt_override=self._get_prompt("synthesizer") or None,
                )
                result["synthesizer_ops"] = len(applied_ops)
                await self._broadcast_operation_results(applied_ops)
            except Exception as e:
                logger.error(f"Final synthesizer drain error: {e}")

        if self._is_enabled("opportunity_specialist") and self._offering_matching_enabled:
            await _emit_progress(
                progress_callback,
                "opportunity_matching",
                "Matching opportunities to the offerings catalog...",
                4,
                drain_total_steps,
                80,
            )
            try:
                applied_ops = await run_opportunity_specialist_cycle(
                    self.session_id,
                    model_override=self._get_model("opportunity_specialist", None),
                    knowledge_source_ids=self._get_knowledge_source_ids("opportunity_specialist"),
                )
                result["opportunity_ops"] = len(applied_ops)
                await self._broadcast_operation_results(applied_ops)
            except Exception as e:
                logger.error(f"Final opportunity specialist drain error: {e}")

        if briefing_enabled:
            await _emit_progress(
                progress_callback,
                "call_briefing",
                "Settling the call briefing...",
                5,
                drain_total_steps,
                88,
            )
            try:
                synthesis = await run_session_synthesis(
                    self.session_id,
                    mode="post_call",
                    agent_configs=self._agent_configs,
                )
                result["synthesis_generated"] = synthesis is not None
                if synthesis:
                    await self._send_synthesis_update(synthesis)
            except Exception as e:
                logger.error(f"Final briefing synthesis error: {e}")

        logger.info(
            "Graceful drain complete: "
            f"transcript={result['transcript_available']} "
            f"insights={result['insights_saved']} "
            f"synth_ops={result['synthesizer_ops']} "
            f"opp_ops={result['opportunity_ops']}"
        )
        return result

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
                self.active_questions.append({"id": str(question.id), "question": question.question})

            try:
                await self.websocket.send_json({
                    "type": "question",
                    "data": {
                        "id": str(question.id),
                        "item_type": question.item_type,
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

        while not self._stopped:
            try:
                transcript_window = await self.transcript_buffer.get_window()
                if transcript_window == "(No recent transcript)":
                    logger.debug("[consolidated_analyst] No transcript yet, skipping cycle")
                    await asyncio.sleep(interval)
                    continue

                logger.info(f"[consolidated_analyst] Running cycle with {len(transcript_window)} chars of transcript")
                insights = await self.consolidated_agent.run_cycle(
                    transcript_window=transcript_window,
                    directives=self.directives,
                    doc_summaries=self.doc_summaries,
                    speakers=self.speakers,
                    active_questions=self.active_questions,
                )

                for insight in insights:
                    agent_source = insight.get("agent_source", "consolidated_analyst")
                    saved = await self._save_and_send_insight(insight, agent_source=agent_source)
                    if saved:
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

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Consolidated analyst loop error: {e}")

            await asyncio.sleep(interval)

    async def _objection_agent_loop(self):
        """Fast scan loop: short transcript window, low-latency model, immediate surfacing."""
        interval = self._get_interval("objection_handler", settings.OBJECTION_HANDLER_INTERVAL_SECONDS)
        await asyncio.sleep(interval)

        while not self._stopped:
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

                    for insight in insights:
                        saved = await self._save_and_send_insight(insight, agent_source="objection_handler")
                        if saved:
                            self._event_bus.publish("new_insight", {
                                "item_type": "objection",
                                "agent_source": "objection_handler",
                            })

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Objection handler loop error: {e}")

            await asyncio.sleep(interval)

    async def _live_briefing_loop(self):
        await asyncio.sleep(LIVE_SYNTHESIS_INTERVAL_SECONDS)
        while not self._stopped:
            try:
                transcript_window = await self.transcript_buffer.get_window()
                if transcript_window != "(No recent transcript)":
                    synthesis = await run_session_synthesis(
                        self.session_id,
                        mode="live",
                        agent_configs=self._agent_configs,
                        transcript_window=transcript_window,
                        directives=self.directives,
                        doc_summaries=self.doc_summaries,
                        speakers=self.speakers,
                        active_questions=self.active_questions,
                    )
                    if synthesis:
                        await self._send_synthesis_update(synthesis)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Live briefing loop error: {e}")
            await asyncio.sleep(LIVE_SYNTHESIS_INTERVAL_SECONDS)

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
        try:
            logger.info(f"Running synthesizer (triggered by {len(events)} events)")
            applied_ops = await run_synthesizer_cycle(
                self.session_id,
                model_override=self._get_model("synthesizer", None),
                prompt_override=self._get_prompt("synthesizer") or None,
            )

            await self._broadcast_operation_results(applied_ops)

            if applied_ops:
                logger.info(f"Synthesizer applied {len(applied_ops)} operations")

        except Exception as e:
            logger.error(f"Synthesizer cycle error: {e}")

    # ── Event-driven: Opportunity Specialist ──────────────────────────────

    async def _run_opportunity_specialist(self, events: list[dict]):
        """Called by CooldownSubscriber when new_opportunity events arrive."""
        try:
            logger.info(f"Running opportunity specialist (triggered by {len(events)} events)")
            applied_ops = await run_opportunity_specialist_cycle(
                self.session_id,
                model_override=self._get_model("opportunity_specialist", None),
                knowledge_source_ids=self._get_knowledge_source_ids("opportunity_specialist"),
            )

            await self._broadcast_operation_results(applied_ops)

        except Exception as e:
            logger.error(f"Opportunity specialist cycle error: {e}")

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

            if op_result.get("op") == "answer":
                ans_id = op_result.get("id")
                self.active_questions[:] = [
                    aq for aq in self.active_questions
                    if aq["id"] != ans_id
                ]
            elif op_result.get("op") == "create" and ws_data:
                self.active_questions.append({
                    "id": ws_data["id"],
                    "question": ws_data["question"],
                })

    # ── Reconnection ─────────────────────────────────────────────────────

    async def _reconnect_gateway(self) -> bool:
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

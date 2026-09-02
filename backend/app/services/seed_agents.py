"""Seed default agent configurations into the database."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConfig
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.agents.prompts import (
    AUDIO_BRIDGE_PROMPT,
    BRIEF_ARBITER_PROMPT,
    BRIEF_DISCOVERY_LENS_PROMPT,
    BRIEF_MEETING_LENS_PROMPT,
    CONSOLIDATED_ANALYST_BASE_PROMPT,
    DEFAULT_ANALYST_LENSES,
    OBJECTION_HANDLER_PROMPT,
    OPPORTUNITY_SPECIALIST_PROMPT,
    PRINCIPAL_AGENT_PROMPT,
    STRATEGIC_SIGNALS_PROMPT,
)
from app.services.transcript_refiner import SYSTEM_PROMPT as TRANSCRIPT_REFINER_PROMPT
from app.services.transcription_runtime import SETTING_BATCH_TRANSCRIBER_MODEL

# Default prompt lookup by slug (used for reset endpoint)
DEFAULT_PROMPTS = {
    "audio_gateway": AUDIO_BRIDGE_PROMPT,
    "consolidated_analyst": CONSOLIDATED_ANALYST_BASE_PROMPT,
    "objection_handler": OBJECTION_HANDLER_PROMPT,
    "synthesizer": PRINCIPAL_AGENT_PROMPT,
    "opportunity_specialist": OPPORTUNITY_SPECIALIST_PROMPT,
    "strategic_signals": STRATEGIC_SIGNALS_PROMPT,
    "transcript_refiner": TRANSCRIPT_REFINER_PROMPT,
    "brief_meeting_lens": BRIEF_MEETING_LENS_PROMPT,
    "brief_discovery_lens": BRIEF_DISCOVERY_LENS_PROMPT,
    "brief_arbiter": BRIEF_ARBITER_PROMPT,
}

# Default lens configs by slug (used for seeding and the reset endpoint)
DEFAULT_LENSES_BY_SLUG = {
    "consolidated_analyst": DEFAULT_ANALYST_LENSES,
}

SEED_CONFIGS = [
    {
        "slug": "audio_gateway",
        "name": "Audio Bridge",
        "description": "Silent audio relay that streams live conversation audio to the selected cloud or local captioning model. Does not analyze or generate insights — just listens and enables input transcription.",
        "agent_type": "audio",
        "model_id": "",
        "prompt": AUDIO_BRIDGE_PROMPT,
        "enabled": True,
        "sub_types": "",
        "display_order": 1,
    },
    {
        "slug": "consolidated_analyst",
        "name": "Consolidated Analyst",
        "description": "Analyzes transcript through configurable lenses in a single call. Default lenses: strategic follow-up questions, observations, product & service opportunities, and action items. The model set here is also used by the post-import Analyze action.",
        "agent_type": "text",
        "model_id": "",
        "prompt": CONSOLIDATED_ANALYST_BASE_PROMPT,
        "enabled": True,
        "sub_types": "question,observation,opportunity,action_item",
        "lenses": json.dumps(DEFAULT_ANALYST_LENSES),
        "interval_seconds": 40,
        "display_order": 2,
    },
    {
        "slug": "objection_handler",
        "name": "Objection Handler",
        "description": "Fast-cycle scanner that flags objections the moment they surface and pairs each with an immediate suggested response plus the underlying strategic concern. Runs on a short interval over only the freshest transcript with a low-latency model.",
        "agent_type": "text",
        "model_id": "",
        "prompt": OBJECTION_HANDLER_PROMPT,
        "enabled": True,
        "sub_types": "",
        "interval_seconds": 10,
        "display_order": 8,
    },
    {
        "slug": "synthesizer",
        "name": "Principal Agent",
        "description": "Strategic oversight meta-agent that performs quality control on insights while also synthesizing the bigger picture — connecting disparate findings to reveal strategic objectives, initiatives, and cross-domain patterns. The model set here is also used by Enhance Insights after a speaker correction.",
        "agent_type": "meta",
        "model_id": "",
        "prompt": PRINCIPAL_AGENT_PROMPT,
        "enabled": True,
        "sub_types": "",
        "interval_seconds": 75,
        "display_order": 3,
    },
    {
        "slug": "opportunity_specialist",
        "name": "Opportunity Specialist",
        "description": "Enrichment agent that runs after the Consolidated Analyst: when a lens surfaces an Opportunity insight, it matches that insight against the configured knowledge sources (offerings catalog by default) and attaches the match to the card. It does not create new insights.",
        "agent_type": "db",
        "model_id": "",
        "prompt": OPPORTUNITY_SPECIALIST_PROMPT,
        "enabled": True,
        "sub_types": "",
        "interval_seconds": 55,
        "display_order": 4,
    },
    {
        "slug": "strategic_signals",
        "name": "Strategic Signals",
        "description": "Single-pass live synthesis that surfaces the signal, risk, next question, opportunity, and action cue while linking supported cards to saved insights.",
        "agent_type": "meta",
        "model_id": "",
        "prompt": STRATEGIC_SIGNALS_PROMPT,
        "enabled": True,
        "sub_types": "",
        "interval_seconds": 45,
        "display_order": 9,
    },
    {
        "slug": "transcript_refiner",
        "name": "Transcript Refiner",
        "description": "Sends the tokenized transcript to a text model, local or cloud, to fix punctuation, casing, sentence boundaries and obvious mishearings; a rewrite is kept only if it carries exactly the original tokens. Built for the PII Shield, where only local models may hear audio.",
        "agent_type": "text",
        "model_id": "",
        "prompt": TRANSCRIPT_REFINER_PROMPT,
        "enabled": False,
        "sub_types": "",
        "interval_seconds": 45,
        "display_order": 10,
    },
    {
        "slug": "brief_meeting_lens",
        "name": "Briefing Meeting Lens",
        "description": "Independent briefing lens that captures the meeting record: outcomes, decisions, blockers, commitments, and follow-ups.",
        "agent_type": "meta",
        "model_id": "",
        "prompt": BRIEF_MEETING_LENS_PROMPT,
        "enabled": True,
        "sub_types": "",
        "display_order": 5,
    },
    {
        "slug": "brief_discovery_lens",
        "name": "Briefing Discovery Lens",
        "description": "Independent briefing lens that captures the broader sensemaking signal: objectives, pains, learning gaps, opportunities, risks, and open discovery paths.",
        "agent_type": "meta",
        "model_id": "",
        "prompt": BRIEF_DISCOVERY_LENS_PROMPT,
        "enabled": True,
        "sub_types": "",
        "display_order": 6,
    },
    {
        "slug": "brief_arbiter",
        "name": "Briefing Arbiter",
        "description": "Compares the two independent briefing lenses, reconciles agreement and conflict, and settles the live/post-call briefing.",
        "agent_type": "meta",
        "model_id": "",
        "prompt": BRIEF_ARBITER_PROMPT,
        "enabled": True,
        "sub_types": "",
        "display_order": 7,
    },
]


async def seed_agent_configs(db: AsyncSession):
    """Insert default agent configs if they don't already exist."""
    for cfg in SEED_CONFIGS:
        result = await db.execute(
            select(AgentConfig).where(AgentConfig.slug == cfg["slug"])
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            db.add(AgentConfig(**cfg))
        # Descriptions are seed-owned (no UI edits them): keep rows in sync
        if existing is not None and existing.description != cfg["description"]:
            existing.description = cfg["description"]
        if existing is not None:
            _seed_missing_lenses(existing)
    if await get_app_setting(db, SETTING_BATCH_TRANSCRIBER_MODEL, None) is None:
        await set_app_setting(db, SETTING_BATCH_TRANSCRIBER_MODEL, "local-whisper-base")
    await db.commit()


def _seed_missing_lenses(existing: AgentConfig):
    """Populate the lenses column for pre-lens rows, honoring the old sub_types
    selection so previously deselected lenses stay off."""
    if (getattr(existing, "lenses", "") or "").strip():
        return
    defaults = DEFAULT_LENSES_BY_SLUG.get(existing.slug)
    if not defaults:
        return
    selected = {t.strip() for t in (existing.sub_types or "").split(",") if t.strip()}
    lenses = [dict(lens) for lens in defaults]
    if selected:
        for lens in lenses:
            lens["enabled"] = lens["item_type"] in selected
    existing.lenses = json.dumps(lenses)

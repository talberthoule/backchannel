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
from app.services.transcription_runtime import SETTING_BATCH_TRANSCRIBER_MODEL

# Default prompt lookup by slug (used for reset endpoint)
DEFAULT_PROMPTS = {
    "audio_gateway": AUDIO_BRIDGE_PROMPT,
    "consolidated_analyst": CONSOLIDATED_ANALYST_BASE_PROMPT,
    "objection_handler": OBJECTION_HANDLER_PROMPT,
    "synthesizer": PRINCIPAL_AGENT_PROMPT,
    "opportunity_specialist": OPPORTUNITY_SPECIALIST_PROMPT,
    "strategic_signals": STRATEGIC_SIGNALS_PROMPT,
    "brief_meeting_lens": BRIEF_MEETING_LENS_PROMPT,
    "brief_discovery_lens": BRIEF_DISCOVERY_LENS_PROMPT,
    "brief_arbiter": BRIEF_ARBITER_PROMPT,
}

# Default lens configs by slug (used for seeding and the reset endpoint)
DEFAULT_LENSES_BY_SLUG = {
    "consolidated_analyst": DEFAULT_ANALYST_LENSES,
}

# The old monolithic consolidated-analyst prompt hardcoded its lens sections;
# this heading identifies stale copies that should migrate to the new base
# prompt whose {lens_sections} placeholder is filled from the lenses config.
LEGACY_LENS_HEADING_MARKER = "## Lens 1: Strategic Follow-Up Questions"

OBSOLETE_MODEL_IDS = {
    "gemini-2.0-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro-preview-05-06",
}

DEFAULT_MODEL_VERSION_KEY = "defaults.models.version"
DEFAULT_MODEL_VERSION = "v0.2.5"
FORCED_DEFAULT_MODELS = {
    "consolidated_analyst": "gemini-3.6-flash",
    "opportunity_specialist": "gemini-3.6-flash",
    "brief_meeting_lens": "gemini-3.6-flash",
    "brief_discovery_lens": "gemini-3.6-flash",
    "brief_arbiter": "gemini-3.6-flash",
    "objection_handler": "gemini-3.5-flash-lite",
}

# Rows still on one of these old default intervals migrate to the new seeded
# value; user-customized intervals are left alone.
OLD_DEFAULT_INTERVALS = {
    "consolidated_analyst": {15, 45},
    "objection_handler": {5},
    "synthesizer": {30, 60},
    "opportunity_specialist": {5, 45},
}

# Stored prompts containing these placeholders are stale defaults from before
# the knowledge-source generalization and get replaced with the new default.
STALE_PLACEHOLDER_MARKERS = {
    "opportunity_specialist": "{offerings_catalog}",
}

# Stored prompts still carrying the old Presidio branding are stale defaults
# from before the de-branding and get replaced with the new generic default.
LEGACY_BRAND_MARKER = "Presidio"

CONTEXT_PROMPT_MARKERS = {
    "consolidated_analyst": "supporting a live call for leading solutions providers",
    "synthesizer": "Clusters of insights that together reveal a strategic initiative, project, or objective the client is pursuing",
    "brief_meeting_lens": "Audience: internal seller/deal team.",
    "brief_discovery_lens": "discovery and seller-insight lens",
    "brief_arbiter": "internal seller/deal-team audience",
}

SEED_CONFIGS = [
    {
        "slug": "audio_gateway",
        "name": "Audio Bridge",
        "description": "Silent audio relay that streams live conversation audio to Gemini for real-time transcription. Does not analyze or generate insights — just listens and enables input transcription.",
        "agent_type": "audio",
        "model_id": "gemini-3.1-flash-live-preview",
        "prompt": AUDIO_BRIDGE_PROMPT,
        "enabled": True,
        "sub_types": "",
        "display_order": 1,
    },
    {
        "slug": "consolidated_analyst",
        "name": "Consolidated Analyst",
        "description": "Analyzes transcript through configurable lenses in a single call. Default lenses: strategic follow-up questions, observations, product & service opportunities, and action items.",
        "agent_type": "text",
        "model_id": "gemini-3.6-flash",
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
        "model_id": "gemini-3.5-flash-lite",
        "prompt": OBJECTION_HANDLER_PROMPT,
        "enabled": True,
        "sub_types": "",
        "interval_seconds": 10,
        "display_order": 8,
    },
    {
        "slug": "synthesizer",
        "name": "Principal Agent",
        "description": "Strategic oversight meta-agent that performs quality control on insights while also synthesizing the bigger picture — connecting disparate findings to reveal strategic objectives, initiatives, and cross-domain patterns.",
        "agent_type": "meta",
        "model_id": "gemini-3.1-pro-preview",
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
        "model_id": "gemini-3.6-flash",
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
        "model_id": "gemini-3.6-flash",
        "prompt": STRATEGIC_SIGNALS_PROMPT,
        "enabled": True,
        "sub_types": "",
        "interval_seconds": 45,
        "display_order": 9,
    },
    {
        "slug": "brief_meeting_lens",
        "name": "Briefing Meeting Lens",
        "description": "Independent briefing lens that captures the meeting record: outcomes, decisions, blockers, commitments, and follow-ups.",
        "agent_type": "meta",
        "model_id": "gemini-3.6-flash",
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
        "model_id": "gemini-3.6-flash",
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
        "model_id": "gemini-3.6-flash",
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
        elif _should_refresh_seeded_model(existing, cfg):
            existing.model_id = cfg["model_id"]
        if existing is not None and _should_refresh_seeded_prompt(existing, cfg):
            existing.prompt = cfg["prompt"]
        # Descriptions are seed-owned (no UI edits them): keep rows in sync
        if existing is not None and existing.description != cfg["description"]:
            existing.description = cfg["description"]
        if (
            existing is not None
            and existing.slug in OLD_DEFAULT_INTERVALS
            and existing.interval_seconds in OLD_DEFAULT_INTERVALS[existing.slug]
        ):
            existing.interval_seconds = cfg["interval_seconds"]
        if existing is not None:
            _seed_missing_lenses(existing)
    await db.commit()
    await apply_default_model_version(db)


async def apply_default_model_version(db: AsyncSession) -> bool:
    """Apply the v0.2.5 defaults once, then preserve later selections."""
    current_version = await get_app_setting(db, DEFAULT_MODEL_VERSION_KEY, "")
    if current_version == DEFAULT_MODEL_VERSION:
        return False

    result = await db.execute(
        select(AgentConfig).where(AgentConfig.slug.in_(FORCED_DEFAULT_MODELS))
    )
    for agent in result.scalars():
        agent.model_id = FORCED_DEFAULT_MODELS[agent.slug]

    await set_app_setting(
        db,
        SETTING_BATCH_TRANSCRIBER_MODEL,
        "gemini-3.5-flash-lite",
    )
    await set_app_setting(db, DEFAULT_MODEL_VERSION_KEY, DEFAULT_MODEL_VERSION)
    await db.commit()
    return True


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


def _should_refresh_seeded_model(existing: AgentConfig, cfg: dict) -> bool:
    if existing.model_id == cfg["model_id"]:
        return False
    return existing.model_id in OBSOLETE_MODEL_IDS


def _should_refresh_seeded_prompt(existing: AgentConfig, cfg: dict) -> bool:
    stale_marker = STALE_PLACEHOLDER_MARKERS.get(existing.slug)
    if stale_marker and stale_marker in (existing.prompt or ""):
        return True
    if LEGACY_BRAND_MARKER in (existing.prompt or ""):
        return True
    if (
        "{lens_sections}" in (cfg.get("prompt") or "")
        and "{lens_sections}" not in (existing.prompt or "")
        and LEGACY_LENS_HEADING_MARKER in (existing.prompt or "")
    ):
        # Old default monolithic prompt with hardcoded lens sections: replace
        # with the new base prompt (lens bodies now live in the lenses column).
        return True
    if "{meeting_context_text}" in (existing.prompt or ""):
        return False
    marker = CONTEXT_PROMPT_MARKERS.get(existing.slug)
    return bool(marker and marker in (existing.prompt or ""))

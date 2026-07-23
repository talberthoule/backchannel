"""Single-call live strategic-signals synthesis."""

from __future__ import annotations

import uuid
from typing import Any

from google import genai

from app.services.agents.prompts import STRATEGIC_SIGNALS_PROMPT
from app.services.briefing_synthesis import (
    BriefArbiterOutput,
    _build_context,
    _generate_structured,
    _persist_synthesis,
    load_agent_configs,
)
from app.services.meeting_context import format_prompt_with_meeting_context
from app.services.privacy import LocalOnlyModeError, is_local_only
from app.services.secrets import resolve_provider_key

STRATEGIC_SIGNALS_SLUG = "strategic_signals"


async def run_strategic_signals_cycle(
    session_id: uuid.UUID,
    agent_configs: dict[str, Any] | None = None,
    transcript_window: str | None = None,
    directives: list[str] | None = None,
    doc_summaries: str | None = None,
    speakers: list[dict] | None = None,
    active_questions: list[dict] | None = None,
):
    if await is_local_only():
        raise LocalOnlyModeError("live strategic signals")

    configs = agent_configs or await load_agent_configs(session_id)
    cfg = configs.get(STRATEGIC_SIGNALS_SLUG)
    if not cfg or not cfg.enabled:
        return None

    context = await _build_context(
        session_id,
        mode="live",
        transcript_window=transcript_window,
        directives=directives,
        doc_summaries=doc_summaries,
        speakers=speakers,
        active_questions=active_questions,
    )
    if not context.transcript_text or context.transcript_text == "(No transcript yet)":
        return None

    prompt = format_prompt_with_meeting_context(
        cfg.prompt or STRATEGIC_SIGNALS_PROMPT,
        context.meeting_context_text,
        mode="live",
        speakers_text=context.speakers_text,
        directives_text=context.directives_text,
        document_summaries=context.document_summaries,
        insights_text=context.insights_text,
        transcript_text=context.transcript_text,
    )
    client = genai.Client(api_key=await resolve_provider_key("google"))
    output = await _generate_structured(
        client,
        cfg.model_id,
        prompt,
        BriefArbiterOutput,
        session_id=session_id,
        source=STRATEGIC_SIGNALS_SLUG,
    )
    return await _persist_synthesis(
        session_id=session_id,
        mode="live",
        status="completed",
        meeting_output=None,
        discovery_output=None,
        arbiter_output=output,
        model_ids={STRATEGIC_SIGNALS_SLUG: cfg.model_id},
    )

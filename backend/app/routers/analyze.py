import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm import generate_text
from app.database import get_db
from app.models import Directive, Question, Session, TranscriptEntry
from app.services.briefing_synthesis import agent_model_id, load_agent_configs
from app.services.meeting_context import build_meeting_context_text
from app.services.transcript_refiner import REFINER_SLUG, refine_session

router = APIRouter(prefix="/api/sessions/{session_id}/analyze", tags=["analyze"])


@router.post("")
async def analyze_transcript(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Analyze an imported transcript: generate questions, track answers, surface insights."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # Load transcript
    result = await db.execute(
        select(TranscriptEntry)
        .where(TranscriptEntry.session_id == session_id)
        .order_by(TranscriptEntry.sequence)
    )
    entries = result.scalars().all()
    if not entries:
        raise HTTPException(400, "No transcript entries to analyze")

    # The refiner, when enabled, corrects the wording first so the analysis
    # reads what a person would. It works on tokenized text only.
    refiner_cfg = (await load_agent_configs()).get(REFINER_SLUG)
    if refiner_cfg and refiner_cfg.enabled and refiner_cfg.model_id:
        await refine_session(db, session_id, refiner_cfg.model_id)
        await db.commit()
        result = await db.execute(
            select(TranscriptEntry)
            .where(TranscriptEntry.session_id == session_id)
            .order_by(TranscriptEntry.sequence)
        )
        entries = result.scalars().all()

    # Load directives
    result = await db.execute(
        select(Directive.text).where(Directive.session_id == session_id, Directive.active.is_(True))
    )
    directives = list(result.scalars().all())

    # Build the transcript text
    transcript_text = "\n".join(e.text for e in entries)

    # Build directives context
    directives_text = "\n".join(f"- {d}" for d in directives) if directives else "(No directives)"

    meeting_context_text = build_meeting_context_text(session)

    prompt = f"""You are a conversation analysis assistant. Analyze this transcript and generate context-appropriate insights. Do not assume this is a client or sales call unless the Meeting Context or transcript supports that.

## Meeting Context
{meeting_context_text}

## Call Directives (what the user wanted to watch for):
{directives_text}

## Transcript:
{transcript_text}

## Your Task:
Analyze the transcript and output a JSON array of objects. Each object should be one of these types:

1. **Question** — A follow-up question worth asking in a future conversation:
{{"item_type": "question", "question": "...", "rationale": "why this matters", "source_context": "what was said"}}

2. **Observation** — A notable fact, statement, or detail from the conversation:
{{"item_type": "observation", "question": "the observation", "rationale": "why this matters", "source_context": "what was said"}}

3. **Opportunity** — A context-appropriate next move identified in the conversation. This may be a learning gap, program opportunity, process improvement, partner motion, customer opportunity, or offering opportunity only when supported:
{{"item_type": "opportunity", "question": "the opportunity", "rationale": "why it is valuable and what should happen next", "source_context": "what reveals this"}}

4. **Action Item** — Something that needs follow-up after the call:
{{"item_type": "action_item", "question": "the action item", "rationale": "why this is important", "source_context": "what triggered this"}}

5. **Answered** — A question that was asked AND answered during the call:
{{"item_type": "answered", "question": "the question", "answer_summary": "what we learned", "needs_followup": true/false, "followup_question": "next question if needed"}}

Rules:
- Surface a good mix of all types - questions, observations, opportunities, and action items
- Focus on value-adding insights, not obvious observations
- For answered items, summarize what was learned concisely
- Flag follow-ups where the answer was vague or opens new threads
- If directives are set, prioritize findings related to them
- Use Meeting Context to decide whether sales/client language is appropriate
- Output ONLY a valid JSON array, no other text

Output the JSON array:"""

    # Analyze is the post-import form of what the Consolidated Analyst does
    # live: same transcript in, same four item types out. It runs whatever
    # model that agent is set to, so Privacy First judges it by destination and
    # the choice is visible in Admin -> Agents instead of being implicit.
    model_id = await agent_model_id("consolidated_analyst")

    raw = await generate_text(
        model_id, prompt, session_id=session_id, source="analyze"
    )


    # Parse the JSON array from the response
    import json
    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON array in the response
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            try:
                items = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                raise HTTPException(500, "Failed to parse analysis results")
        else:
            raise HTTPException(500, "Failed to parse analysis results")

    # Save questions to the database
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue

        itype = item.get("item_type", "question")
        question_text = item.get("question", "")
        if not question_text:
            continue

        q = Question(
            session_id=session_id,
            item_type=itype if itype != "answered" else "question",
            question=question_text,
            rationale=item.get("rationale", ""),
            source_context=item.get("source_context", ""),
        )

        if itype == "answered":
            q.answered = True
            q.answer_summary = item.get("answer_summary", "")
            q.needs_followup = item.get("needs_followup", False)
            q.followup_question = item.get("followup_question", "")

        db.add(q)
        count += 1

        # If answered with followup, create the followup as a separate question
        if itype == "answered" and item.get("needs_followup") and item.get("followup_question"):
            followup = Question(
                session_id=session_id,
                question=item["followup_question"],
                rationale=f"Follow-up to: {question_text}",
                source_context=item.get("answer_summary", ""),
                needs_followup=True,
            )
            db.add(followup)
            count += 1

    await db.commit()

    # Mark session as completed
    session.state = "completed"
    session.ended_at = datetime.now(timezone.utc)
    if not session.started_at:
        session.started_at = datetime.now(timezone.utc)
    await db.commit()

    return {"analyzed": count, "session_id": str(session_id)}

"""Base classes for text-based agents.

TranscriptBuffer: in-memory ring buffer (~5 min of transcript text), thread-safe.
TextAgent: common logic for Observer, Opportunity Scout, and Action Tracker.
"""

import asyncio
import json
import logging
import time
from collections import deque

from app.config import settings
from app.services.agents.speaker_context import format_speakers_list, format_transcript_segment
from app.services.llm import generate_text

logger = logging.getLogger(__name__)

# ~5 minutes of transcript at ~10s per segment = ~30 segments
_DEFAULT_BUFFER_SIZE = 30


class TranscriptBuffer:
    """Thread-safe ring buffer of recent transcript segments."""

    def __init__(self, max_segments: int = _DEFAULT_BUFFER_SIZE):
        self._segments: deque[dict] = deque(maxlen=max_segments)
        self._lock = asyncio.Lock()

    async def add(
        self,
        text: str,
        speaker: str | None = None,
        speaker_id: str | None = None,
        speaker_type: str | None = None,
    ):
        async with self._lock:
            self._segments.append({
                "text": text,
                "speaker": speaker or "Unknown",
                "speaker_id": speaker_id,
                "speaker_type": speaker_type,
                "ts": time.time(),
            })

    async def get_window(self, max_age_seconds: float = 300.0) -> str:
        """Return formatted transcript window for the last `max_age_seconds`."""
        async with self._lock:
            cutoff = time.time() - max_age_seconds
            lines = []
            for seg in self._segments:
                if seg["ts"] >= cutoff:
                    lines.append(format_transcript_segment(
                        seg["text"],
                        seg["speaker"],
                        speaker_id=seg.get("speaker_id"),
                        speaker_type=seg.get("speaker_type"),
                    ))
            return "\n".join(lines) if lines else "(No recent transcript)"

    async def clear(self):
        async with self._lock:
            self._segments.clear()


class TextAgent:
    """Base class for text-based batch agents (Observer, Opportunity Scout, Action Tracker).

    Subclasses set `agent_name`, `item_type`, and `prompt_template` at the class level.
    """

    agent_name: str = "text_agent"
    item_type: str = "observation"
    prompt_template: str = ""

    def __init__(self):
        pass

    async def run_cycle(
        self,
        transcript_window: str,
        directives: list[str],
        doc_summaries: str,
        speakers: list[dict],
    ) -> list[dict]:
        """Execute one analysis cycle. Returns list of insight dicts."""
        directives_text = "\n".join(f"- {d}" for d in directives) if directives else "(No directives set)"
        speakers_text = format_speakers_list(speakers)

        prompt = self.prompt_template.format(
            transcript_window=transcript_window,
            directives_text=directives_text,
            document_summaries=doc_summaries or "(No documents uploaded)",
            speakers_text=speakers_text,
        )

        try:
            raw = await generate_text(settings.REFINEMENT_MODEL, prompt)
        except Exception as e:
            logger.error(f"[{self.agent_name}] API call failed: {e}")
            return []

        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> list[dict]:
        """Parse JSON array from model response, handling markdown fences."""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        if not raw or raw == "[]":
            return []

        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1:
                try:
                    items = json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    logger.warning(f"[{self.agent_name}] parse failed: {raw[:200]}")
                    return []
            else:
                logger.warning(f"[{self.agent_name}] parse failed: {raw[:200]}")
                return []

        if not isinstance(items, list):
            return []

        # Ensure each item has the correct item_type and filter malformed entries
        valid = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if "question" not in item:
                continue
            item["item_type"] = item.get("item_type", self.item_type)
            valid.append(item)

        return valid


class ObserverAgent(TextAgent):
    agent_name = "observer"
    item_type = "observation"

    @property
    def prompt_template(self):
        from app.services.agents.prompts import OBSERVER_PROMPT
        return OBSERVER_PROMPT


class OpportunityScoutAgent(TextAgent):
    agent_name = "opportunity_scout"
    item_type = "opportunity"

    @property
    def prompt_template(self):
        from app.services.agents.prompts import OPPORTUNITY_SCOUT_PROMPT
        return OPPORTUNITY_SCOUT_PROMPT


class ActionTrackerAgent(TextAgent):
    agent_name = "action_tracker"
    item_type = "action_item"

    @property
    def prompt_template(self):
        from app.services.agents.prompts import ACTION_TRACKER_PROMPT
        return ACTION_TRACKER_PROMPT

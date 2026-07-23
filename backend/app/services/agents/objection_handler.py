"""Objection Handler agent — fast scan loop over the freshest transcript.

Optimized for latency: a lean prompt, a short transcript window, and a
low-latency default model so objections surface while the moment to
respond is still open. Each finding pairs an immediate suggested reply
(micro) with the underlying concern and strategic angle (macro).
"""

import json
import logging
import uuid
from collections import deque

from app.services.agents.prompts import OBJECTION_HANDLER_PROMPT
from app.services.agents.speaker_context import format_speakers_list
from app.services.llm import generate_text
from app.services.meeting_context import build_meeting_context_text, format_prompt_with_meeting_context

logger = logging.getLogger(__name__)

# Low-latency model: objection surfacing is time-critical, so the default
# trades some depth for speed. Overridable via agent config.
DEFAULT_OBJECTION_MODEL = "gemini-3.1-flash-lite"

VALID_SEVERITIES = {"high", "medium", "low"}

# How many surfaced objections to remind the model about so overlapping
# scan windows don't re-flag the same pushback every cycle.
_MAX_RECENT_OBJECTIONS = 12


def _normalize_speaker_id(raw: object, valid_speaker_ids: set[str]) -> str | None:
    """Return a known speaker UUID string, or None for invalid model output."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        normalized = str(uuid.UUID(raw.strip()))
    except ValueError:
        return None
    return normalized if normalized in valid_speaker_ids else None


def _compose_rationale(item: dict) -> str:
    """Fold the micro/macro fields into the insight rationale."""
    parts = []
    response_now = item.get("response_now")
    if isinstance(response_now, str) and response_now.strip():
        parts.append(f"Respond now: {response_now.strip()}")
    bigger_picture = item.get("bigger_picture")
    if isinstance(bigger_picture, str) and bigger_picture.strip():
        parts.append(f"Bigger picture: {bigger_picture.strip()}")
    severity = item.get("severity")
    if isinstance(severity, str) and severity.strip().lower() in VALID_SEVERITIES:
        parts.append(f"(Severity: {severity.strip().lower()})")
    return " ".join(parts)


class ObjectionHandlerAgent:
    """Fast-cycle scanner that flags objections with a ready response."""

    def __init__(
        self,
        model_override: str | None = None,
        prompt_override: str | None = None,
        meeting_context_text: str | None = None,
        session_id: uuid.UUID | None = None,
    ):
        self._model = model_override or DEFAULT_OBJECTION_MODEL
        self._prompt_template = prompt_override or OBJECTION_HANDLER_PROMPT
        self.meeting_context_text = meeting_context_text or build_meeting_context_text()
        self._recent_objections: deque[str] = deque(maxlen=_MAX_RECENT_OBJECTIONS)
        self._last_window = ""
        self._session_id = session_id

    def update_meeting_context(self, meeting_context_text: str):
        self.meeting_context_text = meeting_context_text
        # Clear the unchanged-window skip so the current window is rescanned with the new context.
        self._last_window = ""

    async def run_cycle(
        self,
        transcript_window: str,
        directives: list[str],
        speakers: list[dict],
    ) -> list[dict]:
        """Execute one fast scan. Returns list of objection insight dicts."""
        # No new speech since the last scan — skip the LLM call entirely.
        if transcript_window == self._last_window:
            return []
        self._last_window = transcript_window

        directives_text = "\n".join(f"- {d}" for d in directives) if directives else "(No directives set)"
        speakers_text = format_speakers_list(speakers)
        valid_speaker_ids = {str(s["id"]) for s in speakers if s.get("id")}
        if self._recent_objections:
            recent_text = "\n".join(f'- "{o}"' for o in self._recent_objections)
        else:
            recent_text = "(No objections surfaced yet)"

        prompt = format_prompt_with_meeting_context(
            self._prompt_template,
            self.meeting_context_text,
            transcript_window=transcript_window,
            directives_text=directives_text,
            speakers_text=speakers_text,
            recent_objections=recent_text,
        )

        try:
            raw_text = await generate_text(
                self._model, prompt, session_id=self._session_id, source="objection_handler"
            )
        except Exception as e:
            logger.error(f"[objection_handler] API call failed: {e}")
            return []

        items = self._parse_response(raw_text, valid_speaker_ids)
        for item in items:
            self._recent_objections.append(item["question"])
        if items:
            logger.info(f"[objection_handler] flagged {len(items)} objection(s)")
        return items

    def _parse_response(self, raw: str, valid_speaker_ids: set[str]) -> list[dict]:
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
                    logger.warning(f"[objection_handler] parse failed: {raw[:200]}")
                    return []
            else:
                logger.warning(f"[objection_handler] parse failed: {raw[:200]}")
                return []

        if not isinstance(items, list):
            return []

        valid = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = item.get("question")
            if not isinstance(text, str) or not text.strip():
                continue
            valid.append({
                "item_type": "objection",
                "question": text.strip(),
                "rationale": _compose_rationale(item),
                "source_context": item.get("source_context", "") or "",
                "speaker_id": _normalize_speaker_id(item.get("speaker_id"), valid_speaker_ids),
                "agent_source": "objection_handler",
            })

        return valid

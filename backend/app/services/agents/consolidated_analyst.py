"""Consolidated Analyst agent — single API call producing observations,
opportunities, and action items from one read of the transcript.

Replaces the three separate text agents (Observer, Opportunity Scout,
Action Tracker) with one structured call for ~60% cost reduction
and better cross-cutting insight quality.
"""

import json
import logging
import re
import uuid

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services.agents.activity import classify_error
from app.services.agents.prompts import CONSOLIDATED_ANALYST_BASE_PROMPT, DEFAULT_ANALYST_LENSES
from app.services.llm import generate_json
from app.services.agents.speaker_context import format_speakers_list
from app.services.meeting_context import build_meeting_context_text, format_prompt_layers

logger = logging.getLogger(__name__)

# Map item_type to the agent_source name for backward-compatible exports
AGENT_SOURCE_BY_TYPE = {
    "question": "question_hunter",
    "observation": "observer",
    "opportunity": "opportunity_scout",
    "action_item": "action_tracker",
}

# Built-in item types with special pipeline behavior (question answer
# tracking, opportunity offering-matching). Lenses may also define custom
# item_type slugs, which flow through the pipeline as plain insights.
BUILTIN_TYPES = {"question", "observation", "opportunity", "action_item"}
VALID_TYPES = BUILTIN_TYPES  # legacy alias
TYPE_ORDER = ["question", "observation", "opportunity", "action_item"]

TYPE_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9_]+")

LENS_SECTIONS_PLACEHOLDER = "{lens_sections}"


class ConsolidatedAnalystItem(BaseModel):
    item_type: str
    question: str
    rationale: str = ""
    source_context: str = ""
    speaker_id: str | None = None
    directive_source: str | None = None
    lens: str | None = None


class ConsolidatedAnalystOutput(BaseModel):
    items: list[ConsolidatedAnalystItem]


def normalize_type_slug(raw: object) -> str:
    """Coerce arbitrary text into an item_type slug ('' if nothing usable)."""
    slug = _SLUG_CLEAN_RE.sub("_", str(raw or "").strip().lower()).strip("_")[:50]
    return slug if TYPE_SLUG_RE.match(slug) else ""


def _lens_item_type(lens: dict) -> str:
    """The insight type a lens's findings surface as; defaults to observation."""
    return normalize_type_slug(lens.get("item_type")) or "observation"


def active_lenses(lenses: list) -> list[dict]:
    """Filter a lens config list down to enabled lenses with usable prompts."""
    result = []
    for lens in lenses or []:
        if not isinstance(lens, dict):
            continue
        if not lens.get("enabled", True):
            continue
        if not str(lens.get("prompt") or "").strip():
            continue
        result.append(lens)
    return result


def compose_lens_sections(lenses: list[dict]) -> str:
    """Render lens configs into numbered prompt sections."""
    sections = []
    for idx, lens in enumerate(lenses, 1):
        label = str(lens.get("label") or f"Lens {idx}").strip()
        body = str(lens.get("prompt") or "").strip()
        itype = _lens_item_type(lens)
        key = str(lens.get("key") or "").strip() or itype
        sections.append(
            f"## Lens {idx}: {label}\n{body}\n\n"
            f'Tag every finding from this lens with "item_type": "{itype}" and "lens": "{key}".'
        )
    return "\n\n".join(sections)

SPEAKER_ATTRIBUTION_APPENDIX = """

## Speaker Attribution Requirements
- Transcript lines may include `speaker_id=<uuid>`. Use those UUIDs for attribution.
- Participants lists `speaker_type=team` or `speaker_type=external` once per speaker. Look the speaker up there by `speaker_id`; transcript lines do not repeat it.
- Treat `team` speakers as internal voices from the user's organization.
- Treat `external` speakers as outside the internal team. Use Meeting Context to decide whether they are a client, vendor, partner, candidate, or other participant.
- Do not treat external speaker statements as client evidence unless the Meeting Context or transcript supports that interpretation.
- Return a `speaker_id` field on each JSON item. Use a UUID shown in Participants or Recent Transcript, or null if unclear.
- Do not invent Speaker numbers, real names, or combined labels like "Speaker 1/Mark" in the insight text.
"""


def _normalize_speaker_id(raw: object, valid_speaker_ids: set[str]) -> str | None:
    """Return a known speaker UUID string, or None for invalid model output."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = raw.strip()
    try:
        normalized = str(uuid.UUID(candidate))
    except ValueError:
        return None
    return normalized if normalized in valid_speaker_ids else None


class ConsolidatedAnalystAgent:
    """Single-call analyst that produces all three insight types."""

    def __init__(
        self,
        enabled_types: set[str] | None = None,
        model_override: str | None = None,
        prompt_override: str | None = None,
        meeting_context_text: str | None = None,
        lenses: list[dict] | None = None,
        session_id: uuid.UUID | None = None,
        suppressed_types: set[str] | None = None,
    ):
        self._model = settings.REFINEMENT_MODEL if model_override is None else model_override
        prompt_template = prompt_override or CONSOLIDATED_ANALYST_BASE_PROMPT

        # Kept so the lens set can be recomposed when the meeting type changes
        # mid-call and a lens becomes (in)applicable.
        self._configured_lenses = lenses
        self._configured_types = enabled_types
        self._suppressed_types = set(suppressed_types or ())
        self._uses_lens_sections = LENS_SECTIONS_PLACEHOLDER in prompt_template
        self._compose_lenses()

        if "## Speaker Attribution Requirements" not in prompt_template:
            prompt_template = f"{prompt_template.rstrip()}{SPEAKER_ATTRIBUTION_APPENDIX}"
        self._prompt_template = prompt_template
        self.meeting_context_text = meeting_context_text or build_meeting_context_text()
        self._session_id = session_id
        self.last_outcome: dict | None = None

    def _compose_lenses(self):
        """(Re)build the lens sections and enabled types from the stored config.

        Suppressed item types are dropped here rather than filtered from the
        output, so a suppressed lens costs no prompt tokens at all.
        """
        lenses = self._configured_lenses
        enabled_types = self._configured_types

        self._lens_sections = ""
        self._item_type_values = "|".join(TYPE_ORDER)
        # Lens provenance lookups: key -> {label, item_type}, plus the first
        # lens label per item_type as an attribution fallback.
        self._lens_by_key: dict[str, dict] = {}
        self._label_by_type: dict[str, str] = {}
        if self._uses_lens_sections:
            if lenses is None:
                # No lens config stored yet: fall back to the defaults, honoring
                # the legacy sub_types selection when one was provided.
                lenses = [dict(l) for l in DEFAULT_ANALYST_LENSES]
                if enabled_types:
                    lenses = [l for l in lenses if l["item_type"] in enabled_types]
            lens_list = [
                lens for lens in active_lenses(lenses)
                if _lens_item_type(lens) not in self._suppressed_types
            ]
            self._lens_sections = compose_lens_sections(lens_list)
            lens_types = []
            for lens in lens_list:
                itype = _lens_item_type(lens)
                key = str(lens.get("key") or "").strip() or itype
                label = str(lens.get("label") or "").strip()
                self._lens_by_key[key] = {"label": label, "item_type": itype}
                self._label_by_type.setdefault(itype, label)
                if itype not in lens_types:
                    lens_types.append(itype)
            self.enabled_types = set(lens_types)
            self._item_type_values = "|".join(lens_types) or "observation"
            self.lens_count = len(lens_list)
        else:
            # Legacy monolithic prompt (custom prompt from before configurable
            # lenses): run it as-is and filter output by the sub_types config.
            # The prompt cannot be trimmed, but suppressed output is dropped.
            self.enabled_types = set(enabled_types or VALID_TYPES) - self._suppressed_types
            self._item_type_values = "|".join(t for t in TYPE_ORDER if t in self.enabled_types)
            # No lens sections in a legacy prompt; the enabled types are the
            # closest analog for the live activity summary.
            self.lens_count = len(self.enabled_types)

    def set_suppressed_types(self, suppressed_types: set[str] | None):
        """Apply a mid-call change to which item types this agent may produce."""
        updated = set(suppressed_types or ())
        if updated == self._suppressed_types:
            return
        self._suppressed_types = updated
        self._compose_lenses()

    async def run_cycle(
        self,
        transcript_window: str,
        directives: list[str],
        doc_summaries: str,
        speakers: list[dict],
        active_questions: list[dict] | None = None,
        board_notes: list[dict] | None = None,
    ) -> list[dict]:
        """Execute one analysis cycle. Returns list of insight dicts with item_type and agent_source."""
        directives_text = "\n".join(f"- {d}" for d in directives) if directives else "(No directives set)"
        speakers_text = format_speakers_list(speakers)
        valid_speaker_ids = {str(s["id"]) for s in speakers if s.get("id")}
        if active_questions:
            aq_text = "\n".join(f'- "{q["question"]}"' for q in active_questions)
        else:
            aq_text = "(No questions suggested yet)"
        # Everything else already on the board rides in the same placeholder,
        # so installs whose stored prompt predates the heading change still get
        # the full context. Stubbed and capped upstream (_MAX_BOARD_STUBS).
        if board_notes:
            notes_text = "\n".join(
                f'- [{note.get("item_type") or "insight"}] {note.get("text") or ""}'
                for note in board_notes
            )
            aq_text += (
                "\n\nOther insights already captured this call (do not restate"
                " any of these in any wording; only add what is genuinely"
                " new):\n" + notes_text
            )

        # Instructions go out as instructions; the user turn is this cycle's
        # data. About half of every call is byte-identical to the last one,
        # and that half is now a prefix a cache can share (ALP-285).
        system, prompt = format_prompt_layers(
            self._prompt_template,
            self.meeting_context_text,
            transcript_window=transcript_window,
            directives_text=directives_text,
            document_summaries=doc_summaries or "(No documents uploaded)",
            speakers_text=speakers_text,
            active_questions=aq_text,
            lens_sections=self._lens_sections,
            item_type_values=self._item_type_values,
        )

        try:
            output = await generate_json(
                self._model,
                prompt,
                ConsolidatedAnalystOutput,
                session_id=self._session_id,
                source="consolidated_analyst",
                system=system,
            )
        except Exception as e:
            logger.error(f"[consolidated_analyst] API call failed: {e}")
            if isinstance(e, (json.JSONDecodeError, ValidationError)):
                self.last_outcome = {
                    "kind": "parse_failed",
                    "detail": f"The structured reply was not usable: {e}",
                    "items": 0,
                }
            else:
                self.last_outcome = {
                    "kind": "error",
                    "error": classify_error(e, self._model),
                }
            return []

        raw_items = [item.model_dump(exclude_unset=True) for item in output.items]
        items = self._parse_response(raw_items, valid_speaker_ids)
        logger.info(f"[consolidated_analyst] parsed {len(items)} items from response")

        # Filter to enabled types, tag with agent_source, and attach the
        # producing lens's label for dynamic display downstream.
        results = []
        for item in items:
            itype = item.get("item_type")
            if itype not in self.enabled_types:
                logger.warning(
                    "[consolidated_analyst] dropped item: item_type=%r is not enabled",
                    itype,
                )
                continue
            item["agent_source"] = AGENT_SOURCE_BY_TYPE.get(itype, "consolidated_analyst")
            item["lens_label"] = self._resolve_lens_label(item.pop("lens", None), itype)
            results.append(item)

        if results:
            self.last_outcome = {
                "kind": "insights",
                "detail": f"{len(results)} usable insight{'s' if len(results) != 1 else ''}",
                "items": len(results),
            }
        elif not raw_items:
            self.last_outcome = {
                "kind": "no_findings",
                "detail": "The model found nothing to surface.",
                "items": 0,
            }
        else:
            invalid = len(raw_items) - len(items)
            disabled = len(items)
            drops = []
            if invalid:
                drops.append(
                    f"{invalid} failed validation"
                )
            if disabled:
                drops.append(
                    f"{disabled} disabled type{'s' if disabled != 1 else ''}"
                )
            self.last_outcome = {
                "kind": "all_filtered",
                "detail": (
                    f"{len(raw_items)} structured item"
                    f"{'s' if len(raw_items) != 1 else ''} yielded 0 usable items: "
                    + ", ".join(drops)
                ),
                "items": 0,
            }
        return results

    def _resolve_lens_label(self, raw_lens: object, item_type: str) -> str:
        """Best-effort mapping of a finding back to the lens that produced it."""
        if isinstance(raw_lens, str):
            info = self._lens_by_key.get(raw_lens.strip())
            if info and info["item_type"] == item_type:
                return info["label"]
        return self._label_by_type.get(item_type, "")

    def _parse_response(
        self,
        items: list[object],
        valid_speaker_ids: set[str] | None = None,
    ) -> list[dict]:
        """Normalize schema-validated model items for the insight pipeline."""
        valid_speaker_ids = valid_speaker_ids or set()
        valid = []
        for item in items:
            if not isinstance(item, dict):
                logger.warning(
                    "[consolidated_analyst] dropped item: expected object "
                    "(entry_type=%s)",
                    type(item).__name__,
                )
                continue
            question = item.get("question")
            if not isinstance(question, str) or not question.strip():
                logger.warning(
                    "[consolidated_analyst] dropped item: question=%r must be "
                    "a non-empty string",
                    question,
                )
                continue
            itype = normalize_type_slug(item.get("item_type", ""))
            if not itype:
                logger.warning(
                    "[consolidated_analyst] dropped item: item_type=%r cannot "
                    "be normalized to a slug",
                    item.get("item_type"),
                )
                continue
            item["item_type"] = itype
            item["speaker_id"] = _normalize_speaker_id(item.get("speaker_id"), valid_speaker_ids)
            valid.append(item)

        return valid

"""PII Shield: the encode and decode paths, and the settings that drive them.

``protect_text`` is safe to call from anywhere; with the shield off it returns
its input unchanged. ``reveal_text`` is for the local interface only. The
split is the whole security argument: the models, the database and the
exports only ever hold what ``protect_text`` produced, and the only code that
can put a real value back is the response path to the person sitting at this
machine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PiiRevealEvent, Speaker
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.pii import ner, vault
from app.services.pii.recognizers import (
    CATEGORIES,
    LOCATION,
    ORG,
    PERSON,
    RosterEntry,
    Span,
    find_patterns,
    find_roster,
    resolve_spans,
)
from app.services.pii.state import SETTINGS_KEY
from app.services.pii.vault import TOKEN_PATTERN, has_tokens

logger = logging.getLogger(__name__)

# Places are analytically useful ("we are expanding into Texas") and rarely
# personal on their own; street addresses have their own recognizer.
DEFAULT_CATEGORIES = [c for c in CATEGORIES if c != LOCATION]

ROSTER_TTL_SECONDS = 5.0


@dataclass
class ShieldSettings:
    enabled: bool = False
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    # On-device NER for names, organizations and places in free text.
    ner: bool = True
    # [{"value": "Acme Corp", "category": "ORG"}, ...] - the user's own list.
    protected_terms: list[dict] = field(default_factory=list)
    # Record every outbound model prompt to DATA_DIR/prompt-log so the
    # tokenization can be checked against what actually left (egress.py).
    prompt_log: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "ShieldSettings":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except ValueError:
            return cls()
        categories = [c for c in data.get("categories", DEFAULT_CATEGORIES) if c in CATEGORIES]
        terms = [
            {"value": str(t.get("value", "")).strip(), "category": t.get("category", ORG)}
            for t in data.get("protected_terms", [])
            if isinstance(t, dict) and str(t.get("value", "")).strip()
        ]
        return cls(
            enabled=bool(data.get("enabled", False)),
            categories=categories,
            ner=bool(data.get("ner", True)),
            protected_terms=[t for t in terms if t["category"] in CATEGORIES],
            prompt_log=bool(data.get("prompt_log", False)),
        )


_settings_cache: tuple[float, ShieldSettings] | None = None
_SETTINGS_TTL = 2.0


async def get_settings(db: AsyncSession) -> ShieldSettings:
    global _settings_cache
    now = time.monotonic()
    if _settings_cache and now - _settings_cache[0] < _SETTINGS_TTL:
        return _settings_cache[1]
    try:
        raw = await get_app_setting(db, SETTINGS_KEY, "")
    except (TypeError, AttributeError):
        # A stand-in session (router tests build them from mocks) has no
        # settings row to read; the shield is simply off. A real database
        # failure raises a SQLAlchemy error and still propagates.
        raw = ""
    parsed = ShieldSettings.from_json(raw if isinstance(raw, str) else "")
    _settings_cache = (now, parsed)
    return parsed


async def set_settings(db: AsyncSession, new: ShieldSettings) -> ShieldSettings:
    global _settings_cache
    await set_app_setting(db, SETTINGS_KEY, new.to_json())
    _settings_cache = (time.monotonic(), new)
    _roster_cache.clear()
    logger.info("PII Shield %s (%s)", "enabled" if new.enabled else "disabled", ", ".join(new.categories))
    return new


def invalidate_settings_cache() -> None:
    global _settings_cache
    _settings_cache = None
    _roster_cache.clear()


async def get_settings_standalone() -> ShieldSettings:
    """Settings for call sites without a db (the model-call boundary).

    Served from the two-second cache when warm, so one model call costs at
    most one small query.
    """
    now = time.monotonic()
    if _settings_cache and now - _settings_cache[0] < _SETTINGS_TTL:
        return _settings_cache[1]
    from app.database import async_session

    try:
        async with async_session() as db:
            return await get_settings(db)
    except Exception:  # noqa: BLE001 - the database, not the shield, is the problem here
        # Keep the last known settings rather than let a database hiccup
        # decide the policy either way; with nothing known the shield is off,
        # which is the state a fresh install is in.
        if _settings_cache:
            return _settings_cache[1]
        logger.warning("PII Shield settings could not be read; assuming the shield is off", exc_info=True)
        return ShieldSettings()


async def is_enabled() -> bool:
    """Read the flag with a standalone session (for call sites without a db)."""
    return (await get_settings_standalone()).enabled


# ── Roster: the session's own people plus the user's protected terms ───────

_roster_cache: dict[uuid.UUID, tuple[float, list[RosterEntry]]] = {}


def invalidate_roster(session_id: uuid.UUID | None = None) -> None:
    if session_id is None:
        _roster_cache.clear()
    else:
        _roster_cache.pop(session_id, None)


def _is_generic_speaker_name(name: str) -> bool:
    lowered = name.strip().lower()
    return (
        not lowered
        or lowered == "unknown"
        or lowered.startswith("participant ")
        or lowered.startswith("remote participant ")
        or lowered in ("me", "you", "speaker")
        or has_tokens(name)
    )


_ROSTER_CATEGORIES = (PERSON, ORG, LOCATION)


async def session_roster(db: AsyncSession, session_id: uuid.UUID, settings: ShieldSettings) -> list[RosterEntry]:
    """Known names for this session: its speakers, the protected terms, and
    every name the session's vault already holds.

    The vault matters most. A speaker's stored name becomes a token the
    moment it is written, so the Speaker row no longer says "Bill Brown";
    the vault does, and a later "Brown agreed" in the transcript must still
    map to the same token whether or not the on-device model is present.
    """
    cached = _roster_cache.get(session_id)
    now = time.monotonic()
    if cached and now - cached[0] < ROSTER_TTL_SECONDS:
        return cached[1]
    entries: list[RosterEntry] = []
    seen: set[tuple[str, str]] = set()

    def add(value: str, category: str) -> None:
        key = (category, value.strip().casefold())
        if value.strip() and key not in seen:
            seen.add(key)
            entries.append(RosterEntry(value.strip(), category))

    result = await db.execute(select(Speaker).where(Speaker.session_id == session_id))
    for speaker in result.scalars().all():
        for name in (speaker.name, speaker.display_name):
            if name and not _is_generic_speaker_name(name):
                add(name, PERSON)
    for term in settings.protected_terms:
        add(term["value"], term["category"])
    for token, value in (await vault.reveal_map(db, session_id)).items():
        category = token[1:token.index("_")]
        if category in _ROSTER_CATEGORIES:
            add(value, category)
    _roster_cache[session_id] = (now, entries)
    return entries


# ── Encode path ───────────────────────────────────────────────────────────

def detect(text: str, roster: list[RosterEntry], settings: ShieldSettings, *, use_ner: bool | None = None) -> list[Span]:
    """Every span the shield would replace, overlaps resolved. Pure CPU."""
    categories = set(settings.categories)
    spans = find_patterns(text, categories)
    spans.extend(find_roster(text, roster, categories))
    if (settings.ner if use_ner is None else use_ner) and categories & {PERSON, ORG, LOCATION}:
        spans.extend(ner.find_entities(text, categories))
    # Never re-tokenize a token, and never split one.
    token_ranges = [(m.start(), m.end()) for m in TOKEN_PATTERN.finditer(text)]
    if token_ranges:
        spans = [
            s for s in spans
            if not any(s.start < end and start < s.end for start, end in token_ranges)
        ]
    return resolve_spans(spans)


async def protect_text(
    db: AsyncSession,
    session_id: uuid.UUID,
    text: str | None,
    *,
    settings: ShieldSettings | None = None,
) -> str:
    """Return ``text`` with every detected value replaced by its session token.

    Safe to call on every ingress path: with the shield off, or on empty
    input, the text comes back untouched and nothing is queried.
    """
    if not text:
        return text or ""
    settings = settings or await get_settings(db)
    if not settings.enabled:
        return text
    roster = await session_roster(db, session_id, settings)
    spans = await asyncio.to_thread(detect, text, roster, settings)
    if not spans:
        return text
    pieces: list[str] = []
    cursor = 0
    known_before = await vault.entry_count(db, session_id)
    for span in spans:
        token = await vault.token_for(db, session_id, span.category, span.value)
        pieces.append(text[cursor:span.start])
        pieces.append(token)
        cursor = span.end
    pieces.append(text[cursor:])
    if await vault.entry_count(db, session_id) != known_before:
        # A newly minted name joins the roster for the very next line.
        invalidate_roster(session_id)
    return "".join(pieces)


async def protect_name(db: AsyncSession, session_id: uuid.UUID, name: str | None) -> str:
    """A speaker's name is a person's name by definition: no detection needed.

    Generic labels ("Participant 2", "Unknown") and values that are already
    tokens pass through; anything else becomes the session's PERSON token.
    """
    if not name or not name.strip():
        return name or ""
    settings = await get_settings(db)
    if not settings.enabled or PERSON not in settings.categories or _is_generic_speaker_name(name):
        return name
    token = await vault.token_for(db, session_id, PERSON, name.strip())
    invalidate_roster(session_id)
    return token


def forget_session(session_id: uuid.UUID) -> None:
    """Drop every cache for a deleted session."""
    vault.forget(session_id)
    invalidate_roster(session_id)


async def protect_fields(db: AsyncSession, session_id: uuid.UUID, obj: Any, fields: tuple[str, ...]) -> None:
    """Protect the named string attributes of an ORM row in place."""
    settings = await get_settings(db)
    if not settings.enabled:
        return
    for name in fields:
        value = getattr(obj, name, None)
        if isinstance(value, str) and value:
            setattr(obj, name, await protect_text(db, session_id, value, settings=settings))


async def preview(db: AsyncSession, text: str, session_id: uuid.UUID | None = None) -> dict:
    """What the shield would do to ``text``, without touching the vault.

    Tokens are numbered from 1 in the order found; the real session vault
    would reuse existing ordinals for values it has already seen.
    """
    settings = await get_settings(db)
    roster = await session_roster(db, session_id, settings) if session_id else [
        RosterEntry(t["value"], t["category"]) for t in settings.protected_terms
    ]
    spans = await asyncio.to_thread(detect, text, roster, settings)
    counters: dict[str, int] = {}
    seen: dict[tuple[str, str], str] = {}
    pieces: list[str] = []
    cursor = 0
    findings = []
    for span in spans:
        key = (span.category, span.value.casefold())
        token = seen.get(key)
        if token is None:
            counters[span.category] = counters.get(span.category, 0) + 1
            token = vault.make_token(span.category, counters[span.category])
            seen[key] = token
        pieces.append(text[cursor:span.start])
        pieces.append(token)
        cursor = span.end
        findings.append({"text": span.text, "category": span.category, "token": token, "source": span.source, "score": round(span.score, 2)})
    pieces.append(text[cursor:])
    return {"protected": "".join(pieces), "findings": findings, "enabled": settings.enabled}


# ── Decode path ───────────────────────────────────────────────────────────

def substitute(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Replace every token in ``text`` that ``mapping`` knows. Pure."""
    if not text or not mapping:
        return text, 0
    count = 0

    def replace(match) -> str:
        nonlocal count
        category = match.group(1) or match.group(3)
        ordinal = match.group(2) or match.group(4)
        value = mapping.get(vault.make_token(category, ordinal))
        if value:
            count += 1
            return value
        return match.group(0)

    return TOKEN_PATTERN.sub(replace, text), count


async def reveal_text(
    db: AsyncSession,
    session_id: uuid.UUID,
    text: str | None,
    *,
    route: str = "",
    audit: bool = True,
) -> str:
    """Substitute the session's real values back into ``text``. UI only."""
    if not text or not has_tokens(text):
        return text or ""
    mapping = await vault.reveal_map(db, session_id)
    revealed, count = substitute(text, mapping)
    if count and audit:
        await record_reveal(session_id, route, count)
    return revealed


def _walk(obj: Any, mapping: dict[str, str]) -> tuple[Any, int]:
    if isinstance(obj, str):
        return substitute(obj, mapping)
    if isinstance(obj, list):
        total = 0
        out = []
        for item in obj:
            value, count = _walk(item, mapping)
            out.append(value)
            total += count
        return out, total
    if isinstance(obj, dict):
        total = 0
        out = {}
        for key, item in obj.items():
            value, count = _walk(item, mapping)
            out[key] = value
            total += count
        return out, total
    return obj, 0


async def reveal_payload(
    db: AsyncSession,
    session_id: uuid.UUID,
    payload: Any,
    *,
    route: str = "",
    audit: bool = True,
) -> Any:
    """Reveal every string inside a JSON-shaped payload (dict/list/str)."""
    mapping = await vault.reveal_map(db, session_id)
    if not mapping:
        return payload
    revealed, count = _walk(payload, mapping)
    if count and audit:
        await record_reveal(session_id, route, count)
    return revealed


async def record_reveal(session_id: uuid.UUID | None, route: str, count: int) -> None:
    """Append one audit row in its own transaction; never raises."""
    from app.database import async_session

    try:
        async with async_session() as db:
            db.add(PiiRevealEvent(session_id=session_id, route=route[:160], token_count=count))
            await db.commit()
    except Exception:  # noqa: BLE001 - the audit trail must not break the page it describes
        logger.warning("Could not record a PII reveal event", exc_info=True)


async def warm_up_ner(db: AsyncSession) -> None:
    """Download and load the NER model ahead of the first transcript."""
    settings = await get_settings(db)
    if settings.enabled and settings.ner:
        await asyncio.to_thread(ner.get_model, True)

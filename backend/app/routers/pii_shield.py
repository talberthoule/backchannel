"""PII Shield settings, status, preview, and the per-session ledger.

Two routers. The workspace one (``/api/pii-shield``) holds the switch, the
category list, the protected terms, and the on-device model's state. The
session one (``/api/sessions/{id}/pii``) is the decode side: the ledger lists
what was protected in a session with its real values (audited like every
reveal), and ``protect`` runs the encode path over text a session stored
before the shield was turned on.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Directive, Document, Question, Session, Speaker, TranscriptEntry
from app.services.pii import egress, ner, shield, vault
from app.services.pii.status import status as shield_status
from app.services.pii.recognizers import CATEGORIES

router = APIRouter(prefix="/api/pii-shield", tags=["pii-shield"])
session_router = APIRouter(prefix="/api/sessions/{session_id}/pii", tags=["pii-shield"])


class ProtectedTerm(BaseModel):
    value: str = Field(min_length=1, max_length=200)
    category: str = Field(default="ORG")


class ShieldUpdate(BaseModel):
    enabled: bool | None = None
    categories: list[str] | None = None
    ner: bool | None = None
    protected_terms: list[ProtectedTerm] | None = None
    prompt_log: bool | None = None


class PreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    session_id: uuid.UUID | None = None


@router.get("")
async def get_status(db: AsyncSession = Depends(get_db)):
    return await shield_status(db)


def _merge_update(current: shield.ShieldSettings, update: ShieldUpdate) -> shield.ShieldSettings:
    if update.enabled is not None:
        current.enabled = update.enabled
    if update.categories is not None:
        unknown = [c for c in update.categories if c not in CATEGORIES]
        if unknown:
            raise HTTPException(400, f"Unknown categories: {', '.join(unknown)}")
        current.categories = list(dict.fromkeys(update.categories))
    if update.ner is not None:
        current.ner = update.ner
    if update.prompt_log is not None:
        current.prompt_log = update.prompt_log
    if update.protected_terms is not None:
        current.protected_terms = [_valid_term(term) for term in update.protected_terms if term.value.strip()]
    return current


def _valid_term(term: ProtectedTerm) -> dict:
    if term.category not in CATEGORIES:
        raise HTTPException(400, f"Unknown category: {term.category}")
    return {"value": term.value.strip(), "category": term.category}


@router.put("")
async def update_settings(update: ShieldUpdate, db: AsyncSession = Depends(get_db)):
    current = _merge_update(await shield.get_settings(db), update)
    await shield.set_settings(db, current)
    await db.commit()
    if current.enabled and current.ner and not ner.is_installed():
        # Fetch in the background; the status reports progress on the next read.
        asyncio.create_task(asyncio.to_thread(ner.get_model, True))
    return await shield_status(db)


@router.post("/preview")
async def preview(body: PreviewIn, db: AsyncSession = Depends(get_db)):
    return await shield.preview(db, body.text, body.session_id)


@router.get("/egress")
async def outbound_prompts(limit: int = 50):
    """The newest outbound model prompts, exactly as sent (prompt log).

    Not session-scoped in the path, so the reveal middleware leaves the
    tokens as tokens: this is the view of what the models received.
    """
    limit = max(1, min(limit, 200))
    entries = egress.recent(limit)
    return {"enabled": (await shield.get_settings_standalone()).prompt_log, "entries": entries}


@router.delete("/egress", status_code=204)
async def clear_outbound_prompts():
    egress.clear()


@router.post("/ner/install")
async def install_ner(db: AsyncSession = Depends(get_db)):
    """Download and load the on-device model now rather than on first use."""
    ner.reset_for_tests()
    model = await asyncio.to_thread(ner.get_model, True)
    if model is None:
        raise HTTPException(503, ner.load_error() or "The on-device NER model could not be installed.")
    return (await shield_status(db))["ner"]


@session_router.get("/summary")
async def session_summary(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """How many values the shield holds for this session, by category.

    Counts only: nothing is decrypted, so the call is not a reveal.
    """
    rows = (
        await db.execute(
            select(vault.PiiVaultEntry.category, func.count(vault.PiiVaultEntry.id))
            .where(vault.PiiVaultEntry.session_id == session_id)
            .group_by(vault.PiiVaultEntry.category)
        )
    ).all()
    counts = {category: int(count) for category, count in rows}
    return {"counts": counts, "total": sum(counts.values())}


@session_router.get("")
async def session_ledger(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """What the shield protected in this session, with the real values.

    Tokens are returned as category and ordinal rather than as the bracketed
    string, so the reveal middleware has nothing to substitute here; the
    values themselves are revealed explicitly and audited as one request.
    """
    rows = (
        await db.execute(
            select(vault.PiiVaultEntry)
            .where(vault.PiiVaultEntry.session_id == session_id)
            .order_by(vault.PiiVaultEntry.category, vault.PiiVaultEntry.ordinal)
        )
    ).scalars().all()
    entries = [
        {"category": row.category, "ordinal": row.ordinal, "value": vault.decrypt(row.value_encrypted)}
        for row in rows
    ]
    if entries:
        await shield.record_reveal(session_id, "ledger", len(entries))
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    return {"entries": entries, "counts": counts}


_QUESTION_FIELDS = (
    "question", "rationale", "source_context", "answer_summary",
    "followup_question", "enrichment_notes", "offering_match",
)


class _Protector:
    """Runs the encode path over stored rows and counts what changed."""

    def __init__(self, db: AsyncSession, session_id: uuid.UUID, settings: shield.ShieldSettings):
        self.db = db
        self.session_id = session_id
        self.settings = settings
        self.changed = {"transcripts": 0, "insights": 0, "directives": 0, "documents": 0, "speakers": 0, "session": 0}

    async def text_attr(self, obj, attr: str) -> bool:
        value = getattr(obj, attr, None)
        if not isinstance(value, str) or not value:
            return False
        protected = await shield.protect_text(self.db, self.session_id, value, settings=self.settings)
        if protected == value:
            return False
        setattr(obj, attr, protected)
        return True

    async def rows(self, model, attrs: tuple[str, ...], bucket: str) -> None:
        result = await self.db.execute(select(model).where(model.session_id == self.session_id))
        for row in result.scalars().all():
            touched = [await self.text_attr(row, attr) for attr in attrs]
            self.changed[bucket] += int(any(touched))

    async def speakers(self) -> None:
        result = await self.db.execute(select(Speaker).where(Speaker.session_id == self.session_id))
        for speaker in result.scalars().all():
            touched = False
            for attr in ("name", "display_name"):
                value = getattr(speaker, attr, "") or ""
                protected = await shield.protect_name(self.db, self.session_id, value)
                if protected != value:
                    setattr(speaker, attr, protected)
                    touched = True
            self.changed["speakers"] += int(touched)


@session_router.post("/protect")
async def protect_existing(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Run the encode path over everything this session already stores.

    For sessions recorded before the shield was on. Speakers go last so the
    roster still carries their real names while the transcript is scanned.
    """
    settings = await shield.get_settings(db)
    if not settings.enabled:
        raise HTTPException(400, "Turn the PII Shield on first.")
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    protector = _Protector(db, session_id, settings)
    touched = [await protector.text_attr(session, attr) for attr in ("name", "notes", "meeting_context")]
    protector.changed["session"] = sum(touched)
    await protector.rows(TranscriptEntry, ("text",), "transcripts")
    await protector.rows(Question, _QUESTION_FIELDS, "insights")
    await protector.rows(Directive, ("text",), "directives")
    await protector.rows(Document, ("summary",), "documents")
    await protector.speakers()

    await db.commit()
    shield.invalidate_roster(session_id)
    return {"changed": protector.changed, "vault_entries": await vault.entry_count(db, session_id)}

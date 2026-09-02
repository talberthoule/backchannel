"""The PII vault: per-session tokens for real values, stored encrypted.

Encode path (``token_for``): the value is normalized, keyed-hashed for lookup,
and either matched to the session's existing token or given the next ordinal
in its category. The stored ciphertext is Fernet under a key derived from the
DATA_DIR master key for this purpose alone, so the vault shares the
credentials' root of trust without sharing their key.

Decode path (``reveal_map``): the session's token-to-value map, decrypted on
demand. Only ``shield.reveal_text`` calls it.

Both paths go through an in-process cache per session. The application is a
single process, every write lands in the cache before the transaction ends,
and the cache is dropped when a session is deleted, so a cached map is never
stale for longer than one request.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PiiVaultEntry
from app.services.redaction import register_secret
from app.services.pii.recognizers import CATEGORIES, normalize_value
from app.services.secrets import derive_subkey

logger = logging.getLogger(__name__)

_VAULT_PURPOSE = b"backchannel.pii.vault.v1"
_LOOKUP_PURPOSE = b"backchannel.pii.lookup.v1"

_CATEGORY_ALTERNATION = "|".join(CATEGORIES)
# The bracketed form is what the shield writes; the bare form is what a model
# sometimes hands back after rewriting a sentence around the token.
TOKEN_PATTERN = re.compile(rf"\[({_CATEGORY_ALTERNATION})_(\d+)\]|\b({_CATEGORY_ALTERNATION})_(\d+)\b")


def make_token(category: str, ordinal: int) -> str:
    return f"[{category}_{ordinal}]"


def has_tokens(text: str | None) -> bool:
    return bool(text) and TOKEN_PATTERN.search(text) is not None


@dataclass
class _SessionVault:
    by_hmac: dict[str, str] = field(default_factory=dict)      # value_hmac -> token
    by_token: dict[str, str] = field(default_factory=dict)     # token -> ciphertext
    next_ordinal: dict[str, int] = field(default_factory=dict)  # category -> next free
    loaded: bool = False


_vaults: dict[uuid.UUID, _SessionVault] = {}
_lock = threading.Lock()
_fernet: Fernet | None = None
_lookup_key: bytes | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(base64.urlsafe_b64encode(derive_subkey(_VAULT_PURPOSE)))
    return _fernet


def _get_lookup_key() -> bytes:
    global _lookup_key
    if _lookup_key is None:
        _lookup_key = derive_subkey(_LOOKUP_PURPOSE)
    return _lookup_key


def value_hmac(category: str, value: str) -> str:
    normalized = normalize_value(value, category)
    return hmac.new(_get_lookup_key(), f"{category}\x00{normalized}".encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


# Vault values shorter than this stay out of the log scrubber: masking a
# four-letter first name would also eat it inside ordinary words.
PII_LOG_SCRUB_MIN_LENGTH = 5

# Every plaintext value this process has minted or decrypted, with its
# category. The egress tripwire (services/pii/egress.py) checks outbound
# prompts against it; the log scrubber gets the same values.
_plaintext_seen: dict[str, str] = {}


def _remember_plaintext(value: str, category: str) -> None:
    value = value.strip()
    if not value:
        return
    register_secret(value, min_length=PII_LOG_SCRUB_MIN_LENGTH)
    with _lock:
        _plaintext_seen.setdefault(value, category)


def known_plaintext_values() -> list[tuple[str, str]]:
    """(value, category) for every vault value seen by this process."""
    with _lock:
        return list(_plaintext_seen.items())


def _category_of(token: str) -> str:
    return token[1:token.index("_")] if token.startswith("[") and "_" in token else ""


def decrypt(ciphertext: str, category: str = "") -> str:
    try:
        value = _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        _remember_plaintext(value, category)
        return value
    except (InvalidToken, ValueError):
        logger.warning("A PII vault entry could not be decrypted; master key changed?")
        return ""


def _vault(session_id: uuid.UUID) -> _SessionVault:
    with _lock:
        vault = _vaults.get(session_id)
        if vault is None:
            vault = _SessionVault()
            _vaults[session_id] = vault
        return vault


async def _ensure_loaded(db: AsyncSession, session_id: uuid.UUID) -> _SessionVault:
    vault = _vault(session_id)
    if vault.loaded:
        return vault
    result = await db.execute(select(PiiVaultEntry).where(PiiVaultEntry.session_id == session_id))
    rows = list(result.scalars().all())
    with _lock:
        if not vault.loaded:
            for row in rows:
                vault.by_hmac[row.value_hmac] = row.token
                vault.by_token[row.token] = row.value_encrypted
                vault.next_ordinal[row.category] = max(vault.next_ordinal.get(row.category, 1), row.ordinal + 1)
            vault.loaded = True
    return vault


async def token_for(db: AsyncSession, session_id: uuid.UUID, category: str, value: str) -> str:
    """The session's token for this value, minting one on first sight.

    The new row is flushed, not committed: it belongs to the caller's
    transaction so a rolled-back transcript write leaves no orphan token.
    """
    vault = await _ensure_loaded(db, session_id)
    digest = value_hmac(category, value)
    existing = vault.by_hmac.get(digest)
    if existing:
        return existing
    with _lock:
        ordinal = vault.next_ordinal.get(category, 1)
        vault.next_ordinal[category] = ordinal + 1
    token = make_token(category, ordinal)
    _remember_plaintext(value, category)
    row = PiiVaultEntry(
        session_id=session_id,
        category=category,
        ordinal=ordinal,
        token=token,
        value_hmac=digest,
        value_encrypted=encrypt(value.strip()),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Another writer minted this value first (two imports racing). Drop
        # our row, reload, and use theirs.
        await db.rollback()
        with _lock:
            _vaults.pop(session_id, None)
        vault = await _ensure_loaded(db, session_id)
        found = vault.by_hmac.get(digest)
        if found:
            return found
        raise
    with _lock:
        vault.by_hmac[digest] = token
        vault.by_token[token] = row.value_encrypted
    return token


async def reveal_map(db: AsyncSession, session_id: uuid.UUID) -> dict[str, str]:
    """token -> real value for one session. Decode path only."""
    vault = await _ensure_loaded(db, session_id)
    with _lock:
        items = list(vault.by_token.items())
    return {token: decrypt(ciphertext, _category_of(token)) for token, ciphertext in items}


async def entry_count(db: AsyncSession, session_id: uuid.UUID) -> int:
    vault = await _ensure_loaded(db, session_id)
    return len(vault.by_token)


def forget(session_id: uuid.UUID | None = None) -> None:
    """Drop cached state: one session (on delete) or everything (tests)."""
    with _lock:
        if session_id is None:
            _vaults.clear()
        else:
            _vaults.pop(session_id, None)


def reset_keys_for_tests() -> None:
    global _fernet, _lookup_key
    _fernet = None
    _lookup_key = None
    with _lock:
        _plaintext_seen.clear()
    forget()

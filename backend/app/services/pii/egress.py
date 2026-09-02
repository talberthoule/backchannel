"""The model-call boundary: a tripwire and a prompt log.

Every text prompt leaves the process through ``llm.generate_text`` or
``llm.generate_json``, and both call ``guard`` first.

Tripwire. While the shield is on, a prompt that still carries a value the
vault has seen in plaintext (a name, an email, a card number) is a defect
somewhere upstream, never a legitimate call. The prompt is refused and the
event is written to the audit trail, so a gap in the encode path costs one
model call rather than one disclosure.

Prompt log. When ``prompt_log`` is on in the shield settings, every outbound
prompt is appended to ``DATA_DIR/prompt-log/outbound.jsonl`` exactly as it
would be sent, with the source agent, model and session. That file is the
evidence that tokenization works: it should contain ``[PERSON_1]`` and never
a name. It is written raw on purpose, bypassing the log scrubber, because a
scrubbed record could not show a leak. It never leaves the machine.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.pii import vault
from app.services.pii.recognizers import CARD, IP, PHONE, SSN

logger = logging.getLogger(__name__)

LOG_FILE_NAME = "outbound.jsonl"
MAX_LOG_BYTES = 25 * 1024 * 1024
MAX_PROMPT_CHARS_STORED = 60_000
# Values shorter than this are too easily part of an ordinary word to judge.
MIN_VALUE_LENGTH = 5
_DIGIT_CATEGORIES = {PHONE, SSN, CARD, IP}


class PiiEgressBlocked(ValueError):
    """An outbound prompt carried a vault value while the shield was on."""

    def __init__(self, source: str, model_id: str, categories: list[str]):
        kinds = ", ".join(sorted(set(categories))) or "personal data"
        super().__init__(
            f"The PII Shield stopped a model call ({source or 'text generation'} on {model_id}): "
            f"the prompt still carried {kinds} in plain text. Nothing was sent. "
            "Protect the session (POST /api/sessions/{id}/pii/protect) or report the "
            "path that produced this prompt; the Privacy tab's prompt log shows it."
        )
        self.source = source
        self.model_id = model_id
        self.categories = categories


def log_dir() -> Path:
    from app.services.secrets import data_dir

    return data_dir() / "prompt-log"


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def find_leaks(text: str) -> list[tuple[str, str]]:
    """(value, category) for every known vault value present in ``text``.

    Text categories match as whole words with their original casing, the
    same rule the roster uses; numeric categories match on their digits so a
    re-spaced phone number is still caught.
    """
    if not text:
        return []
    found: list[tuple[str, str]] = []
    text_digits: str | None = None
    for value, category in vault.known_plaintext_values():
        if len(value) < MIN_VALUE_LENGTH:
            continue
        if category in _DIGIT_CATEGORIES:
            digits = _digits(value)
            if len(digits) >= 7:
                if text_digits is None:
                    text_digits = _digits(text)
                if digits in text_digits:
                    found.append((value, category))
            continue
        if re.search(rf"(?<![\w@.])({re.escape(value)})(?![\w@])", text):
            found.append((value, category))
    return found


def _log_path() -> Path:
    return log_dir() / LOG_FILE_NAME


def _rotate_if_large(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            older = path.with_suffix(".1.jsonl")
            if older.exists():
                older.unlink()
            path.rename(older)
    except OSError:
        logger.warning("Could not rotate the prompt log", exc_info=True)


def record(entry: dict) -> None:
    """Append one outbound-prompt record. Never raises."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_large(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("Could not write the prompt log", exc_info=True)


def recent(limit: int = 50) -> list[dict]:
    """The newest ``limit`` records, newest first."""
    path = _log_path()
    if not path.exists():
        return []
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            chunk = min(size, 4 * 1024 * 1024)
            handle.seek(size - chunk)
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    if size > 4 * 1024 * 1024 and lines:
        lines = lines[1:]  # the first line of a mid-file read is a fragment
    records = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
        if len(records) >= limit:
            break
    return records


def clear() -> int:
    """Delete the prompt log; returns the number of files removed."""
    removed = 0
    for path in (_log_path(), _log_path().with_suffix(".1.jsonl")):
        try:
            if path.exists():
                path.unlink()
                removed += 1
        except OSError:
            logger.warning("Could not remove %s", path, exc_info=True)
    return removed


async def guard(
    prompt: str,
    *,
    system: str | None = None,
    model_id: str = "",
    session_id: object | None = None,
    source: str = "",
) -> None:
    """Check an outbound prompt; log it if asked; refuse it if it leaks."""
    from app.services.pii.shield import get_settings_standalone, record_reveal

    settings = await get_settings_standalone()
    if not settings.enabled and not settings.prompt_log:
        return
    text = f"{system}\n\n{prompt}" if system else prompt
    leaks = find_leaks(text) if settings.enabled else []
    blocked = bool(leaks)
    if settings.prompt_log:
        record({
            "at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "model_id": model_id,
            "session_id": str(session_id) if session_id else None,
            "chars": len(text),
            "tokens_present": bool(vault.has_tokens(text)),
            "blocked": blocked,
            "leaks": [{"category": category, "value": value} for value, category in leaks],
            "prompt": text[:MAX_PROMPT_CHARS_STORED],
            "truncated": len(text) > MAX_PROMPT_CHARS_STORED,
        })
    if blocked:
        categories = [category for _, category in leaks]
        logger.warning(
            "PII egress tripwire: %d vault value(s) (%s) found in the %s prompt for %s; call refused",
            len(leaks), ", ".join(sorted(set(categories))), source or "text", model_id,
        )
        try:
            sid = uuid.UUID(str(session_id)) if session_id else None
        except ValueError:
            sid = None
        await record_reveal(sid, f"egress-blocked:{source or 'text'}", len(leaks))
        raise PiiEgressBlocked(source, model_id, categories)

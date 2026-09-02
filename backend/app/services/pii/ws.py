"""Reveal protected values on the WebSocket path to the interface.

Every live message - transcript lines, insights, signals, briefing updates -
is built by hand somewhere in the orchestrator or the audio handler. Rather
than teach each of them about the vault, the socket handed to them reveals at
the send boundary. Anything not sent through ``send_json`` (binary frames,
close) is delegated untouched.

Reveals are audited in batches: a talking call sends a message every few
seconds, and one audit row per line would say nothing a per-minute row does
not.
"""

from __future__ import annotations

import json
import time
import uuid

from app.services.pii import shield, vault

AUDIT_FLUSH_SECONDS = 60.0


class RevealingWebSocket:
    def __init__(self, inner, session_id: uuid.UUID):
        self._inner = inner
        self._session_id = session_id
        self._pending = 0
        self._last_flush = time.monotonic()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def send_json(self, data, mode: str = "text") -> None:
        if isinstance(data, (dict, list)) and vault.has_tokens(json.dumps(data, ensure_ascii=False)):
            from app.database import async_session

            async with async_session() as db:
                mapping = await vault.reveal_map(db, self._session_id)
            if mapping:
                data, count = shield._walk(data, mapping)
                self._pending += count
                await self._maybe_flush()
        await self._inner.send_json(data, mode)

    async def close(self, *args, **kwargs):
        await self._flush()
        return await self._inner.close(*args, **kwargs)

    async def _maybe_flush(self) -> None:
        if self._pending and time.monotonic() - self._last_flush >= AUDIT_FLUSH_SECONDS:
            await self._flush()

    async def _flush(self) -> None:
        if not self._pending:
            return
        count, self._pending = self._pending, 0
        self._last_flush = time.monotonic()
        await shield.record_reveal(self._session_id, "ws", count)

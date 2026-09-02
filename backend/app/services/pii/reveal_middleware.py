"""Reveal protected values in JSON responses bound for the local interface.

One choke point for the REST decode path. Every session-scoped JSON response
(``/api/sessions/{id}/...``, the session list, and the session detail) has its
tokens substituted with the session's real values before it leaves the
process. Responses that are not JSON, or not session-scoped, pass through
untouched; the exports and multi-session chat handle their own reveal because
their scope is not in the path.

The interface is the only caller this middleware serves: the request guard
in front of it already refuses foreign origins and unknown hosts (ALP-351),
and every reveal is written to the audit trail.
"""

from __future__ import annotations

import json
import re
import uuid

from app.services.pii import shield, vault

_SESSION_PATH = re.compile(r"^/api/sessions/([0-9a-fA-F-]{36})(?:/|$)")
_LIST_PATH = re.compile(r"^/api/sessions/?$")


def _scope_target(scope) -> tuple[uuid.UUID | None, bool]:
    """(session id, is the session list) for a request, or (None, False)."""
    path = scope.get("path", "")
    match = _SESSION_PATH.match(path)
    if match:
        try:
            return uuid.UUID(match.group(1)), False
        except ValueError:
            return None, False
    is_list = _LIST_PATH.match(path) is not None and scope.get("method") == "GET"
    return None, is_list


def _is_revealable(message) -> bool:
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in message.get("headers", [])}
    return "application/json" in headers.get("content-type", "") and message.get("status", 200) < 400


class _BufferedSender:
    """Holds a JSON response until its last chunk, then sends the revealed body."""

    def __init__(self, send, reveal):
        self.send = send
        self.reveal = reveal
        self.start_message = None
        self.body_parts: list[bytes] = []
        self.passthrough = False

    async def __call__(self, message):
        kind = message["type"]
        if kind == "http.response.start" and _is_revealable(message):
            self.start_message = message
            return
        if kind == "http.response.start":
            self.passthrough = True
        if kind != "http.response.body" or self.passthrough:
            await self.send(message)
            return
        self.body_parts.append(message.get("body", b""))
        if message.get("more_body"):
            return
        revealed = await self.reveal(b"".join(self.body_parts))
        headers = [
            (k, v) for k, v in self.start_message.get("headers", [])
            if k.decode("latin-1").lower() != "content-length"
        ]
        headers.append((b"content-length", str(len(revealed)).encode("latin-1")))
        await self.send({**self.start_message, "headers": headers})
        await self.send({"type": "http.response.body", "body": revealed, "more_body": False})


class PiiRevealMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        session_id, is_list = _scope_target(scope) if scope["type"] == "http" else (None, False)
        if session_id is None and not is_list:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def reveal(raw: bytes) -> bytes:
            return await self._reveal(raw, session_id, is_list, path)

        await self.app(scope, receive, _BufferedSender(send, reveal))

    async def _reveal(self, raw: bytes, session_id, is_list: bool, route: str) -> bytes:
        if not raw or not vault.has_tokens(raw.decode("utf-8", "replace")):
            return raw
        from app.database import async_session

        try:
            payload = json.loads(raw)
        except ValueError:
            return raw
        async with async_session() as db:
            if is_list and isinstance(payload, list):
                out = []
                for item in payload:
                    item_id = item.get("id") if isinstance(item, dict) else None
                    try:
                        sid = uuid.UUID(str(item_id)) if item_id else None
                    except ValueError:
                        sid = None
                    out.append(await shield.reveal_payload(db, sid, item, route=route) if sid else item)
                payload = out
            elif session_id is not None:
                payload = await shield.reveal_payload(db, session_id, payload, route=route)
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

"""Host and Origin guards for an API that has no user login.

Backchannel trusts whoever can reach it: the desktop build binds loopback and
the Docker stack sits behind the frontend proxy, so the API itself never asks
for credentials. Two browser tricks turn that trust into a problem for a
person who merely visits a hostile web page:

- DNS rebinding. The page's domain resolves to the attacker's server just long
  enough to load, then to 127.0.0.1. Later requests from that page hit the
  local API as a same-origin call, with the attacker's hostname in ``Host``.
- Cross-origin requests. A page on any origin can send requests to
  ``http://localhost:<port>``; the browser only withholds the *response* when
  CORS says so, and a form-shaped POST needs no preflight at all.

Both leave a fingerprint the server can check. The first carries a ``Host``
that is not one of ours; the second carries an ``Origin`` that is not one of
ours. This middleware rejects each before any router runs. Because the
allowed set must include every way a legitimate user reaches the app, the
rule is: loopback names, any IP address literal (a rebinding attack needs a
DNS name, so an IP-literal Host or Origin cannot be one), the Docker service
name, and anything listed in the environment:

- ``BACKCHANNEL_ALLOWED_HOSTS``: extra hostnames, comma-separated, for a
  Docker deployment reached by name (``backchannel.lan``). ``*`` disables the
  Host check.
- ``BACKCHANNEL_ALLOWED_ORIGINS``: extra origins (``https://tools.example``)
  that may call the API cross-origin, also used for CORS. ``*`` disables the
  Origin check (CORS then still restricts itself to the loopback pattern).
"""

from __future__ import annotations

import ipaddress
import logging
import os
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

ALLOWED_HOSTS_ENV = "BACKCHANNEL_ALLOWED_HOSTS"
ALLOWED_ORIGINS_ENV = "BACKCHANNEL_ALLOWED_ORIGINS"

# Names that only ever mean "this machine" (plus the Compose service name,
# which resolves nowhere outside the stack's own network).
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "backend"})

# Origins CORS accepts without configuration. Everything a local frontend
# could be served from: the app's own port, the Vite dev server, a preview.
CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\]|[A-Za-z0-9.-]+\.localhost)(:\d+)?$"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _env_list(name: str) -> list[str]:
    return [item.strip().lower() for item in os.environ.get(name, "").split(",") if item.strip()]


def _hostname_of(host_header: str) -> str:
    """Host header -> lowercase hostname without port; "" when unparseable."""
    try:
        return (urlsplit("//" + host_header.strip()).hostname or "").lower()
    except ValueError:
        return ""


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def hostname_allowed(hostname: str, extra_hosts: list[str] | None = None) -> bool:
    extra = _env_list(ALLOWED_HOSTS_ENV) if extra_hosts is None else extra_hosts
    if "*" in extra:
        return True
    name = (hostname or "").lower()
    if not name:
        return False
    if name in LOOPBACK_NAMES or name.endswith(".localhost"):
        return True
    if _is_ip_literal(name):
        return True
    return name in extra


def host_header_allowed(host_header: str, extra_hosts: list[str] | None = None) -> bool:
    return hostname_allowed(_hostname_of(host_header), extra_hosts)


def origin_allowed(
    origin: str,
    extra_hosts: list[str] | None = None,
    extra_origins: list[str] | None = None,
) -> bool:
    """Whether a browser Origin may issue state-changing requests.

    An origin is fine when its host is one of ours (same rule as Host) or it
    is listed verbatim in the environment. ``null`` - a sandboxed frame, a
    file:// page, a redirect from another site - is never ours.
    """
    origins = _env_list(ALLOWED_ORIGINS_ENV) if extra_origins is None else extra_origins
    if "*" in origins:
        return True
    value = (origin or "").strip().lower()
    if not value or value == "null":
        return False
    if value in origins:
        return True
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or parts.path not in ("", "/"):
        return False
    return hostname_allowed(parts.hostname or "", extra_hosts)


def cors_allowed_origins() -> list[str]:
    """Explicit origins for CORSMiddleware, from the environment."""
    return [o for o in _env_list(ALLOWED_ORIGINS_ENV) if o != "*"]


class RequestGuardMiddleware:
    """Reject requests whose Host or Origin is not one of ours.

    Applies to HTTP and WebSocket handshakes alike; a websocket with a foreign
    Host is closed before it is accepted, which the client sees as a 403.
    """

    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: list[str] | None = None,
        allowed_origins: list[str] | None = None,
    ) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host = headers.get("host", "")
        if not host_header_allowed(host, self.allowed_hosts):
            logger.warning(
                "Rejected request for unrecognized host %r; set %s to allow it",
                host[:120],
                ALLOWED_HOSTS_ENV,
            )
            await self._reject(scope, receive, send, 400, "Host header is not allowed")
            return
        # Browsers put an Origin on every WebSocket handshake and on every
        # state-changing HTTP request; a page on a foreign origin gets neither.
        # WebSockets are checked unconditionally because CORS never applied to
        # them: without this, a hostile page could open ws://127.0.0.1/ws/<id>
        # and both read the live transcript and drive the call.
        origin_checked = scope["type"] == "websocket" or scope.get("method", "GET").upper() not in _SAFE_METHODS
        if origin_checked:
            origin = headers.get("origin")
            if origin is not None and not origin_allowed(origin, self.allowed_hosts, self.allowed_origins):
                logger.warning(
                    "Rejected cross-origin %s from %r; set %s to allow it",
                    "websocket" if scope["type"] == "websocket" else scope.get("method"),
                    origin[:120],
                    ALLOWED_ORIGINS_ENV,
                )
                await self._reject(scope, receive, send, 403, "Origin is not allowed")
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status: int, message: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": message})
            return
        response = PlainTextResponse(message, status_code=status)
        await response(scope, receive, send)

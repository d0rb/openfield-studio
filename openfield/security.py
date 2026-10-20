"""Keep other web pages from driving the local server.

The app listens on loopback with no login, so a page open in the user's browser could otherwise talk to
it: a cross-site form post is a "simple request" (no preflight), its Host is 127.0.0.1 (which the host
allowlist accepts), and it could start paid renders or fill the disk. Every state-changing request is
therefore checked for where it came from.

Browsers always say: `Sec-Fetch-Site` on modern ones, `Origin` on every POST. Clients that are not
browsers (curl, scripts, the tests) send neither and pass. Reads are never blocked: cross-origin pages
cannot read the answers anyway, because the app sends no CORS headers.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# the largest body any route accepts is a 200 MB clip plus a 20 MB image; refuse bigger ones unread
MAX_BODY_BYTES = 230 * 1024 * 1024


def foreign_origin(headers: Mapping[str, str], allowed: frozenset[str] = frozenset()) -> str | None:
    """Why a browser's request looks like it came from a page on another origin, or None if it did not."""
    site = headers.get("sec-fetch-site")
    if site is not None:
        # "same-site" is another port on the same machine: another application, not this one
        if site in {"same-origin", "none"}:
            return None
        return f"it was sent from a page on another origin (Sec-Fetch-Site: {site})"
    origin = headers.get("origin")
    if origin is None:
        return None
    if origin.lower().rstrip("/") in allowed:
        return None
    host = headers.get("host", "").lower()
    if not urlsplit(origin).netloc or urlsplit(origin).netloc.lower() != host:
        return f"its Origin ({origin}) is not this server ({host or 'no Host header'})"
    return None


class SameOriginOnly:
    """ASGI middleware: refuse cross-origin state-changing requests and oversized bodies."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed = frozenset(o.lower().rstrip("/") for o in allowed_origins if o)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            reason = foreign_origin(headers, self.allowed)
            if reason:
                await _refuse(scope, receive, send, 403, "cross_origin",
                              f"Refused: {reason}. Only OpenField's own pages may change anything here.")
                return
            length = headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_BODY_BYTES:
                await _refuse(scope, receive, send, 413, "too_large",
                              f"That upload is larger than the {MAX_BODY_BYTES // (1024 * 1024)} MB the app accepts.")
                return
        await self.app(scope, receive, send)


async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, code: str, message: str) -> None:
    await JSONResponse({"error": {"code": code, "message": message}}, status_code=status)(scope, receive, send)

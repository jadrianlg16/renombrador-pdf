"""ASGI middleware that guards the API: allowed hosts, same-origin writes, body limits."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
MEBIBYTE = 1024 * 1024
DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def parse_allowed_hosts(extra: str | None) -> frozenset[str]:
    """Return the loopback host names plus the comma-separated names in ``extra``."""
    names = {name.strip().strip("[]").lower() for name in (extra or "").split(",")}
    return DEFAULT_ALLOWED_HOSTS | {name for name in names if name}


def host_name(netloc: str) -> str:
    """Return the lowercased host of ``host[:port]`` without IPv6 brackets; "" if invalid."""
    try:
        return urlsplit(f"//{netloc}").hostname or ""
    except ValueError:
        return ""


def is_cross_site(headers: Headers, allowed_hosts: frozenset[str]) -> bool:
    """Tell whether a browser sent this request from a page on another origin.

    Browsers attach ``Origin`` to every request that is not a GET or HEAD, so when it
    is present its host must be an allowed one and it must name the same host and port
    the request was sent to. Without it, ``Sec-Fetch-Site`` is the fallback. A request
    with neither header comes from a non-browser client such as curl or a script; a
    malicious web page cannot make the browser send that, so it is allowed.
    """
    origin = headers.get("origin")
    if origin is not None:
        try:
            origin_netloc = urlsplit(origin).netloc.lower()
        except ValueError:
            return True
        return (
            host_name(origin_netloc) not in allowed_hosts
            or origin_netloc != headers.get("host", "").lower()
        )
    return headers.get("sec-fetch-site") in {"cross-site", "same-site"}


class RequestGuardMiddleware:
    """Refuse requests for an unknown host name (DNS rebinding) and cross-site writes (CSRF).

    DNS rebinding points an attacker's domain at 127.0.0.1, so the browser treats the
    app as part of the attacker's site and sends that domain in ``Host``. Only loopback
    names and the ones listed in ALLOWED_HOSTS are served, so such a page gets 400 and
    can neither read nor change anything. The app has no login, so a session token would
    protect nothing; what matters is that no other site can make the operator's browser
    rename, skip or delete files.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer 400 to an unknown Host and 403 to a cross-site write; pass the rest on."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if host_name(headers.get("host", "")) not in self.allowed_hosts:
            detail = (
                "Nombre de host no permitido. Abre la aplicación en http://127.0.0.1 o "
                "http://localhost, o agrega el nombre a ALLOWED_HOSTS."
            )
            await JSONResponse({"detail": detail}, status_code=400)(scope, receive, send)
            return
        if scope["method"] not in SAFE_METHODS and is_cross_site(headers, self.allowed_hosts):
            detail = "Solicitud rechazada: viene de otro sitio web."
            await JSONResponse({"detail": detail}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Refuse request bodies above a per-path limit before the app reads them.

    Starlette parses a multipart upload completely before the endpoint runs, so a size
    check inside the endpoint only fires after the whole body is on disk. Here a
    declared ``Content-Length`` over the limit is answered with 413 without reading
    anything, and a body sent without one is counted as it streams in and cut off as
    soon as it passes the limit.
    """

    def __init__(self, app: ASGIApp, limits: Mapping[str, int], default_limit: int) -> None:
        self.app = app
        self.limits = dict(limits)
        self.default_limit = default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer 413 to an oversized body; count a streamed one as the app reads it."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.limits.get(scope["path"], self.default_limit)
        detail = f"La petición supera el límite de {limit // MEBIBYTE} MB."
        declared = Headers(scope=scope).get("content-length", "")
        # Uvicorn already rejects a malformed Content-Length; anything else is counted below.
        if declared.isdigit() and int(declared) > limit:
            await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI re-raises HTTPException from body parsing, so this becomes
                    # a 413 response instead of a generic 400 "error parsing the body".
                    raise HTTPException(status_code=413, detail=detail)
            return message

        await self.app(scope, limited_receive, send)

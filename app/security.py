"""ASGI middleware that guards the API: same-origin writes and request body limits."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
MEBIBYTE = 1024 * 1024


def is_cross_site(headers: Headers) -> bool:
    """Tell whether a browser sent this request from a page on another origin.

    Browsers attach ``Origin`` to every request that is not a GET or HEAD, so when it
    is present it must name the same host and port the request was sent to. Without
    it, ``Sec-Fetch-Site`` is the fallback. A request with neither header comes from a
    non-browser client such as curl or a script; a malicious web page cannot make the
    browser send that, so it is allowed.
    """
    origin = headers.get("origin")
    if origin is not None:
        if origin == "null":
            return True
        return urlsplit(origin).netloc.lower() != headers.get("host", "").lower()
    return headers.get("sec-fetch-site") in {"cross-site", "same-site"}


class SameOriginMiddleware:
    """Reject state-changing requests that a browser sent from another site (CSRF).

    The app has no login, so a session token would protect nothing; what matters is
    that a page on another site cannot make the operator's browser rename, skip or
    delete files. Reads stay open because the browser already hides cross-origin
    responses from the page that asked for them.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer 403 to a cross-site write; pass everything else through."""
        if (
            scope["type"] == "http"
            and scope["method"] not in SAFE_METHODS
            and is_cross_site(Headers(scope=scope))
        ):
            response = JSONResponse(
                {"detail": "Solicitud rechazada: viene de otro sitio web."}, status_code=403
            )
            await response(scope, receive, send)
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

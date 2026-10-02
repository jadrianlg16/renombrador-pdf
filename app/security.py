"""ASGI middleware that guards the API against cross-site writes."""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


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

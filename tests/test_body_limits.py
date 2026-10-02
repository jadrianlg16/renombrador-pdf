"""Request body limits: oversized requests are refused before the app reads them."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request

from app.security import BodySizeLimitMiddleware
from helpers import MINIMAL_PDF


def _limited_app(limit: int) -> tuple[BodySizeLimitMiddleware, list[str]]:
    """Wrap a body-echoing endpoint in the middleware; the list records each call."""
    calls: list[str] = []
    inner = FastAPI()

    @inner.post("/echo")
    async def echo(request: Request) -> dict:
        calls.append("endpoint")
        return {"size": len(await request.body())}

    return BodySizeLimitMiddleware(inner, limits={}, default_limit=limit), calls


def _drive(app, headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> tuple[int, int]:
    """Send one POST through the ASGI app; return (status, number of chunks it pulled)."""
    pulled = 0
    sent: list[dict] = []

    async def receive() -> dict:
        nonlocal pulled
        if pulled < len(chunks):
            pulled += 1
            return {
                "type": "http.request",
                "body": chunks[pulled - 1],
                "more_body": pulled < len(chunks),
            }
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/echo",
        "raw_path": b"/echo",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in sent if message["type"] == "http.response.start")
    return start["status"], pulled


def test_a_declared_length_over_the_limit_is_refused_without_reading():
    app, calls = _limited_app(limit=10)
    status, pulled = _drive(app, [(b"content-length", b"11")], [b"x" * 11])
    assert status == 413
    assert pulled == 0
    assert calls == []


def test_a_streamed_body_is_cut_off_once_it_passes_the_limit():
    app, _ = _limited_app(limit=10)
    status, pulled = _drive(app, [(b"transfer-encoding", b"chunked")], [b"abcd"] * 5)
    assert status == 413
    assert pulled == 3  # 4 + 4 + 4 bytes crosses 10; the last two chunks are never read


def test_a_body_within_the_limit_reaches_the_endpoint():
    app, calls = _limited_app(limit=10)
    status, pulled = _drive(app, [(b"content-length", b"8")], [b"abcd", b"efgh"])
    assert status == 200
    assert pulled == 2
    assert calls == ["endpoint"]


def test_an_upload_over_the_cap_is_refused_and_nothing_is_written(client):
    test_client, module = client
    oversized = str(module.MAX_UPLOAD_BYTES + 1)
    response = test_client.post(
        "/api/upload",
        files=[("files", ("grande.pdf", MINIMAL_PDF, "application/pdf"))],
        data={"folder": "Lote"},
        headers={"Content-Length": oversized},
    )
    assert response.status_code == 413
    assert "300 MB" in response.json()["detail"]
    assert list(module.settings.input_dir.iterdir()) == []


def test_json_requests_have_a_small_limit(client):
    test_client, module = client
    response = test_client.post(
        "/api/documents/x/approve",
        json={"name": "ANA", "ocr_text": "A" * (module.MAX_REQUEST_BYTES + 1)},
    )
    assert response.status_code == 413


def test_the_ui_can_read_the_upload_cap(client):
    test_client, module = client
    config = test_client.get("/api/config").json()
    assert config == {"max_upload_bytes": module.MAX_UPLOAD_BYTES}

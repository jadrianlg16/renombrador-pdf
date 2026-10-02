"""Test data and request helpers shared by the HTTP API tests."""

from __future__ import annotations

import importlib
import io
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType

from fastapi.testclient import TestClient
from httpx import Response

# The app only answers to loopback host names, so the test client uses one.
TEST_HOST = "localhost"

# The smallest file PyMuPDF opens as a one-page, 200 x 200 pt PDF.
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
)


@contextmanager
def open_app() -> Iterator[tuple[TestClient, ModuleType]]:
    """Reload ``app.main`` so it reads the current environment, and serve it in-process."""
    import app.main as main

    module = importlib.reload(main)
    try:
        with TestClient(module.app, base_url=f"http://{TEST_HOST}") as test_client:
            yield test_client, module
    finally:
        importlib.reload(main)


def upload(test_client: TestClient, names: list[str], **data: str) -> Response:
    """Upload one minimal PDF per name, as the browser does, with optional form fields."""
    files = [("files", (name, io.BytesIO(MINIMAL_PDF), "application/pdf")) for name in names]
    return test_client.post("/api/upload", files=files, data=data)

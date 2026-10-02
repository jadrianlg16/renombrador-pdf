"""Document endpoints: page rendering, review actions and their effect on disk."""

from __future__ import annotations

import pytest

from helpers import open_app, upload


def _png_width(png: bytes) -> int:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(png[16:20], "big")


def test_page_images_use_the_configured_render_dpi(app_env: pytest.MonkeyPatch):
    app_env.setenv("PDF_RENDER_DPI", "100")
    with open_app() as (test_client, _):
        upload(test_client, ["a.pdf"], folder="Lote")
        document_id = test_client.get("/api/documents").json()["documents"][0]["id"]
        page_url = f"/api/documents/{document_id}/page/1"

        default = test_client.get(page_url)
        assert default.status_code == 200
        explicit = test_client.get(page_url, params={"dpi": 100})
        assert _png_width(default.content) == _png_width(explicit.content)
        sharper = test_client.get(page_url, params={"dpi": 150})
        assert _png_width(default.content) < _png_width(sharper.content)

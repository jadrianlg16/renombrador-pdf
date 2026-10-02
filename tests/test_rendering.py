"""Rendering limits: huge pages are rendered at a lower resolution instead of exhausting memory."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from app import ocr

FULL_PAGE = {"x": 0, "y": 0, "width": 1, "height": 1}


def _pdf(path: Path, width: float, height: float) -> str:
    document = pymupdf.open()
    page = document.new_page(width=width, height=height)
    page.insert_text((72, 72), "ANA LOPEZ", fontsize=40)
    document.save(path)
    return str(path)


def _png_pixels(png: bytes) -> int:
    width, height = Image.open(io.BytesIO(png)).size
    return width * height


@pytest.mark.parametrize(
    ("width", "height", "dpi"), [(3000, 3000, 250), (3000, 3000, 450), (14400, 14400, 450)]
)
def test_capped_dpi_keeps_huge_pages_within_the_pixel_budget(width, height, dpi):
    capped = ocr.capped_dpi(width, height, dpi)
    assert capped < dpi
    assert (width / 72 * capped + 1) * (height / 72 * capped + 1) <= ocr.MAX_RENDER_PIXELS


def test_capped_dpi_leaves_ordinary_pages_alone():
    assert ocr.capped_dpi(612, 792, 150) == 150
    assert ocr.capped_dpi(612, 792, 450) == 450  # a whole letter page read for OCR


def test_huge_pages_and_crops_render_within_the_budget(tmp_path, monkeypatch):
    # A smaller budget keeps the test light; the arithmetic is the same at 40 Mpx.
    monkeypatch.setattr(ocr, "MAX_RENDER_PIXELS", 1_000_000)
    pdf = _pdf(tmp_path / "grande.pdf", 3000, 3000)

    png, _ = ocr.render_page(pdf, 1, 250)
    assert _png_pixels(png) <= 1_000_000
    crop = ocr.render_crop(pdf, 1, FULL_PAGE, 450)
    assert crop.shape[0] * crop.shape[1] <= 1_000_000


def test_the_page_endpoint_serves_a_huge_page_at_a_lower_resolution(client, monkeypatch):
    test_client, module = client
    monkeypatch.setattr(ocr, "MAX_RENDER_PIXELS", 1_000_000)
    _pdf(module.settings.input_dir / "grande.pdf", 3000, 3000)
    test_client.post("/api/sync")
    document_id = test_client.get("/api/documents").json()["documents"][0]["id"]

    response = test_client.get(f"/api/documents/{document_id}/page/1", params={"dpi": 250})
    assert response.status_code == 200
    assert _png_pixels(response.content) <= 1_000_000


def test_crop_previews_are_scaled_down(monkeypatch):
    monkeypatch.setattr("app.ocr.pytesseract.image_to_data", lambda *_a, **_k: {"text": []})
    wide = np.full((300, 6000, 3), 255, dtype=np.uint8)
    result = ocr.recognize_crop(wide, "spa")
    preview = Image.open(io.BytesIO(base64.b64decode(result["preview_original"])))
    assert max(preview.size) <= ocr.PREVIEW_MAX_SIDE

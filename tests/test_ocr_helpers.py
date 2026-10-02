"""OCR text cleanup, word segmentation and reading ranking (Tesseract is faked)."""

import cv2
import numpy as np

from app.ocr import (
    OCRCandidate,
    _needs_review,
    _visual_word_boxes,
    clean_ocr_text,
    join_name_parts,
    recognize_crop,
)


def test_clean_text_preserves_lines():
    cleaned = clean_ocr_text("  MARÍA   DEL CARMEN\n  DE LA GARZA  ")
    assert cleaned == "MARÍA DEL CARMEN\nDE LA GARZA"


def test_join_name_parts_flattens_multiple_lines_and_regions():
    assert join_name_parts(["MARÍA DEL\nCARMEN", "DE LA GARZA"]) == "MARÍA DEL CARMEN DE LA GARZA"


def test_clean_text_removes_punctuation_inserted_between_letters():
    assert clean_ocr_text("J;ORGE ENRIQUE CASTRO GARZA)") == "JORGE ENRIQUE CASTRO GARZA"


def test_visual_spacing_detects_four_word_regions():
    image = np.full((120, 1250), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "JORGE ENRIQUE CASTRO GARZA",
        (20, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.6,
        0,
        3,
        cv2.LINE_AA,
    )
    lines = _visual_word_boxes(image)
    assert len(lines) == 1
    assert len(lines[0]) == 4


def _fake_tesseract(*readings: tuple[str, float]):
    """Stand-in for pytesseract.image_to_data that answers each call with the next reading."""
    calls = {"count": 0}

    def image_to_data(*_args, **_kwargs) -> dict:
        text, confidence = readings[calls["count"] % len(readings)]
        calls["count"] += 1
        words = text.split()
        return {
            "text": words,
            "conf": [str(confidence)] * len(words),
            "block_num": [1] * len(words),
            "par_num": [1] * len(words),
            "line_num": [1] * len(words),
            "word_num": list(range(1, len(words) + 1)),
        }

    return image_to_data


def test_consistent_confident_readings_do_not_need_review(monkeypatch):
    monkeypatch.setattr("app.ocr.pytesseract.image_to_data", _fake_tesseract(("ANA LOPEZ", 92)))
    blank = np.full((60, 600, 3), 255, dtype=np.uint8)
    result = recognize_crop(blank, "spa")
    assert result["best"]["text"] == "ANA LOPEZ"
    assert result["best"]["needs_review"] is False


def test_disagreeing_readings_force_review_even_at_high_confidence(monkeypatch):
    readings = (("ANA LOPEZ", 95), ("ANA LOPES", 94))
    monkeypatch.setattr("app.ocr.pytesseract.image_to_data", _fake_tesseract(*readings))
    blank = np.full((60, 600, 3), 255, dtype=np.uint8)
    result = recognize_crop(blank, "spa")
    assert result["best"]["confidence"] >= 94
    assert result["best"]["needs_review"] is True
    assert {item["text"] for item in result["alternatives"]} == {"ANA LOPEZ", "ANA LOPES"}


def test_noisy_or_low_confidence_readings_need_review():
    assert _needs_review(OCRCandidate("ANA LOPEZ", 55.0, "contraste"))
    assert _needs_review(OCRCandidate("ANA | LOPEZ", 90.0, "contraste"))
    assert _needs_review(OCRCandidate("ANALOPEZGARCIA", 90.0, "contraste"))
    assert not _needs_review(OCRCandidate("ANA LOPEZ GARCIA", 90.0, "contraste"))

"""OCR text cleanup and visual word segmentation (no Tesseract needed)."""

import cv2
import numpy as np

from app.ocr import _visual_word_boxes, clean_ocr_text, join_name_parts


def test_clean_text_preserves_lines():
    cleaned = clean_ocr_text('  MARÍA   DEL CARMEN\n  DE LA GARZA  ')
    assert cleaned == 'MARÍA DEL CARMEN\nDE LA GARZA'


def test_join_name_parts_flattens_multiple_lines_and_regions():
    assert join_name_parts(['MARÍA DEL\nCARMEN', 'DE LA GARZA']) == 'MARÍA DEL CARMEN DE LA GARZA'


def test_clean_text_removes_punctuation_inserted_between_letters():
    assert clean_ocr_text('J;ORGE ENRIQUE CASTRO GARZA)') == 'JORGE ENRIQUE CASTRO GARZA'


def test_visual_spacing_detects_four_word_regions():
    image = np.full((120, 1250), 255, dtype=np.uint8)
    cv2.putText(
        image,
        'JORGE ENRIQUE CASTRO GARZA',
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

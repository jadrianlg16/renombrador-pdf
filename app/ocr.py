"""Page rendering and region OCR: preprocessing variants, Tesseract runs and ranking.

Every marked region is read several ways and the readings compete. The winner is
proposed, and the result is flagged for review whenever confidence is low, the text
looks noisy, or readings of similar confidence disagree.
"""

from __future__ import annotations

import base64
import difflib
import io
import re
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import pymupdf
import pytesseract
from PIL import Image
from pytesseract import Output


@dataclass
class OCRCandidate:
    """One reading of a region and how it was produced."""

    text: str
    confidence: float
    variant: str


NAME_WHITELIST = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1"
    "\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1"
    "'-"
)


def clean_ocr_text(text: str) -> str:
    """Collapse whitespace and strip stray punctuation from each line, keeping line breaks."""
    lines = []
    for line in text.replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"\s+", " ", line).strip(" \t|_:;,()[]{}")
        # Tesseract sometimes inserts punctuation between two letters.
        cleaned = re.sub(r"(?<=[^\W\d_])[;|_:](?=[^\W\d_])", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def join_name_parts(parts: list[str]) -> str:
    """Join the readings of several regions, and the lines inside them, into one name."""
    return re.sub(r"\s+", " ", " ".join(part.replace("\n", " ") for part in parts)).strip()


def _encode_png(image: np.ndarray) -> str:
    """Encode an OpenCV image as base64 PNG for the review panel."""
    if len(image.shape) == 2:
        pil_image = Image.fromarray(image)
    else:
        pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def render_page(pdf_path: str, page_number: int, dpi: int) -> tuple[bytes, int]:
    """Render one page (1-based) as PNG bytes; returns the image and the page count."""
    with pymupdf.open(pdf_path) as document:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError("Página fuera de rango")
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        return pixmap.tobytes("png"), document.page_count


def render_crop(
    pdf_path: str,
    page_number: int,
    selection: dict[str, Any],
    dpi: int,
) -> np.ndarray:
    """Render just the selected region of a page at ``dpi`` as a BGR image.

    The selection is in page fractions; a small margin is added around it.
    """
    with pymupdf.open(pdf_path) as document:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError("Página fuera de rango")
        page = document.load_page(page_number - 1)
        page_rect = page.rect
        x = max(0.0, min(1.0, float(selection["x"])))
        y = max(0.0, min(1.0, float(selection["y"])))
        width = max(0.001, min(1.0 - x, float(selection["width"])))
        height = max(0.001, min(1.0 - y, float(selection["height"])))

        # A forgiving safety margin recovers glyph edges when the user starts or
        # ends the rectangle a few pixels inside the first/last letter.
        pad_x = min(max(width * 0.01, 0.0015), 0.003)
        pad_y = min(max(height * 0.15, 0.001), 0.004)
        x0 = max(0.0, x - pad_x)
        y0 = max(0.0, y - pad_y)
        x1 = min(1.0, x + width + pad_x)
        y1 = min(1.0, y + height + pad_y)

        clip = pymupdf.Rect(
            page_rect.x0 + x0 * page_rect.width,
            page_rect.y0 + y0 * page_rect.height,
            page_rect.x0 + x1 * page_rect.width,
            page_rect.y0 + y1 * page_rect.height,
        )
        pixmap = page.get_pixmap(dpi=dpi, clip=clip, alpha=False)
        array = np.frombuffer(pixmap.samples, dtype=np.uint8)
        array = array.reshape(pixmap.height, pixmap.width, pixmap.n)
        if pixmap.n == 4:
            array = cv2.cvtColor(array, cv2.COLOR_RGBA2BGR)
        else:
            array = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
        return array


def _variants(image: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Return named preprocessing variants (contrast, denoise, two binarizations, sharpen)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.shape[1] < 1000:
        scale = min(3.0, max(1.5, 1200 / max(gray.shape[1], 1)))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(gray)
    denoised = cv2.fastNlMeansDenoising(clahe, None, 10, 7, 21)
    threshold = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        12,
    )
    _, otsu = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    sharpened = cv2.addWeighted(clahe, 1.5, cv2.GaussianBlur(clahe, (0, 0), 1.2), -0.5, 0)
    return [
        ("contraste", clahe),
        ("limpieza", denoised),
        ("binarizacion adaptativa", threshold),
        ("binarizacion Otsu", otsu),
        ("enfoque", sharpened),
    ]


def _run_tesseract(image: np.ndarray, languages: str, psm: int, variant: str) -> OCRCandidate:
    """Read one image with Tesseract, rebuilding lines from its word boxes."""
    config = f"--oem 3 --psm {psm} -c preserve_interword_spaces=1"
    data = pytesseract.image_to_data(image, lang=languages, config=config, output_type=Output.DICT)
    words: list[str] = []
    confidences: list[float] = []
    lines: dict[tuple[int, int, int], list[tuple[int, str]]] = {}

    for index, raw_text in enumerate(data.get("text", [])):
        text = raw_text.strip()
        try:
            confidence = float(data["conf"][index])
        except (ValueError, TypeError, KeyError):
            confidence = -1
        if not text:
            continue
        key = (
            int(data.get("block_num", [0])[index]),
            int(data.get("par_num", [0])[index]),
            int(data.get("line_num", [0])[index]),
        )
        lines.setdefault(key, []).append((int(data.get("word_num", [0])[index]), text))
        words.append(text)
        if confidence >= 0:
            confidences.append(confidence)

    ordered_lines = [
        " ".join(text for _, text in sorted(line_words)) for _, line_words in sorted(lines.items())
    ]
    text = clean_ocr_text("\n".join(ordered_lines) if ordered_lines else " ".join(words))
    confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    return OCRCandidate(text=text, confidence=confidence, variant=f"{variant} - PSM {psm}")


def _active_runs(mask: np.ndarray, gap_tolerance: int = 0) -> list[tuple[int, int]]:
    """Return [start, end) runs of True in a 1-D mask, bridging gaps up to ``gap_tolerance``."""
    indexes = np.flatnonzero(mask)
    if indexes.size == 0:
        return []
    runs: list[tuple[int, int]] = []
    start = int(indexes[0])
    previous = int(indexes[0])
    for raw_index in indexes[1:]:
        index = int(raw_index)
        if index - previous > gap_tolerance + 1:
            runs.append((start, previous + 1))
            start = index
        previous = index
    runs.append((start, previous + 1))
    return runs


def _visual_word_boxes(gray: np.ndarray) -> list[list[tuple[int, int, int, int]]]:
    """Return visual word boxes grouped by line, without trusting OCR spacing."""
    if gray.ndim != 2:
        raise ValueError("Expected a grayscale image")

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, ink = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    row_counts = np.count_nonzero(ink, axis=1)
    row_threshold = max(2, int(ink.shape[1] * 0.003))
    row_mask = row_counts >= row_threshold
    line_gap_tolerance = max(2, int(ink.shape[0] * 0.012))
    line_runs = _active_runs(row_mask, gap_tolerance=line_gap_tolerance)

    lines: list[list[tuple[int, int, int, int]]] = []
    for y0, y1 in line_runs:
        line_height = y1 - y0
        if line_height < 7:
            continue
        line_ink = ink[y0:y1, :]
        col_counts = np.count_nonzero(line_ink, axis=0)
        col_mask = col_counts >= max(1, int(line_height * 0.035))
        active_columns = np.flatnonzero(col_mask)
        if active_columns.size == 0:
            continue

        word_gap = max(6, int(line_height * 0.32))
        segments: list[tuple[int, int]] = []
        start = int(active_columns[0])
        previous = int(active_columns[0])
        for raw_column in active_columns[1:]:
            column = int(raw_column)
            if column - previous - 1 >= word_gap:
                segments.append((start, previous + 1))
                start = column
            previous = column
        segments.append((start, previous + 1))

        boxes: list[tuple[int, int, int, int]] = []
        for x0, x1 in segments:
            if x1 - x0 < 3:
                continue
            pad_x = max(2, int(line_height * 0.08))
            pad_y = max(2, int(line_height * 0.10))
            boxes.append(
                (
                    max(0, x0 - pad_x),
                    max(0, y0 - pad_y),
                    min(gray.shape[1], x1 + pad_x),
                    min(gray.shape[0], y1 + pad_y),
                )
            )
        if boxes:
            lines.append(boxes)
    return lines


def _run_word_tesseract(image: np.ndarray, languages: str) -> tuple[str, float]:
    """Read one word image limited to letters, apostrophe and hyphen, with no dictionary."""
    config = (
        "--oem 3 --psm 8 "
        f'-c tessedit_char_whitelist="{NAME_WHITELIST}" '
        "-c load_system_dawg=0 -c load_freq_dawg=0"
    )
    data = pytesseract.image_to_data(image, lang=languages, config=config, output_type=Output.DICT)
    pieces: list[str] = []
    confidences: list[float] = []
    for index, raw_text in enumerate(data.get("text", [])):
        piece = re.sub(r"\s+", "", raw_text or "")
        piece = piece.strip("|_:;,()[]{}")
        if not piece:
            continue
        pieces.append(piece)
        try:
            confidence = float(data["conf"][index])
        except (ValueError, TypeError, KeyError):
            confidence = -1
        if confidence >= 0:
            confidences.append(confidence)
    text = "".join(pieces)
    if not any(character.isalpha() for character in text):
        return "", 0.0
    confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    return text, confidence


def _visual_spacing_candidate(image: np.ndarray, languages: str) -> OCRCandidate | None:
    """Read word by word from the gaps in the ink, when Tesseract's own spacing is wrong.

    Tesseract can merge or split words on a scan; cutting the line at the visual gaps
    first rebuilds the spaces. Returns None unless it finds two or more words.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.shape[1] < 1000:
        scale = min(3.0, max(1.5, 1200 / max(gray.shape[1], 1)))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    line_boxes = _visual_word_boxes(gray)
    if not line_boxes:
        return None

    line_texts: list[str] = []
    confidences: list[float] = []
    detected_words = 0
    for boxes in line_boxes:
        words: list[str] = []
        for x0, y0, x1, y1 in boxes:
            word_image = gray[y0:y1, x0:x1]
            text, confidence = _run_word_tesseract(word_image, languages)
            if text:
                words.append(text)
                detected_words += 1
                if confidence >= 0:
                    confidences.append(confidence)
        if words:
            line_texts.append(" ".join(words))

    text = clean_ocr_text("\n".join(line_texts))
    # The method is useful only when it actually reconstructs word boundaries.
    if not text or detected_words < 2:
        return None
    confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    return OCRCandidate(text=text, confidence=confidence, variant="espacios visuales")


def _candidate_score(candidate: OCRCandidate) -> float:
    """Rank a reading: confidence plus bonuses for name-like text, penalties for noise."""
    text = re.sub(r"\s+", " ", candidate.text).strip()
    if not text:
        return -1000.0
    letters = sum(character.isalpha() for character in text)
    non_space = sum(not character.isspace() for character in text)
    alpha_ratio = letters / max(non_space, 1)
    tokens = text.split()
    longest = max((len(token) for token in tokens), default=0)
    suspicious = sum(character in ";|_:()[]{}<>" for character in text)

    score = candidate.confidence
    score += alpha_ratio * 24
    score -= suspicious * 18
    score -= max(0, longest - 15) * 2.5
    if 2 <= len(tokens) <= 8:
        score += 9
    if len(tokens) == 1 and letters >= 13:
        score -= 15
    if candidate.variant == "espacios visuales":
        score += 8
    return score


def _needs_review(candidate: OCRCandidate) -> bool:
    """Flag a reading with low confidence, stray punctuation, or one suspiciously long word."""
    flat = re.sub(r"\s+", " ", candidate.text).strip()
    tokens = flat.split()
    longest = max((len(token) for token in tokens), default=0)
    has_noise = bool(re.search(r"[;|_:()\[\]{}<>]", flat))
    return candidate.confidence < 60 or has_noise or (len(tokens) == 1 and longest >= 13)


def _candidates_disagree(ranked: list[OCRCandidate]) -> bool:
    """Tell whether readings of similar confidence say something different from the winner.

    A 95% reading can still be wrong; if another strong reading differs (difflib ratio
    below 0.985 after dropping spaces and punctuation), a person has to look.
    """
    if len(ranked) < 2:
        return False
    best = ranked[0]
    best_text = re.sub(r"[^\w]+", "", best.text, flags=re.UNICODE).casefold()
    if not best_text:
        return True
    comparable = [
        item for item in ranked[1:5] if item.confidence >= max(45.0, best.confidence - 18.0)
    ]
    for item in comparable:
        other = re.sub(r"[^\w]+", "", item.text, flags=re.UNICODE).casefold()
        if not other:
            continue
        similarity = difflib.SequenceMatcher(None, best_text, other).ratio()
        if similarity < 0.985:
            return True
    return False


def recognize_crop(image: np.ndarray, languages: str) -> dict[str, Any]:
    """Read one region every way, rank the readings, and return the best with alternatives."""
    candidates: list[OCRCandidate] = []
    region_is_multiline = image.shape[0] / max(image.shape[1], 1) > 0.12
    psms = [7, 13] if not region_is_multiline else [6, 11]

    visual_candidate = _visual_spacing_candidate(image, languages)
    if visual_candidate:
        candidates.append(visual_candidate)

    variants = _variants(image)
    for variant_name, variant_image in variants:
        for psm in psms:
            candidate = _run_tesseract(variant_image, languages, psm, variant_name)
            if candidate.text:
                candidates.append(candidate)

    deduplicated: dict[str, OCRCandidate] = {}
    for candidate in candidates:
        key = re.sub(r"\s+", " ", candidate.text).strip().casefold()
        existing = deduplicated.get(key)
        if not existing or _candidate_score(candidate) > _candidate_score(existing):
            deduplicated[key] = candidate

    ranked = sorted(
        deduplicated.values(),
        key=lambda item: (_candidate_score(item), item.confidence, len(item.text)),
        reverse=True,
    )
    best = ranked[0] if ranked else OCRCandidate("", 0.0, "sin resultado")
    disagreement = _candidates_disagree(ranked)
    enhanced = variants[0][1]
    return {
        "best": {
            "text": best.text,
            "confidence": best.confidence,
            "variant": best.variant,
            "needs_review": _needs_review(best) or disagreement,
        },
        "alternatives": [
            {
                "text": item.text,
                "confidence": item.confidence,
                "variant": item.variant,
                "needs_review": _needs_review(item),
            }
            for item in ranked[:8]
        ],
        "preview_original": _encode_png(image),
        "preview_enhanced": _encode_png(enhanced),
    }


def recognize_selections(
    pdf_path: str,
    selections: list[dict[str, Any]],
    dpi: int,
    languages: str,
) -> dict[str, Any]:
    """Read each selection in order and join the best readings into one proposed name."""
    regions: list[dict[str, Any]] = []
    best_parts: list[str] = []
    for index, selection in enumerate(selections):
        image = render_crop(pdf_path, int(selection["page"]), selection, dpi)
        result = recognize_crop(image, languages)
        result["selection_index"] = index
        result["page"] = int(selection["page"])
        regions.append(result)
        best_parts.append(result["best"]["text"])

    joined = join_name_parts(best_parts)
    confidences = [region["best"]["confidence"] for region in regions if region["best"]["text"]]
    confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    needs_review = (
        confidence < 60
        or any(region["best"].get("needs_review", True) for region in regions)
        or not joined
    )
    return {
        "joined_text": joined,
        "confidence": confidence,
        "needs_review": needs_review,
        "regions": regions,
    }

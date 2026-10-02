"""Settings read from environment variables, and Tesseract discovery."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytesseract

from .security import parse_allowed_hosts


@dataclass(frozen=True)
class Settings:
    """Paths and OCR options the app runs with; see the Configuration table in the README."""

    base_dir: Path
    input_dir: Path
    state_dir: Path
    database_path: Path
    render_dpi: int
    ocr_dpi: int
    ocr_languages: str
    allowed_hosts: frozenset[str]


def _resolve_path(value: str | None, default: Path) -> Path:
    """Return the configured path made absolute, or the default when unset."""
    if not value:
        return default.resolve()
    return Path(value).expanduser().resolve()


def configure_tesseract() -> str | None:
    """Point pytesseract at the first Tesseract found and return its path.

    Order: TESSERACT_CMD, PATH, then the two default folders of the Windows installer.
    Returns None when none exists; OCR requests then fail with a 503 that says so.
    """
    explicit = os.getenv("TESSERACT_CMD")
    candidates = [
        explicit,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return str(candidate)
    return None


def get_settings() -> Settings:
    """Read the settings, create the inbox and state folders, and locate Tesseract."""
    base_dir = Path(__file__).resolve().parent.parent
    input_dir = _resolve_path(os.getenv("PDF_INPUT_DIR"), base_dir / "data" / "inbox")
    state_dir = _resolve_path(os.getenv("PDF_STATE_DIR"), base_dir / "data" / "state")
    input_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    configure_tesseract()
    return Settings(
        base_dir=base_dir,
        input_dir=input_dir,
        state_dir=state_dir,
        database_path=state_dir / "renamer.db",
        render_dpi=int(os.getenv("PDF_RENDER_DPI", "150")),
        ocr_dpi=int(os.getenv("PDF_OCR_DPI", "450")),
        ocr_languages=os.getenv("OCR_LANGUAGES", "spa+eng"),
        allowed_hosts=parse_allowed_hosts(os.getenv("ALLOWED_HOSTS")),
    )

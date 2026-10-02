"""Filename and upload-path sanitizing, and collision-free target names."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sanitize_pdf_name(value: str) -> str:
    """Turn an approved name into a Windows-safe ``.pdf`` filename.

    Keeps accents (NFC), replaces characters Windows rejects with spaces, trims dots and
    spaces at the ends, drops a typed ``.pdf`` and suffixes reserved device names such
    as ``CON``. Raises ValueError when nothing is left.
    """
    value = unicodedata.normalize("NFC", value or "")
    value = value.replace("\n", " ").replace("\r", " ")
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1F]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if value.lower().endswith(".pdf"):
        value = value[:-4].strip(" .")
    if not value:
        raise ValueError("El nombre no puede estar vacío")
    if value.upper() in WINDOWS_RESERVED:
        value = f"{value}_"
    return f"{value}.pdf"


MAX_COMPONENT_LENGTH = 120


def sanitize_path_component(value: str) -> str:
    """Clean one path segment; returns "" when nothing usable is left."""
    value = unicodedata.normalize("NFC", value or "")
    # Only a drive letter is dropped; any other ":" becomes a space.
    value = re.sub(r"^[A-Za-z]:", "", value)
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1F]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value or value in {".", ".."}:
        return ""
    stem, dot, suffix = value.rpartition(".")
    if dot and 0 < len(suffix) <= 8 and len(value) > MAX_COMPONENT_LENGTH:
        value = f"{stem[: MAX_COMPONENT_LENGTH - len(suffix) - 1].strip(' .')}.{suffix}"
    else:
        value = value[:MAX_COMPONENT_LENGTH].strip(" .")
    if not value:
        return ""
    parsed = Path(value)
    if parsed.stem.upper() in WINDOWS_RESERVED:
        value = f"{parsed.stem}_{parsed.suffix}"
    return value


def sanitize_folder_name(value: str) -> str:
    """Return a one-level batch name, ignoring any path the browser sent with it."""
    parts = [part for part in re.split(r"[\\/]+", value or "") if part]
    return sanitize_path_component(parts[-1]) if parts else ""


def safe_upload_relative_path(value: str) -> str | None:
    """Turn a browser-sent filename into a safe relative path to a PDF, or None.

    Every segment is cleaned, ``..`` and drive letters disappear, and only the last six
    levels are kept, so the result can only point inside the folder it is joined to.
    """
    components = []
    for raw in re.split(r"[\\/]+", value or ""):
        component = sanitize_path_component(raw)
        if component:
            components.append(component)
    if not components:
        return None
    filename = components[-1]
    if not filename.lower().endswith(".pdf") or len(filename) <= 4:
        return None
    return "/".join(components[-6:])


def unique_directory(parent: Path, name: str) -> Path:
    """Return ``parent/name``, or ``name (2)``, ``name (3)``... if that folder exists."""
    candidate = parent / name
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = parent / f"{name} ({counter})"
        if not candidate.exists():
            return candidate
        counter += 1


def unique_target(directory: Path, filename: str, current_path: Path | None = None) -> Path:
    """Return a path for ``filename`` in ``directory`` that doesn't overwrite another file.

    Adds `` (2)``, `` (3)``... on a clash. ``current_path`` is the file being renamed, which
    may keep its own name.
    """
    candidate = directory / filename
    if current_path and candidate.resolve() == current_path.resolve():
        return candidate
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        is_current = current_path is not None and candidate.resolve() == current_path.resolve()
        if not candidate.exists() or is_current:
            return candidate
        counter += 1

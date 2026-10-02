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
    """Limpia un solo segmento de ruta y devuelve cadena vacía si no queda nada útil."""
    value = unicodedata.normalize("NFC", value or "")
    # Sólo la letra de unidad se descarta; los demás ":" pasan a ser espacios.
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
    """Nombre de lote de un solo nivel; ignora cualquier ruta que venga del navegador."""
    parts = [part for part in re.split(r"[\\/]+", value or "") if part]
    return sanitize_path_component(parts[-1]) if parts else ""


def safe_upload_relative_path(value: str) -> str | None:
    """Convierte el nombre enviado por el navegador en una ruta relativa segura a un PDF."""
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

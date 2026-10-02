from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath

import pymupdf
import pytesseract
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .config import get_settings
from .database import Database
from .models import ApproveRequest, OCRRequest
from .naming import (
    safe_upload_relative_path,
    sanitize_folder_name,
    sanitize_pdf_name,
    unique_directory,
    unique_target,
)
from .ocr import recognize_selections, render_page
from .security import BodySizeLimitMiddleware, SameOriginMiddleware


APP_VERSION = "1.2.0"
# Cap on one upload request. The browser sends one file per request once a file is
# larger than its 40 MB batch size, so this is also the largest PDF that can be added.
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
# Every other request carries a small JSON body (or none).
MAX_REQUEST_BYTES = 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024

settings = get_settings()
database = Database(settings)
STATIC_DIR = settings.base_dir / "app" / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Rescan the inbox on startup so files copied in while the app was stopped show up."""
    database.sync_documents()
    yield


app = FastAPI(title="Renombrador PDF", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    BodySizeLimitMiddleware,
    limits={"/api/upload": MAX_UPLOAD_BYTES},
    default_limit=MAX_REQUEST_BYTES,
)
# Added last so it runs first: a cross-site request is refused before its body is read.
app.add_middleware(SameOriginMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _get_document_or_404(document_id: str) -> dict:
    document = database.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return document


def _document_path(document: dict) -> Path:
    path = (settings.input_dir / document["current_relative_path"]).resolve()
    try:
        path.relative_to(settings.input_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ruta de documento inválida") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="El archivo ya no existe en la carpeta")
    return path


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/api/health")
def health() -> dict:
    try:
        languages = pytesseract.get_languages(config="")
        tesseract_ready = True
    except Exception:
        languages = []
        tesseract_ready = False
    return {
        "ok": True,
        "app_id": "renombrador-pdf",
        "version": APP_VERSION,
        "input_dir": str(settings.input_dir),
        "tesseract_ready": tesseract_ready,
        "ocr_languages": settings.ocr_languages,
        "available_languages": languages,
    }


@app.get("/api/config")
def client_config() -> dict:
    return {"max_upload_bytes": MAX_UPLOAD_BYTES}


@app.post("/api/sync")
def sync() -> dict:
    return database.sync_documents()


@app.get("/api/documents")
def list_documents() -> dict:
    documents = database.list_documents()
    counts = {status: 0 for status in ("pending", "approved", "skipped", "missing")}
    for document in documents:
        counts[document["status"]] = counts.get(document["status"], 0) + 1
    return {"documents": documents, "counts": counts, "total": len(documents)}


@app.get("/api/documents/{document_id}")
def get_document(document_id: str) -> dict:
    document = _get_document_or_404(document_id)
    path = _document_path(document)
    try:
        with pymupdf.open(path) as pdf:
            page_count = pdf.page_count
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"No se pudo abrir el PDF: {exc}") from exc
    if document.get("page_count") != page_count:
        database.update_page_count(document_id, page_count)
        document["page_count"] = page_count
    return document


@app.get("/api/documents/{document_id}/file")
def get_document_file(document_id: str) -> FileResponse:
    document = _get_document_or_404(document_id)
    return FileResponse(_document_path(document), media_type="application/pdf", filename=document["current_name"])


@app.get("/api/documents/{document_id}/page/{page_number}")
def get_document_page(
    document_id: str,
    page_number: int,
    dpi: int = Query(default=settings.render_dpi, ge=72, le=250),
) -> Response:
    document = _get_document_or_404(document_id)
    path = _document_path(document)
    try:
        image, page_count = render_page(str(path), page_number, dpi)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"No se pudo renderizar el PDF: {exc}") from exc
    if document.get("page_count") != page_count:
        database.update_page_count(document_id, page_count)
    return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/documents/{document_id}/ocr")
def ocr_document(document_id: str, request: OCRRequest) -> dict:
    document = _get_document_or_404(document_id)
    path = _document_path(document)
    selections = [selection.model_dump() for selection in request.selections]
    try:
        result = recognize_selections(
            str(path), selections, settings.ocr_dpi, settings.ocr_languages
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Tesseract no está instalado o no fue encontrado. Configura TESSERACT_CMD.",
        ) from exc
    except pytesseract.TesseractError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Tesseract no pudo ejecutar el OCR: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Falló el OCR: {exc}") from exc

    database.save_ocr(
        document_id,
        proposed_name=result["joined_text"],
        ocr_text=result["joined_text"],
        selections=selections,
    )
    return result


@app.post("/api/documents/{document_id}/approve")
def approve_document(document_id: str, request: ApproveRequest) -> dict:
    document = _get_document_or_404(document_id)
    source = _document_path(document)
    try:
        safe_filename = sanitize_pdf_name(request.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target = unique_target(source.parent, safe_filename, current_path=source)
    if target != source:
        try:
            source.rename(target)
        except OSError as exc:
            raise HTTPException(status_code=409, detail=f"No se pudo renombrar: {exc}") from exc

    before_relative = source.relative_to(settings.input_dir).as_posix()
    after_relative = target.relative_to(settings.input_dir).as_posix()
    database.mark_approved(
        document_id=document_id,
        before_path=before_relative,
        after_path=after_relative,
        proposed_name=target.stem,
        ocr_text=request.ocr_text,
        selections=[selection.model_dump() for selection in request.selections],
    )
    return {
        "ok": True,
        "document_id": document_id,
        "before": before_relative,
        "after": after_relative,
        "filename": target.name,
    }


@app.post("/api/documents/{document_id}/skip")
def skip_document(document_id: str) -> dict:
    _get_document_or_404(document_id)
    database.mark_skipped(document_id)
    return {"ok": True}


@app.post("/api/undo-last")
def undo_last() -> dict:
    action = database.latest_undoable_rename()
    if not action:
        raise HTTPException(status_code=404, detail="No hay cambios de nombre para deshacer")
    current = (settings.input_dir / action["after_relative_path"]).resolve()
    original = (settings.input_dir / action["before_relative_path"]).resolve()
    if not current.exists():
        raise HTTPException(status_code=409, detail="El archivo renombrado ya no existe")
    if original.exists() and original != current:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede restaurar porque ya existe: {original.name}",
        )
    try:
        current.rename(original)
    except OSError as exc:
        raise HTTPException(status_code=409, detail=f"No se pudo deshacer: {exc}") from exc
    restored_relative = original.relative_to(settings.input_dir).as_posix()
    database.complete_undo(action["id"], action["document_id"], restored_relative)
    return {"ok": True, "restored": restored_relative, "document_id": action["document_id"]}


@app.get("/api/history")
def history(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    return {"actions": database.history(limit)}


def batch_of(relative_path: str) -> str:
    """Carpeta de primer nivel dentro de la bandeja; cadena vacía para la raíz."""
    parts = PurePosixPath(relative_path).parts
    return parts[0] if len(parts) > 1 else ""


def _resolve_batch_dir(folder: str | None, batch: str | None) -> Path:
    if batch:
        name = sanitize_folder_name(batch)
        candidate = settings.input_dir / name if name else None
        if not name or not candidate.is_dir():
            raise HTTPException(status_code=400, detail="El lote indicado ya no existe")
        return candidate
    name = sanitize_folder_name(folder or "")
    if not name:
        name = f"lote-{datetime.now():%Y%m%d-%H%M%S}"
    directory = unique_directory(settings.input_dir, name)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def _store_upload(upload: UploadFile, batch_dir: Path) -> tuple[str | None, str | None]:
    """Guarda un PDF dentro del lote. Devuelve (ruta_relativa, motivo_de_rechazo)."""
    relative = safe_upload_relative_path(upload.filename or "")
    if not relative:
        return None, "Sólo se aceptan archivos .pdf"

    destination_dir = (batch_dir / relative).parent
    try:
        destination_dir.resolve().relative_to(settings.input_dir.resolve())
    except ValueError:
        return None, "Ruta de archivo inválida"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_target(destination_dir, PurePosixPath(relative).name)

    header = await upload.read(5)
    if header[:5] != b"%PDF-":
        return None, "El archivo no es un PDF válido"

    with destination.open("wb") as handle:
        handle.write(header)
        while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
            handle.write(chunk)
    return destination.relative_to(settings.input_dir).as_posix(), None


@app.post("/api/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    folder: str | None = Form(default=None),
    batch: str | None = Form(default=None),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No se recibió ningún archivo")
    batch_dir = _resolve_batch_dir(folder, batch)

    saved: list[str] = []
    rejected: list[dict[str, str]] = []
    for upload in files:
        try:
            relative, reason = await _store_upload(upload, batch_dir)
        except OSError as exc:
            relative, reason = None, f"No se pudo guardar: {exc}"
        finally:
            await upload.close()
        if relative:
            saved.append(relative)
        else:
            rejected.append({"name": upload.filename or "(sin nombre)", "reason": reason or "Rechazado"})

    batch_name = batch_dir.relative_to(settings.input_dir).as_posix()
    if saved:
        database.register_batch(batch_name)
    sync_result = database.sync_documents()
    return {
        "ok": True,
        "batch": batch_name,
        "saved": len(saved),
        "files": saved,
        "rejected": rejected,
        "sync": sync_result,
    }


@app.get("/api/batches")
def list_batches() -> dict:
    registered = {row["name"]: row for row in database.list_batches()}
    totals: dict[str, dict[str, int]] = {}
    for document in database.list_documents():
        if document["status"] == "missing":
            continue
        name = batch_of(document["current_relative_path"])
        bucket = totals.setdefault(name, {"documents": 0, "approved": 0, "pending": 0})
        bucket["documents"] += 1
        if document["status"] == "approved":
            bucket["approved"] += 1
        elif document["status"] == "pending":
            bucket["pending"] += 1

    batches = []
    for name in sorted(set(totals) | set(registered)):
        row = registered.get(name)
        bucket = totals.get(name, {"documents": 0, "approved": 0, "pending": 0})
        batches.append(
            {
                "name": name,
                **bucket,
                # Los PDF sueltos en la raíz de la bandeja no forman lote y nunca se borran.
                "deletable": bool(name) and bool(row),
                "source": row["source"] if row else None,
                "created_at": row["created_at"] if row else None,
                "exported_at": row["exported_at"] if row else None,
            }
        )
    return {"batches": batches, "latest_upload": database.latest_batch()}


@app.post("/api/batches/{batch_name}/delete")
def delete_batch(batch_name: str) -> dict:
    row = database.get_batch(batch_name)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Ese lote no existe en la bandeja, así que no hay nada que borrar.",
        )
    name = row["name"]
    inbox = settings.input_dir.resolve()
    directory = (settings.input_dir / name).resolve()
    if directory == inbox:
        raise HTTPException(status_code=400, detail="No se puede borrar la carpeta raíz")
    try:
        directory.relative_to(inbox)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ruta de lote inválida") from exc

    removed_files = 0
    if directory.is_dir():
        removed_files = sum(1 for item in directory.rglob("*") if item.is_file())
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"No se pudo borrar la carpeta del lote: {exc}",
            ) from exc

    removed_documents = database.delete_batch(name)
    return {
        "ok": True,
        "batch": name,
        "files": removed_files,
        "documents": removed_documents,
    }


@app.get("/api/export")
def export_zip(
    scope: str = Query(default="approved", pattern="^(approved|all)$"),
    folder: str | None = Query(default=None),
) -> FileResponse:
    entries: list[tuple[Path, str]] = []
    exported_batches: set[str] = set()
    for document in database.list_documents():
        if document["status"] == "missing":
            continue
        if scope == "approved" and document["status"] != "approved":
            continue
        relative = PurePosixPath(document["current_relative_path"])
        document_batch = batch_of(document["current_relative_path"])
        if folder is not None and document_batch != folder:
            continue
        path = settings.input_dir / relative
        if not path.is_file():
            continue
        if document_batch:
            exported_batches.add(document_batch)
        # Al exportar un solo lote el ZIP se abre directo en los archivos; al
        # exportar todo se conservan las carpetas para no mezclar lotes.
        if folder and document_batch:
            arcname = relative.relative_to(document_batch).as_posix()
        else:
            arcname = relative.as_posix()
        entries.append((path, arcname))

    if not entries:
        raise HTTPException(
            status_code=404,
            detail="No hay archivos para exportar con ese filtro. Aprueba al menos un documento.",
        )

    export_dir = settings.state_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    handle, temporary_path = tempfile.mkstemp(suffix=".zip", dir=export_dir)
    archive_path = Path(temporary_path)
    try:
        with open(handle, "wb") as stream:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                used: set[str] = set()
                for path, arcname in entries:
                    unique_name = arcname
                    counter = 2
                    while unique_name.lower() in used:
                        stem = PurePosixPath(arcname)
                        unique_name = f"{stem.with_suffix('')} ({counter}){stem.suffix}"
                        counter += 1
                    used.add(unique_name.lower())
                    archive.write(path, unique_name)
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    # Se marca antes de enviar: el aviso de "todavía no descargas este lote" que protege
    # al botón de borrar debe apagarse aunque el navegador cancele la descarga a medias.
    database.mark_batches_exported(sorted(exported_batches))

    label = (sanitize_folder_name(folder) or "raiz") if folder is not None else "todo"
    scope_label = "aprobados" if scope == "approved" else "todos"
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"renombrados-{label}-{scope_label}.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )
